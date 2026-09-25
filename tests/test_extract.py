"""Document -> candidate triples -> a verdict per row -> the graph.

The two halves are tested apart and then together: what the prompt is
built from (extract), what an incoming row would do (merge), and the
whole path end to end with a stand-in model, because the seam between
them — the list-of-dicts shape the importers already speak — is the
thing that lets the model be replaced without touching anything below.
"""
import ast
import json
from pathlib import Path

import pytest

from trikedb import OntologyError, TrikeDB
from trikedb import extract as extract_mod
from trikedb import merge


@pytest.fixture
def graph(tmp_path):
    """A graph that declares enough to have opinions about what arrives."""
    db = TrikeDB(tmp_path / "g.yaml", ontology={
        "WORKS_AT": "who a person works for",
        "FOUNDED": "who started a company",
        "BASED_IN": "where a company is",
    })
    db.declare_link("WORKS_AT", domain="person", range="company")
    db.declare("WORKS_AT", "functional")
    db.set_node("Tanaka", type="person")
    db.set_node("Acme", type="company")
    db.set_node("Globex", type="company")
    db.add("Tanaka", "WORKS_AT", "Acme", prov="joined Acme")
    return db


# ------------------------------------------------------------------ merge


def test_preview_gives_a_verdict_per_row_and_writes_nothing(graph):
    before = len(graph)
    findings = graph.preview([
        {"s": "Tanaka", "p": "WORKS_AT", "o": "Acme", "prov": "joined Acme"},
        {"s": "Tanaka", "p": "WORKS_AT", "o": "Acme", "prov": "still there"},
        {"s": "Tanaka", "p": "WORKS_AT", "o": "Globex"},
        {"s": "Tanaka", "p": "EMPLOYED_BY", "o": "Acme"},
        {"s": "Acme", "p": "FOUNDED", "o": "Tanaka"},
    ])
    assert [f["verdict"] for f in findings] == [
        "same", "update", "conflict", "rejected", "new"]
    assert len(graph) == before
    assert TrikeDB(graph.path) is not None and len(TrikeDB(graph.path)) == before


def test_update_says_which_attributes_would_change(graph):
    finding, = graph.preview(
        [{"s": "Tanaka", "p": "WORKS_AT", "o": "Acme", "prov": "still there",
          "note": "new key"}])
    assert finding["verdict"] == "update"
    assert "prov: 'joined Acme' -> 'still there'" in finding["detail"]
    assert "+note=" in finding["detail"]
    assert finding["existing"]["prov"] == "joined Acme"


def test_conflict_needs_the_functional_declaration_to_exist(tmp_path):
    """Without the declaration there is no contradiction to find.

    Two objects for one subject is only wrong when the graph has said the
    predicate holds one. Guessing that from the data is how a tool starts
    calling two true facts a conflict.
    """
    db = TrikeDB(tmp_path / "loose.yaml", ontology={"WORKS_AT": ""})
    db.add("Tanaka", "WORKS_AT", "Acme")
    assert db.preview([{"s": "Tanaka", "p": "WORKS_AT", "o": "Globex"}]
                      )[0]["verdict"] == "new"
    db.declare("WORKS_AT", "functional")
    assert db.preview([{"s": "Tanaka", "p": "WORKS_AT", "o": "Globex"}]
                      )[0]["verdict"] == "conflict"


def test_two_incoming_rows_that_disagree_with_each_other_are_caught(graph):
    """The second would silently win if the batch were judged row by row
    against the graph alone — neither is in the file yet."""
    findings = graph.preview([
        {"s": "Sato", "p": "WORKS_AT", "o": "Acme"},
        {"s": "Sato", "p": "WORKS_AT", "o": "Globex"},
    ])
    assert [f["verdict"] for f in findings] == ["new", "conflict"]
    assert "already holds 'Acme'" in findings[1]["detail"]


def test_rejected_carries_the_reason_the_write_would_give(graph):
    predicate, shape, broken = graph.preview([
        {"s": "Tanaka", "p": "EMPLOYED_BY", "o": "Acme"},
        {"s": "Acme", "p": "WORKS_AT", "o": "Tanaka"},
        {"s": "Tanaka", "p": "WORKS_AT"},
    ])
    assert "not in the ontology" in predicate["detail"]
    assert "person -> company" in shape["detail"]
    assert "missing required key" in broken["detail"]
    # and the preview did not lie: the write refuses for the same reason
    with pytest.raises(OntologyError):
        graph.add("Tanaka", "EMPLOYED_BY", "Acme")


