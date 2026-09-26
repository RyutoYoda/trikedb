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
from trikedb import importers as importers_mod
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


def test_cli_extract_reads_a_word_file_without_being_told_to(graph, capsys, tmp_path):
    """The document people have is a .docx, not a Markdown file.

    Downloading a doc and pointing at it is the whole interaction; a
    step where the human converts the file first is where the path
    stops being used. The dispatch is on the suffix, so nothing about
    the command changes.
    """
    import io
    import zipfile

    from trikedb.cli import main

    path = tmp_path / "notice.docx"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:body><w:p><w:r>'
            "<w:t>Sato joined Globex in April.</w:t>"
            "</w:r></w:p></w:body></w:document>")
    path.write_bytes(buf.getvalue())

    assert main(["extract", str(graph.path), str(path)]) == 0
    out = capsys.readouterr().out
    assert "Sato joined Globex in April." in out     # the document went in
    assert "`WORKS_AT`" in out                       # the graph still built it


def test_relevance_offers_both_ends_of_a_matching_triple_once_each(tmp_path):
    """The two ways `limit` slots used to be wasted or misspent.

    Search ranks triples, and a triple is about both of its ends. Taking
    only the subject meant the top hit could offer the department and
    never the company it belongs to; and two triples sharing a subject
    spent two slots on one name. `limit` promises a number of names to
    offer, so it has to count names.
    """
    db = TrikeDB(tmp_path / "g.yaml", ontology={
        "BELONGS_TO": "which organisation something is part of",
        "LIKES": "what someone likes",
    })
    db.add("Data Platform", "BELONGS_TO", "Acme")
    db.add("Suzuki", "BELONGS_TO", "Data Platform")
    db.add("Kobayashi", "LIKES", "Ramen")
    db.add("Kobayashi", "LIKES", "Kyoto")

    db.search = lambda query, k=10: [
        {"kind": "triple", "s": "Data Platform", "p": "BELONGS_TO", "o": "Acme"},
        {"kind": "triple", "s": "Kobayashi", "p": "LIKES", "o": "Ramen"},
        {"kind": "triple", "s": "Kobayashi", "p": "LIKES", "o": "Kyoto"},
    ][:k]

    prompt = extract_mod.prompt_for(db, "a reorganisation",
                                    relevant_to="a reorganisation", limit=3)
    section = prompt.split("## Entities")[1].split("If something")[0]
    offered = [line[2:] for line in section.splitlines()
               if line.startswith("- ")]

    # Acme is the object of the best hit and a subject of nothing.
    assert offered == ["Data Platform", "Acme", "Kobayashi"]
    assert len(offered) == len(set(offered))


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


def _as_docx(path, body: str) -> None:
    """Write a .docx whose body is exactly this WordprocessingML.

    Built rather than committed as a binary for the reason the reader
    exists at all: a .docx is legible, and a fixture you can read in the
    diff keeps the parser honest about which parts of the format it
    actually depends on.
    """
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:body>' + body + "</w:body></w:document>")
    path.write_bytes(buf.getvalue())


def _w_p(text: str, *, style: str = "", bullet: bool = False) -> str:
    pr = (f'<w:pStyle w:val="{style}"/>' if style else "") + (
        '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'
        if bullet else "")
    return (f"<w:p>{f'<w:pPr>{pr}</w:pPr>' if pr else ''}"
            f"<w:r><w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p>")