def test_a_fact_restated_without_its_date_says_it_would_land_beside_the_old_one(graph):
    """A triple's identity includes its time, so this really is a new row.

    That is right for events and wrong-feeling for facts, and the gap
    between the two is where silent duplicates come from. The verdict
    stays honest about what add() would do; the detail is what makes it
    reviewable.
    """
    graph.add("Acme", "BASED_IN", "Tokyo", at="2020-01-01", prov="the filing")
    undated, = graph.preview([{"s": "Acme", "p": "BASED_IN", "o": "Tokyo"}])
    assert undated["verdict"] == "new"
    assert "already states this, dated 2020-01-01" in undated["detail"]
    assert undated["existing"]["at"] == "2020-01-01"

    # two real dates are two records, and saying so every time is noise
    dated, = graph.preview([{"s": "Acme", "p": "BASED_IN", "o": "Tokyo",
                             "at": "2024-06-01"}])
    assert dated["verdict"] == "new" and "a second record" in dated["detail"]

    # and a genuinely unseen fact says nothing extra
    fresh, = graph.preview([{"s": "Globex", "p": "BASED_IN", "o": "Osaka"}])
    assert fresh["detail"] == "new fact"


def test_counts_and_blocking_summarize_a_run(graph):
    findings = graph.preview([
        {"s": "Tanaka", "p": "WORKS_AT", "o": "Globex"},
        {"s": "Tanaka", "p": "NOPE", "o": "x"},
        {"s": "Acme", "p": "BASED_IN", "o": "Tokyo"},
    ])
    assert merge.counts(findings) == {"conflict": 1, "rejected": 1, "new": 1}
    assert [f["verdict"] for f in merge.blocking(findings)] == ["conflict", "rejected"]


# ---------------------------------------------------------------- extract


def test_the_prompt_carries_the_graphs_own_vocabulary(graph):
    prompt = graph.extract_prompt("Sato joined Globex in April 2026.")
    assert "`WORKS_AT`" in prompt and "who a person works for" in prompt
    assert "person -> company" in prompt            # the declared shape
    assert "- Tanaka  (person)" in prompt           # existing entity, with its type
    assert "- Acme  (company)" in prompt
    assert "Sato joined Globex in April 2026." in prompt
    assert "| s | p | o | at | prov |" in prompt


def test_predicates_and_owl_bookkeeping_are_not_offered_as_entities(graph):
    """`declare(p, "functional")` stores a triple, so the predicate and an
    owl# URI become nodes. Neither is something a document mentions, and
    offering them invites a row the guardrail then has to reject."""
    prompt = graph.extract_prompt("Sato joined Globex.")
    entities = prompt.split("## Entities")[1].split("## What counts")[0]
    assert "- WORKS_AT" not in entities
    assert "owl#" not in entities and "://" not in entities
    assert "- Acme  (company)" in entities


def test_an_undeclared_graph_is_told_it_is_choosing_for_itself(tmp_path):
    prompt = TrikeDB(tmp_path / "empty.yaml").extract_prompt("hello")
    assert "declares no predicates yet" in prompt
    assert "The graph is empty" in prompt


def test_the_document_may_contain_braces(graph):
    """Rendering is literal replacement, not format() — a document full of
    JSON used to raise KeyError on its own contents."""
    assert '{"a": {"b": 1}}' in graph.extract_prompt('{"a": {"b": 1}}')


def test_parse_reads_a_fenced_table_and_skips_empty_cells():
    rows = extract_mod.parse(
        "Here you go:\n\n```markdown\n"
        "| s | p | o | at | prov |\n|---|---|---|---|---|\n"
        "| Tanaka | WORKS_AT | Acme | 2026-04-01 | joined Acme |\n"
        "| Acme | BASED_IN | Tokyo |  | based in Tokyo |\n"
        "```\n")
    assert rows == [
        {"s": "Tanaka", "p": "WORKS_AT", "o": "Acme",
         "at": "2026-04-01", "prov": "joined Acme"},
        {"s": "Acme", "p": "BASED_IN", "o": "Tokyo", "prov": "based in Tokyo"},
    ]


def test_parse_of_an_answer_with_no_facts_is_empty_not_an_error():
    assert extract_mod.parse("| s | p | o |\n|---|---|---|\n") == []


def test_extract_calls_the_callable_with_the_prompt(graph):
    seen = {}

    def llm(prompt):
        seen["prompt"] = prompt
        return "| s | p | o |\n|---|---|---|\n| Sato | WORKS_AT | Globex |\n"

    rows = graph.extract("Sato works at Globex.", llm=llm)
    assert rows == [{"s": "Sato", "p": "WORKS_AT", "o": "Globex"}]
    assert "Sato works at Globex." in seen["prompt"]
    assert "`WORKS_AT`" in seen["prompt"]
    assert len(graph) == 2          # 1 fact + the functional declaration