@pytest.mark.parametrize("suffix", [".md", ".txt", ".docx"])
def test_the_same_facts_arrive_whatever_file_the_document_is_in(
        graph, tmp_path, suffix, capsys):
    """A file format is packaging. Changing it must not change the facts.

    This is the whole path a person actually walks — a file on disk,
    `extract`, a model, `import` — run once per format the command
    accepts, against one document that says the same three things in
    each. A regression here is the failure that matters most and is
    hardest to see: the Word file still reads, still produces a prompt,
    and quietly carries less of the document than the Markdown did.
    """
    from trikedb.cli import main

    lines = ["Notes on the reorganisation",
             "Sato joined Acme in 2026.",
             "Acme is based in Osaka.",
             "Tanaka has left for Globex."]

    document = tmp_path / ("doc" + suffix)
    if suffix == ".docx":
        _as_docx(document, _w_p(lines[0], style="Heading1")
                 + "".join(_w_p(line, bullet=True) for line in lines[1:]))
    else:
        document.write_text("# " + lines[0] + "\n\n"
                            + "\n".join("- " + line for line in lines[1:])
                            + "\n", encoding="utf-8")

    prompt_file = tmp_path / "prompt.txt"
    assert main(["extract", str(graph.path), str(document),
                 "-o", str(prompt_file)]) == 0
    prompt = prompt_file.read_text(encoding="utf-8")

    # Every sentence of the document reached the model, in every format.
    for line in lines:
        assert line in prompt
    assert "`WORKS_AT`" in prompt and "- Acme  (company)" in prompt

    table = tmp_path / "rows.md"
    table.write_text(
        "| s | p | o | at | prov |\n|---|---|---|---|---|\n"
        "| Sato | WORKS_AT | Acme | 2026-01-01 | Sato joined Acme |\n"
        "| Acme | BASED_IN | Osaka | | Acme is based in Osaka |\n",
        encoding="utf-8")
    assert main(["import", str(graph.path), str(table)]) == 0

    on_disk = TrikeDB(graph.path)
    assert ("Sato", "WORKS_AT", "Acme") in on_disk
    assert ("Acme", "BASED_IN", "Osaka") in on_disk


def test_a_table_in_a_word_file_reaches_the_model_as_a_table(graph, tmp_path,
                                                             capsys):
    """The reason converting a .docx is worth more than reading its text.

    A roster is a table, and a table is one fact per row. Flattened into
    a run of words — "Name Team Tanaka Data Platform Sato Data Platform"
    — the rows lose their edges and the column headings stop labelling
    anything, which is the point at which a model starts guessing who
    belongs to what. Arriving as Markdown, the shape the document had is
    the shape the model reads.
    """
    from trikedb.cli import main

    def cell(text):
        return f"<w:tc>{_w_p(text)}</w:tc>"

    def row(*cells):
        return "<w:tr>" + "".join(cell(c) for c in cells) + "</w:tr>"

    document = tmp_path / "roster.docx"
    _as_docx(document,
             _w_p("Roster", style="Heading1")
             + "<w:tbl>" + row("Name", "Employer")
             + row("Tanaka", "Acme") + row("Sato", "Globex") + "</w:tbl>")

    assert main(["extract", str(graph.path), str(document)]) == 0
    prompt = capsys.readouterr().out

    assert "| Name | Employer |" in prompt
    assert "| Tanaka | Acme |" in prompt
    assert "| Sato | Globex |" in prompt


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


# --------------------------------------------- the document is not a fact


#: The shapes a document actually arrives in. This is the accuracy claim:
#: head detection is only worth having if it survives the formats people
#: are already holding — a Word export that starts at Heading2, an
#: Obsidian note whose title is in front matter, a mail forwarded with its
#: headers, a letter that opens by addressing the reader. Each row that
#: fails names the format it fails on, which is the only way this stays
#: honest as formats get added.
DOCUMENT_SHAPES = [
    ("markdown h1",           "# 取り込み設計\n\n本文。", "取り込み設計"),
    ("starts at h2",          "## 仕様概要\n\n### 前提\n\n本文。", "仕様概要"),
    ("setext ===",            "設計メモ\n========\n\n本文。", "設計メモ"),
    ("setext ---",            "Design Note\n-----------\n\nbody.", "Design Note"),
    ("yaml front matter",     "---\ntitle: 取り込み設計\ntags: [a]\n---\n\n本文。",
                              "取り込み設計"),
    ("front matter quoted",   '---\ntitle: "Q3 Review"\n---\n\nbody.', "Q3 Review"),
    ("toml front matter",     '+++\ntitle = "Runbook"\n+++\n\nbody.', "Runbook"),
    ("front matter no title", "---\ntags: [a]\n---\n\n# 実物\n\n本文。", "実物"),
    ("mail headers",          "From: a@b.c\nTo: all@b.c\nSubject: 【連絡】席替え\n\n各位",
                              "【連絡】席替え"),
    ("mail, subject first",   "Subject: Weekly report\nFrom: a@b.c\n\nbody",
                              "Weekly report"),
    ("plain txt title line",  "四半期レビュー\n\n本文が続く。", "四半期レビュー"),
    ("numbered heading",      "# 1. はじめに\n\n本文。", "1. はじめに"),
    ("closed atx",            "# Q3 Review #\n\nbody", "Q3 Review"),
    ("fence before heading",  "```yaml\nkey: v\n```\n\n# 実物\n\n本文。", "実物"),
    ("heading only in fence", "```\n# not a heading\n```\n\n本文が長々と続きます。", ""),
    ("leading blank lines",   "\n\n\n# 通知\n\n本文。", "通知"),
    ("crlf",                  "# 通知\r\n\r\n本文。\r\n", "通知"),
    ("byte order mark",       "\ufeff# 通知\n\n本文。", "通知"),
    ("chinese",               "# 数据平台部成立通知\n\n正文。", "数据平台部成立通知"),
    ("english plain",         "Acme Announces Division\n\nTOKYO — today.",
                              "Acme Announces Division"),
    ("title with colon",      "# 設計メモ: 取り込み\n\n本文。", "設計メモ: 取り込み"),
    ("company letterhead",    "株式会社アクメ\n\n# 人事異動のお知らせ\n\n本文。",
                              "人事異動のお知らせ"),
    ("date line then title",  "2026-09-20\n\n# 障害報告\n\n本文。", "障害報告"),
    ("hr then heading",       "---\n\n# 実物\n\n本文。", "実物"),
    # A head it cannot honestly name is an empty answer, not a guess: the
    # caller still has the file's own name, and a wrong head would be
    # written into the prompt as a thing not to extract.
    ("empty",                 "", ""),
    ("whitespace only",       "   \n\n  \n", ""),
    ("one long paragraph",    "本書は取り込み方針について述べるものである。\n\n次。", ""),
    ("bullet first",          "- 田中 亮\n- 佐藤 美咲\n", ""),
    ("table first",           "| a | b |\n|---|---|\n| 1 | 2 |\n", ""),
    ("blockquote first",      "> 引用です\n\n本文。", ""),
    ("over-long first line",  "あ" * 120 + "\n\n本文。", ""),
    ("ends mid-sentence",     "これは文です。\n\n本文。", ""),
    ("salutation opener",     "各位\n\nお疲れ様です。異動の連絡です。", ""),
    ("greeting opener",       "お疲れ様です\n\n総務です。連絡します。", ""),
]


@pytest.mark.parametrize("shape,text,expected",
                         DOCUMENT_SHAPES,
                         ids=[s[0] for s in DOCUMENT_SHAPES])
def test_the_head_of_a_document_is_the_line_that_names_it(shape, text, expected):
    assert importers_mod.document_title(text) == expected


@pytest.mark.parametrize("title,expected", [
    ("人事異動のお知らせ", "人事異動のお知らせ.yaml"),
    ("Acme Announces A Division", "acme-announces-a-division.yaml"),
    ("設計メモ: 取り込み/パイプライン", "設計メモ-取り込み-パイプライン.yaml"),
    # A dash between words is a separator like a space is, and leaving it in
    # produces `q3-—-torikomi.yaml`: two hyphens around a character that is
    # doing nothing but separating.
    ("Q3 — 取り込み見直し", "q3-取り込み見直し.yaml"),
    ("", ""),
    ("...", ""),
])
def test_a_head_becomes_a_filename_without_being_romanised(title, expected):
    # Stripping the Japanese would produce a name nobody can find a file by,
    # and every filesystem trikedb runs on has taken these bytes for years.
    assert importers_mod.graph_filename(title) == expected


def test_a_filename_from_a_head_cannot_redirect_the_write():
    for hostile in ("../../etc/passwd", "a/b", "C:\\x", "x\x00y"):
        name = importers_mod.graph_filename(hostile)
        assert "/" not in name and "\\" not in name and "\x00" not in name
        assert not name.startswith(".")


def test_the_prompt_names_the_head_so_the_model_can_refuse_it():
    prompt = extract_mod.build_prompt("# 人事異動のお知らせ\n\n高橋 舞 が異動する。",
                                  ontology={"BELONGS_TO": "所属"})
    assert "「人事異動のお知らせ」" in prompt
    # The rule has to reach the other two places a document leaks in.
    assert "as a subject or as an object" in prompt
    assert "改訂履歴" in prompt


def test_a_document_with_no_head_still_gets_the_rule():
    prompt = extract_mod.build_prompt("高橋 舞 が異動する。", ontology={"X": "y"})
    assert "no head of its own" in prompt
    assert "{{" not in prompt


def test_an_explicit_title_overrides_what_the_text_looks_like():
    prompt = extract_mod.build_prompt("# 見出し\n\n本文", title="", ontology={"X": "y"})
    assert "no head of its own" in prompt
    assert "「見出し」" not in prompt