def test_extract_refuses_to_run_without_being_handed_a_model(graph):
    with pytest.raises(TypeError, match="llm="):
        graph.extract("anything", llm=None)


def test_extract_carries_no_provider(graph):
    """The module may not grow a vendor SDK, a client, or a socket.

    Declining to bundle providers is the feature — it is why `extract`
    costs nothing to install and cannot break when a vendor renames a
    parameter. A guarantee nothing checks is a guarantee until someone
    adds an import.
    """
    source = Path(extract_mod.__file__).read_text(encoding="utf-8")
    allowed = {"__future__", "typing", "trikedb"}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert node.level > 0 or root in allowed, f"extract imports {node.module}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in allowed, \
                    f"extract imports {alias.name}"


# -------------------------------------------------------------------- cli


def test_cli_extract_prints_a_prompt_built_from_the_graph(graph, capsys):
    from trikedb.cli import main

    assert main(["extract", str(graph.path), _doc(graph)]) == 0
    out = capsys.readouterr().out
    assert "`WORKS_AT`" in out and "- Acme  (company)" in out
    assert "Sato joined Globex" in out


def test_cli_extract_writes_the_prompt_and_says_what_to_do_next(graph, capsys, tmp_path):
    from trikedb.cli import main

    out_file = tmp_path / "prompt.txt"
    assert main(["extract", str(graph.path), _doc(graph), "-o", str(out_file)]) == 0
    assert "`WORKS_AT`" in out_file.read_text(encoding="utf-8")
    assert "--dry-run" in capsys.readouterr().out


def test_cli_extract_names_the_extra_when_semantic_search_is_missing(
        graph, monkeypatch, capsys):
    """The failure that only appears on a graph worth using.

    `--relevant-to` reaches for the vector index only when the graph
    holds more nodes than the prompt will list, so an install without
    the extra works on the graph someone tries first and breaks on the
    one they meant. A traceback would be the second surprise; naming
    the extra is the whole answer.
    """
    import sys

    from trikedb.cli import main

    monkeypatch.setitem(sys.modules, "numpy", None)
    code = main(["extract", str(graph.path), _doc(graph),
                 "--relevant-to", "who works where", "--limit", "1"])
    assert code == 2
    err = capsys.readouterr().err
    assert "pip install 'trikedb[semantic]'" in err
    assert "Traceback" not in err


def test_cli_import_dry_run_writes_nothing_and_fails_on_a_conflict(graph, capsys, tmp_path):
    from trikedb.cli import main

    source = tmp_path / "rows.md"
    source.write_text(
        "| s | p | o |\n|---|---|---|\n"
        "| Tanaka | WORKS_AT | Globex |\n"
        "| Acme | BASED_IN | Tokyo |\n", encoding="utf-8")
    before = len(TrikeDB(graph.path))

    assert main(["import", str(graph.path), str(source), "--dry-run"]) == 1
    out = capsys.readouterr().out
    assert "conflict" in out and "declared functional" in out
    assert "nothing written" in out
    assert len(TrikeDB(graph.path)) == before

    # the same file, minus the contested row, goes in cleanly
    source.write_text("| s | p | o |\n|---|---|---|\n| Acme | BASED_IN | Tokyo |\n",
                      encoding="utf-8")
    assert main(["import", str(graph.path), str(source), "--dry-run"]) == 0
    assert main(["import", str(graph.path), str(source)]) == 0
    assert len(TrikeDB(graph.path)) == before + 1


def test_cli_import_dry_run_json_is_machine_readable(graph, capsys, tmp_path):
    from trikedb.cli import main

    source = tmp_path / "rows.csv"
    source.write_text("s,p,o\nTanaka,WORKS_AT,Globex\n", encoding="utf-8")
    assert main(["import", str(graph.path), str(source), "-n", "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report[str(source)][0]["verdict"] == "conflict"


def _doc(graph) -> str:
    path = Path(graph.path).parent / "doc.md"
    path.write_text("Sato joined Globex in April 2026.", encoding="utf-8")
    return str(path)


def test_the_provider_examples_still_run(capsys):
    """examples/extract_providers.py is the documentation for `llm=`.

    Its demo needs no key and no network, so there is no reason for it to
    be the one file that quietly stops working.
    """
    import importlib.util

    path = Path(__file__).resolve().parent.parent / "examples" / "extract_providers.py"
    spec = importlib.util.spec_from_file_location("extract_providers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._demo()
    out = capsys.readouterr().out
    assert "conflict" in out and "declared functional" in out
    # every provider adapter is a factory that imports only when called
    for name in ("openai", "anthropic", "gemini", "litellm", "transcript"):
        assert callable(getattr(module, name))


# -------------------------------------------------------------------- mcp


def test_mcp_exposes_the_extraction_path(graph):
    pytest.importorskip("mcp")
    import asyncio

    from trikedb.mcp_server import build_server

    server = build_server(graph.path)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert {"extraction_prompt", "preview_triples", "add_triples"} <= names

    async def call(name, args):
        """The text of every content block — a returned list arrives as one each."""
        content = await server.call_tool(name, args)
        blocks = content[0] if isinstance(content, tuple) else content
        return [block.text for block in blocks]

    prompt, = asyncio.run(call("extraction_prompt", {"text": "Acme is in Tokyo."}))
    assert "`BASED_IN`" in prompt and "Acme is in Tokyo." in prompt

    verdicts = [json.loads(b) for b in asyncio.run(call("preview_triples", {"triples": [
        {"s": "Acme", "p": "BASED_IN", "o": "Tokyo"},
        {"s": "Tanaka", "p": "WORKS_AT", "o": "Globex"},
    ]}))]
    assert [v["verdict"] for v in verdicts] == ["new", "conflict"]
    assert "declared functional" in verdicts[1]["detail"]

    added, = asyncio.run(call("add_triples", {"triples": [
        {"s": "Acme", "p": "BASED_IN", "o": "Tokyo", "prov": "Acme is in Tokyo."}]}))
    assert json.loads(added)["added"] == 1
    assert ("Acme", "BASED_IN", "Tokyo") in TrikeDB(graph.path)


def test_mcp_add_triples_is_all_or_nothing(graph):
    pytest.importorskip("mcp")
    import asyncio

    from trikedb.mcp_server import build_server

    server = build_server(graph.path)
    before = len(TrikeDB(graph.path))
    with pytest.raises(Exception):
        asyncio.run(server.call_tool("add_triples", {"triples": [
            {"s": "Acme", "p": "BASED_IN", "o": "Tokyo"},
            {"s": "Acme", "p": "INVENTED", "o": "x"},
        ]}))
    assert len(TrikeDB(graph.path)) == before


# ------------------------------------------------------------------ evals


def _scorer():
    import importlib.util

    path = Path(__file__).resolve().parent.parent / "evals" / "score.py"
    spec = importlib.util.spec_from_file_location("evals_score", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_eval_case_is_answerable_and_its_gold_answer_is_perfect():
    """The fixtures, not the scorer, are what this protects.

    A gold answer that the scorer cannot score 1.0 is a broken fixture: a
    quote that is not verbatim, a predicate the graph does not declare, a
    name spelled two ways. Each of those is a defect the eval exists to
    measure, so having one in the answer sheet would make the measurement
    meaningless in the direction that flatters us.
    """
    score = _scorer()
    cases = score.cases()
    assert len(cases) >= 3
    for case in cases:
        db, document, gold = score.load(case)
        assert gold, f"{case.name} has no gold rows"
        result = score.score(db, document, gold, gold)
        assert result["f1"] == 1.0, f"{case.name}: {result}"
        assert (result["invented"], result["split"], result["unquotable"],
                result["blocked"]) == (0, 0, 0, 0), f"{case.name}: {result}"


def test_the_scorer_names_each_way_an_extraction_goes_wrong():
    score = _scorer()
    case, = [c for c in score.cases() if c.name == "vendor-memo"]
    db, document, gold = score.load(case)
    result = score.score(db, document, gold, [
        # the graph says "Tamaki Metals": true row, second node
        {"s": "Tamaki Metals Co., Ltd.", "p": "SUPPLIES", "o": "frames",
         "prov": "Tamaki Metals Co., Ltd. supplies our frames"},
        # a predicate nobody declared, so the write would refuse it
        {"s": "Nakano Rubber", "p": "HAS_LEAD_TIME", "o": "11 days",
         "prov": "Their lead time is eleven days"},
        # a quote that is not in the document
        {"s": "Tamaki Metals", "p": "SUPPLIES", "o": "excellent frames",
         "prov": "their frames are the best in the industry"},
        # and one that is simply right
        {"s": "Tamaki Metals", "p": "BASED_IN", "o": "Osaka",
         "prov": "They are based in Osaka"},
    ])
    assert result["invented"] == 1
    assert result["unquotable"] == 1
    assert result["blocked"] == 1                       # the same row, refused
    assert ["Tamaki Metals", "Tamaki Metals Co., Ltd."] in result["split_pairs"]
    assert result["hit"] == 1 and result["recall"] == 0.25


def test_folding_a_name_drops_the_legal_form_and_nothing_else():
    fold = _scorer().fold
    assert fold("Tamaki Metals Co., Ltd.") == fold("Tamaki Metals")
    assert fold("株式会社アクメ") == fold("アクメ")
    assert fold("グロベックス社") == fold("グロベックス")
    assert fold("Acme Inc.") == fold("acme")
    assert fold("田中 亮") != fold("田中")     # a surname is not a person


def test_the_scorer_fails_when_it_scored_nothing(tmp_path, capsys):
    """An eval that measures nothing must not report success.

    `--answers DIR` skips a case whose file is not there, and skipping
    every case used to print an empty table and exit 0 — green in CI,
    having checked nothing. That is the one outcome this file exists to
    make impossible.
    """
    assert _scorer().main(["--answers", str(tmp_path)]) == 2
    assert "nothing was measured" in capsys.readouterr().err


def test_the_baseline_prompt_supplies_no_vocabulary():
    """What the comparison is against, checked so it cannot drift into
    being a second constrained prompt."""
    from trikedb import prompts

    naive = prompts.render("triples-naive", text="Acme is in Tokyo.")
    assert "Acme is in Tokyo." in naive
    assert "| s | p | o |" in naive
    for constraint in ("Predicates you may use", "already exist in the graph",
                       "verbatim", "Do not infer"):
        assert constraint not in naive


# -------------------------------------------------------------------- e2e


def test_a_document_becomes_reviewed_facts_in_the_file(tmp_path):
    """The whole path, with the model standing in for itself.

    The stand-in reads the prompt the way a model would — it answers with
    the predicate the prompt offers and the spelling of the entity the
    prompt lists — which is exactly the behaviour the prompt exists to
    produce. What is being tested is that nothing between the document
    and the file drops, renames or silently overwrites a fact.
    """
    db = TrikeDB(tmp_path / "company.yaml",
                 ontology={"WORKS_AT": "who a person works for",
                           "BASED_IN": "where a company is"})
    db.declare_link("WORKS_AT", domain="person", range="company")
    db.declare("WORKS_AT", "functional")
    db.set_node("Acme", type="company")
    db.set_node("Tanaka", type="person")
    db.add("Tanaka", "WORKS_AT", "Acme", prov="Tanaka, of Acme")

    document = ("Acme Corp. moved its head office to Osaka last year. "
                "Sato, who joined the company in 2026, reports from there. "
                "Tanaka has since left for Globex.")

    def model(prompt):
        # The two things the prompt is for: use only declared predicates,
        # and reuse the spelling already in the graph ("Acme", not "Acme Corp.").
        assert "`WORKS_AT`" in prompt and "`BASED_IN`" in prompt
        assert "- Acme  (company)" in prompt
        return ("| s | p | o | at | prov |\n|---|---|---|---|---|\n"
                "| Acme | BASED_IN | Osaka | | moved its head office to Osaka |\n"
                "| Sato | WORKS_AT | Acme | 2026-01-01 | Sato, who joined the company |\n"
                "| Tanaka | WORKS_AT | Globex | | Tanaka has since left for Globex |\n")

    rows = db.extract(document, llm=model)
    assert len(rows) == 3

    findings = db.preview(rows)
    assert merge.counts(findings) == {"conflict": 1, "new": 2}

    # the contested row is held back; the rest go in
    keep = [f["triple"] for f in findings if f["verdict"] == "new"]
    with db.batch():
        for row in keep:
            d = dict(row)
            db.add(d.pop("s"), d.pop("p"), d.pop("o"), **d)
    db.save()

    on_disk = TrikeDB(tmp_path / "company.yaml")
    assert ("Acme", "BASED_IN", "Osaka") in on_disk
    assert ("Sato", "WORKS_AT", "Acme") in on_disk
    assert ("Tanaka", "WORKS_AT", "Globex") not in on_disk   # a human decides
    assert ("Tanaka", "WORKS_AT", "Acme") in on_disk         # not overwritten
    assert "Acme Corp." not in on_disk.nodes()               # not split in two

    # The graph then says what extraction could not: a person arrived from a
    # document, so nothing has checked that WORKS_AT's domain holds for them.
    warning, = on_disk.audit()
    assert warning["kind"] == "unchecked-link" and "'Sato' has no type" in warning["detail"]
    on_disk.set_node("Sato", type="person")
    assert on_disk.audit() == []
