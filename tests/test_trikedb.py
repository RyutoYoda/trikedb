import pytest
import yaml

from trikedb import OntologyError, TrikeDB


@pytest.fixture
def db(tmp_path):
    db = TrikeDB(tmp_path / "graph.yaml")
    db.add("salesflow-crm", "PROVIDES", "crm-sync-job")
    db.add("crm-sync-job", "INGESTS_TO", "RAW_CRM_CONTACTS", schedule="hourly")
    db.add("adastra-ads", "PROVIDES", "ads-spend-collector")
    db.add("ads-spend-collector", "INGESTS_TO", "RAW_AD_SPEND_DAILY")
    db.add("LEGACY_DUMP", "MIGRATED_TO", "RAW_CRM_CONTACTS", deprecated=True)
    return db


def test_pattern_match_wildcards(db):
    assert len(list(db.triples())) == 5
    assert len(list(db.triples(p="PROVIDES"))) == 2
    assert [t.o for t in db.triples(s="crm-sync-job")] == ["RAW_CRM_CONTACTS"]


def test_glob_match(db):
    assert len(list(db.triples(o="RAW_*"))) == 3


def test_attr_filter(db):
    assert [t.s for t in db.triples(deprecated=True)] == ["LEGACY_DUMP"]
    assert [t.o for t in db.triples(schedule="hourly")] == ["RAW_CRM_CONTACTS"]


def test_upsert_merges_attrs(db):
    before = len(db)
    db.add("crm-sync-job", "INGESTS_TO", "RAW_CRM_CONTACTS", via="https://api.example")
    assert len(db) == before
    t = next(db.triples(s="crm-sync-job"))
    assert t.attrs == {"schedule": "hourly", "via": "https://api.example"}


def test_query_joins_on_shared_variables(db):
    rows = db.query(["?vendor PROVIDES ?job", "?job INGESTS_TO ?table"])
    assert {r["vendor"] for r in rows} == {"salesflow-crm", "adastra-ads"}
    assert all(set(r) == {"vendor", "job", "table"} for r in rows)


def test_query_with_constant_and_string_pattern(db):
    rows = db.query(["?job INGESTS_TO RAW_CRM_CONTACTS"])
    assert rows == [{"job": "crm-sync-job"}]


def test_query_quoted_object():
    db = TrikeDB()
    db.add("T", "AFFECTED_BY", "2025-04 API v3: units changed")
    rows = db.query(['?t AFFECTED_BY "2025-04 API v3: units changed"'])
    assert rows == [{"t": "T"}]


def test_save_load_roundtrip(db, tmp_path):
    path = db.save()
    again = TrikeDB(path)
    assert len(again) == len(db)
    assert [t.to_dict() for t in again] == [t.to_dict() for t in db]


def test_saved_yaml_is_flat_and_readable(db):
    doc = yaml.safe_load(db.save().read_text())
    assert {"s", "p", "o", "schedule"} <= set(doc["triples"][1])


def test_ontology_rejects_unknown_predicate(tmp_path):
    db = TrikeDB(tmp_path / "g.yaml", ontology={"PROVIDES": "vendor -> job"})
    db.add("a", "PROVIDES", "b")
    with pytest.raises(OntologyError):
        db.add("a", "TOTALLY_MADE_UP", "b")


def test_ontology_loaded_from_file(tmp_path):
    path = tmp_path / "g.yaml"
    path.write_text(
        "ontology:\n  predicates:\n    ONLY: allowed one\n"
        "triples:\n  - {s: a, p: ONLY, o: b}\n"
    )
    db = TrikeDB(path)
    assert db.ontology == {"ONLY": "allowed one"}
    with pytest.raises(OntologyError):
        db.add("x", "OTHER", "y")


def test_remove(db):
    assert db.remove(p="PROVIDES") == 2
    assert len(db) == 3


def test_helpers(db):
    assert db.subjects(p="PROVIDES") == ["salesflow-crm", "adastra-ads"]
    assert db.objects(s="salesflow-crm") == ["crm-sync-job"]
    assert "MIGRATED_TO" in db.predicates()
    assert ("salesflow-crm", "PROVIDES", "crm-sync-job") in db


def test_jsonld_export(db):
    doc = db.to_jsonld()
    ids = {n["@id"] for n in doc["@graph"]}
    assert "salesflow-crm" in ids
    assert doc["@context"]["PROVIDES"]["@type"] == "@id"


def test_html_export(db, tmp_path):
    out = tmp_path / "graph.html"
    html = db.to_html(out)
    assert out.exists()
    assert "vis-network" in html
    assert "RAW_CRM_CONTACTS" in html
    assert '"deprecated": true' in html  # drives dashed edges in the JS
    assert "oxigraph" in html  # in-browser SPARQL console
    assert "trikedb knowledge graph" in html  # default title
    assert "urn:trikedb:LEGACY_DUMP" in html  # embedded N-Triples for the engine
    assert "search-count" in html  # Cmd+F-style match cycling
    assert "overflow-x: auto" in html  # legend slides instead of clipping when crowded
    assert "function setTypeHidden" in html  # select-all/clear reuse per-label toggle
    assert 'id="legend-ctl"' in html  # all/none controls for the node-type checkboxes


def test_html_event_predicates_detected(tmp_path):
    db = TrikeDB()
    db.add("T", "AFFECTED_BY", "2025-04 API v3: units changed")
    db.add("a", "DEPENDS_ON", "b")
    html = db.to_html()
    assert '"AFFECTED_BY"' in html.split("EVENT_PREDICATES = ")[1].split(";")[0]


def test_examples_load_and_query():
    from pathlib import Path

    examples = Path(__file__).resolve().parent.parent / "examples"
    acme = TrikeDB(examples / "acme_pipeline.yaml")
    assert len(acme.ontology) == 5
    rows = acme.query(["?v PROVIDES ?j", "?j INGESTS_TO ?t"])
    assert {"v": "salesflow-crm", "j": "crm-sync-job", "t": "RAW_CRM_CONTACTS"} in rows

    eco = TrikeDB(examples / "python_ecosystem.yaml")
    assert eco.ontology == {}
    assert "numpy" in eco.objects(p="DEPENDS_ON")


# ---------------------------------------------------------------- sparql

def test_sparql_select_join(db):
    rows = db.sparql(
        "SELECT ?vendor ?table WHERE { ?vendor t:PROVIDES ?job . ?job t:INGESTS_TO ?table }"
    )
    assert {"vendor": "salesflow-crm", "table": "RAW_CRM_CONTACTS"} in rows
    assert {"vendor": "adastra-ads", "table": "RAW_AD_SPEND_DAILY"} in rows


def test_sparql_filter(db):
    rows = db.sparql(
        'SELECT ?t WHERE { ?j t:INGESTS_TO ?t . FILTER(STRSTARTS(STR(?t), "urn:trikedb:RAW_CRM")) }'
    )
    assert rows == [{"t": "RAW_CRM_CONTACTS"}]


def test_sparql_ask(db):
    assert db.sparql("ASK { ?x t:MIGRATED_TO ?y }") is True
    assert db.sparql("ASK { ?x t:NOPE ?y }") is False


def test_sparql_freetext_objects_are_literals():
    db = TrikeDB()
    db.add("T", "AFFECTED_BY", "2025-04 API v3: units changed")
    g = db.to_rdflib()
    from rdflib import Literal

    assert list(g)[0][2] == Literal("2025-04 API v3: units changed")
    rows = db.sparql("SELECT ?event WHERE { t:T t:AFFECTED_BY ?event }")
    assert rows == [{"event": "2025-04 API v3: units changed"}]


# ------------------------------------------------------- sparql update

def test_sparql_insert_data(db):
    delta = db.sparql("INSERT DATA { t:figly t:PROVIDES t:figly-export-job }")
    assert delta == 1
    assert ("figly", "PROVIDES", "figly-export-job") in db


def test_sparql_delete_where(db):
    delta = db.sparql("DELETE WHERE { ?s t:PROVIDES ?o }")
    assert delta == -2
    assert list(db.triples(p="PROVIDES")) == []


def test_update_preserves_attrs_of_surviving_triples(db):
    db.sparql("INSERT DATA { t:x t:PROVIDES t:y }")
    t = next(db.triples(s="crm-sync-job"))
    assert t.attrs == {"schedule": "hourly"}
    assert next(db.triples(s="LEGACY_DUMP")).attrs == {"deprecated": True}


def test_update_respects_ontology(tmp_path):
    db = TrikeDB(tmp_path / "g.yaml", ontology={"PROVIDES": ""})
    db.add("a", "PROVIDES", "b")
    with pytest.raises(OntologyError):
        db.sparql("INSERT DATA { t:a t:MADE_UP t:b }")


def test_autosave_roundtrip(tmp_path):
    path = tmp_path / "g.yaml"
    db = TrikeDB(path, autosave=True)
    db.add("a", "P", "b")
    db.sparql("INSERT DATA { t:c t:P t:d }")
    assert len(TrikeDB(path)) == 2
    db.remove(s="a")
    assert len(TrikeDB(path)) == 1


# --------------------------------------------------------------- imports

def test_import_csv(tmp_path):
    src = tmp_path / "extra.csv"
    src.write_text(
        "s,p,o,schedule,deprecated\n"
        "figly,PROVIDES,figly-job,,\n"
        "figly-job,INGESTS_TO,RAW_FIGLY,daily,\n"
        "OLD_FIGLY,MIGRATED_TO,RAW_FIGLY,,true\n"
    )
    db = TrikeDB()
    assert db.import_file(src) == 3
    t = next(db.triples(s="figly-job"))
    assert t.attrs == {"schedule": "daily"}
    assert next(db.triples(s="OLD_FIGLY")).attrs == {"deprecated": True}


def test_import_csv_requires_spo_header(tmp_path):
    src = tmp_path / "bad.csv"
    src.write_text("from,to\na,b\n")
    with pytest.raises(ValueError):
        TrikeDB().import_file(src)


def test_import_markdown_tables_only_spo(tmp_path):
    src = tmp_path / "doc.md"
    src.write_text(
        "# Design doc\n\nprose here\n\n"
        "| s | p | o | schedule |\n|---|---|---|---|\n"
        "| v | PROVIDES | j |  |\n"
        "| j | INGESTS_TO | T | streaming |\n\n"
        "more prose\n\n"
        "| subject | predicate | object |\n|---|---|---|\n"
        "| T | AFFECTED_BY | 2025-09-01 field dropped |\n\n"
        "| step | owner |\n|------|-------|\n| a | alice |\n"
    )
    db = TrikeDB()
    assert db.import_file(src) == 3
    assert ("j", "INGESTS_TO", "T") in db
    assert next(db.triples(s="j")).attrs == {"schedule": "streaming"}
    assert not list(db.triples(s="a"))  # non-triple table ignored


def test_import_respects_ontology(tmp_path):
    src = tmp_path / "extra.csv"
    src.write_text("s,p,o\na,NOT_ALLOWED,b\n")
    db = TrikeDB(ontology={"PROVIDES": ""})
    with pytest.raises(OntologyError):
        db.import_file(src)


def test_import_yaml_merge(tmp_path):
    other = tmp_path / "other.yaml"
    TrikeDB(other).add("x", "P", "y") and None
    db_other = TrikeDB(other)
    db_other.add("x", "P", "y")
    db_other.save()
    db = TrikeDB()
    db.add("a", "P", "b")
    assert db.import_file(other) == 1
    assert len(db) == 2


def test_import_example_files():
    from pathlib import Path

    examples = Path(__file__).resolve().parent.parent / "examples"
    # autosaveがデフォルトなので、実サンプルを汚さないよう明示的にopt-out
    db = TrikeDB(examples / "acme_pipeline.yaml", autosave=False)
    added = db.import_file(examples / "acme_new_vendors.csv")
    added += db.import_file(examples / "acme_design_doc.md")
    assert added == 8  # 5 from the CSV, 3 from the two s/p/o tables in the doc
    assert ("clickpath-pa", "PROVIDES", "clickpath-webhook") in db
    assert next(db.triples(s="figly-export-job")).attrs["via"].startswith("https://")


# ----------------------------------------------------------- node props

def test_node_props_roundtrip(tmp_path):
    path = tmp_path / "g.yaml"
    db = TrikeDB(path)
    db.add("v", "PROVIDES", "j")
    db.set_node("v", type="saas", url="https://v.example")
    db.set_node("v", plan="enterprise")  # merges
    db.save()
    again = TrikeDB(path)
    assert again.node("v") == {"type": "saas", "url": "https://v.example", "plan": "enterprise"}
    assert again.node("j") == {}


def test_node_props_queryable_via_sparql():
    db = TrikeDB()
    db.add("v", "PROVIDES", "j")
    db.set_node("v", type="saas")
    db.set_node("j", type="job")
    rows = db.sparql('SELECT ?x WHERE { ?x t:type "saas" }')
    assert rows == [{"x": "v"}]


def test_update_does_not_absorb_node_props():
    db = TrikeDB()
    db.add("a", "P", "b")
    db.set_node("a", type="saas")
    db.sparql("INSERT DATA { t:c t:P t:d }")
    assert len(db) == 2  # node-prop statements didn't become triples
    assert db.node("a") == {"type": "saas"}


def test_meta_only_node_appears_in_nodes():
    db = TrikeDB()
    db.set_node("lonely", type="table")
    assert "lonely" in db.nodes()


def test_html_includes_node_meta_and_flow():
    db = TrikeDB()
    db.add("v", "PROVIDES", "j")
    db.set_node("v", type="saas", url="https://v.example")
    html = db.to_html()
    assert '"type": "saas"' in html
    assert "hierarchical" in html  # flow layout
    assert "NODE_TYPES" in html


# --------------------------------------------------------------- mcp

def test_mcp_server_tools_and_roundtrip(tmp_path):
    pytest.importorskip("mcp")
    import asyncio
    import json as _json

    from trikedb.mcp_server import build_server

    path = tmp_path / "g.yaml"
    TrikeDB(path, ontology={"PROVIDES": "vendor -> job"}).save()
    server = build_server(path)

    names = {t.name for t in asyncio.run(server.list_tools())}
    assert {"sparql", "match", "add_triple", "remove_triples",
            "set_node", "get_node", "ontology", "stats", "import_source"} <= names

    async def call(name, args):
        content = await server.call_tool(name, args)
        blocks = content[0] if isinstance(content, tuple) else content
        return _json.loads(blocks[0].text)

    added = asyncio.run(call("add_triple", {"s": "v", "p": "PROVIDES", "o": "j",
                                            "attrs": {"note": "from docs"}}))
    assert added == {"s": "v", "p": "PROVIDES", "o": "j", "note": "from docs"}
    assert len(TrikeDB(path)) == 1  # autosaved

    node = asyncio.run(call("get_node", {"name": "v"}))
    assert node["outgoing"][0]["o"] == "j"

    onto = asyncio.run(call("ontology", {}))
    assert onto == {"PROVIDES": "vendor -> job"}


def test_mcp_rejects_ontology_violation_and_full_wipe(tmp_path):
    pytest.importorskip("mcp")
    import asyncio

    from trikedb.mcp_server import build_server

    path = tmp_path / "g.yaml"
    TrikeDB(path, ontology={"PROVIDES": ""}).save()
    server = build_server(path)

    async def raw_call(name, args):
        return await server.call_tool(name, args)

    with pytest.raises(Exception):
        asyncio.run(raw_call("add_triple", {"s": "a", "p": "MADE_UP", "o": "b"}))
    with pytest.raises(Exception):
        asyncio.run(raw_call("remove_triples", {}))


def test_html_explicit_event_predicates():
    db = TrikeDB()
    db.add("T", "AFFECTED_BY", "2025-04 API change happened")
    db.add("mdb", "LOADS_FROM", "mysql (asteria 17)")  # free text but NOT an event
    auto = db.to_html()
    assert '"LOADS_FROM"' in auto.split("EVENT_PREDICATES = ")[1].split(";")[0]  # heuristic picks it up
    explicit = db.to_html(event_predicates=["AFFECTED_BY"])
    block = explicit.split("EVENT_PREDICATES = ")[1].split(";")[0]
    assert '"AFFECTED_BY"' in block and '"LOADS_FROM"' not in block


def test_cli_node_set_and_show(tmp_path, capsys):
    import json as _json

    from trikedb.cli import main

    g = str(tmp_path / "g.yaml")
    assert main(["add", g, "svc-etl-01", "USES_ROLE", "ROLE_ADMIN"]) == 0
    capsys.readouterr()  # discard the add command's output
    assert main(["node", g, "svc-etl-01", "-a", "label=etl-bot", "-a", "type=bot", "-a", "pii=false"]) == 0
    shown = _json.loads(capsys.readouterr().out)
    assert shown["properties"]["label"] == "etl-bot"
    again = TrikeDB(g)
    assert again.node("svc-etl-01") == {"label": "etl-bot", "type": "bot", "pii": False}
    assert main(["node", g, "svc-etl-01"]) == 0  # show-only does not error


def test_cli_ontology_set(tmp_path):
    from trikedb.cli import main

    g = str(tmp_path / "g.yaml")
    assert main(["add", g, "a", "P", "b"]) == 0
    assert main(["ontology", g, "--set", "P=first predicate", "--set", "Q=second"]) == 0
    again = TrikeDB(g)
    assert again.ontology == {"P": "first predicate", "Q": "second"}
    import pytest as _pytest

    with _pytest.raises(OntologyError):
        again.add("x", "NOT_DECLARED", "y")


# ---------------------------------------------------------------- remote

def test_remote_memory_roundtrip():
    pytest.importorskip("fsspec")
    url = "memory://kg/graph.yaml"
    db = TrikeDB(url, ontology={"P": "test predicate"})
    db.add("a", "P", "b", note="remote!")
    db.set_node("a", type="thing")
    db.save()

    again = TrikeDB(url)
    assert ("a", "P", "b") in again
    assert again.node("a") == {"type": "thing"}
    assert again.ontology == {"P": "test predicate"}
    assert isinstance(again.path, str)  # remote URLs stay strings


def test_remote_autosave():
    pytest.importorskip("fsspec")
    url = "memory://kg/auto.yaml"
    db = TrikeDB(url, autosave=True)
    db.add("x", "P", "y")
    assert ("x", "P", "y") in TrikeDB(url)


def test_remote_missing_graph_starts_empty():
    pytest.importorskip("fsspec")
    db = TrikeDB("memory://kg/does-not-exist.yaml")
    assert len(db) == 0


# ------------------------------------------------------------ shacl / owl

def test_uri_terms_pass_through_to_rdflib():
    from rdflib import URIRef

    db = TrikeDB()
    db.add("INHERITS", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
           "http://www.w3.org/2002/07/owl#TransitiveProperty")
    terms = list(db.to_rdflib())[0]
    assert terms[1] == URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
    assert terms[2] == URIRef("http://www.w3.org/2002/07/owl#TransitiveProperty")


def test_owl_transitive_inference():
    pytest.importorskip("owlrl")
    db = TrikeDB(ontology={"INHERITS": "role -> role"})
    db.declare("INHERITS", "transitive")  # URI predicate is ontology-exempt
    db.add("admin", "INHERITS", "editor")
    db.add("editor", "INHERITS", "viewer")
    new = db.infer()
    assert ("admin", "INHERITS", "viewer") in new
    db.infer(apply=True)
    t = next(db.triples(s="admin", o="viewer"))
    assert t.attrs == {"inferred": True}


def test_owl_symmetric_inference():
    pytest.importorskip("owlrl")
    db = TrikeDB()
    db.declare("MARRIED_TO", "symmetric")
    db.add("alice", "MARRIED_TO", "bob")
    assert ("bob", "MARRIED_TO", "alice") in db.infer()


# --------------------------------------------------------------- rdfs
# infer() surfaces RDFS entailments (classification + hierarchy), not just OWL
# property characteristics. Regression: the closure derived these all along, but
# the result filter discarded every rdf:type / rdfs: triple as "vocabulary noise".

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
RDFS_SUBCLASS = "http://www.w3.org/2000/01/rdf-schema#subClassOf"


def test_rdfs_subclass_type_propagation():
    pytest.importorskip("owlrl")
    db = TrikeDB()
    db.declare("Cat", "subclass_of:Animal")
    db.add("felix", RDF_TYPE, "Cat")
    assert ("felix", RDF_TYPE, "Animal") in db.infer()


def test_rdfs_domain_and_range_typing():
    pytest.importorskip("owlrl")
    db = TrikeDB()
    db.declare("authored", "domain:Person")
    db.declare("authored", "range:Book")
    db.add("alice", "authored", "book1")
    new = db.infer()
    assert ("alice", RDF_TYPE, "Person") in new
    assert ("book1", RDF_TYPE, "Book") in new


def test_rdfs_subproperty_of():
    pytest.importorskip("owlrl")
    db = TrikeDB()
    db.declare("bornIn", "subproperty_of:locatedIn")
    db.add("alice", "bornIn", "paris")
    assert ("alice", "locatedIn", "paris") in db.infer()


def test_rdfs_subclass_transitive_and_apply():
    pytest.importorskip("owlrl")
    db = TrikeDB()
    db.declare("Cat", "subclass_of:Mammal")
    db.declare("Mammal", "subclass_of:Animal")
    new = db.infer(apply=True)
    assert ("Cat", RDFS_SUBCLASS, "Animal") in new
    t = next(db.triples(s="Cat", p=RDFS_SUBCLASS, o="Animal"))
    assert t.attrs == {"inferred": True}
    assert db.infer(apply=True) == []  # idempotent


def test_infer_suppresses_owl_bookkeeping_noise():
    """RDFS/OWL closure emits x rdf:type owl:Thing, x subClassOf rdfs:Resource,
    bnodes, etc. None of that vocabulary noise should surface — only facts whose
    subject and object are the user's own resources."""
    pytest.importorskip("owlrl")
    db = TrikeDB()
    db.declare("Cat", "subclass_of:Animal")
    db.add("felix", RDF_TYPE, "Cat")
    new = db.infer()
    assert new == [("felix", RDF_TYPE, "Animal")]
    for s, p, o in new:
        assert not s.startswith(("http://", "urn:"))  # subject is a plain name
        assert "owl#" not in o and "rdf-schema#" not in o  # no vocabulary objects


SHAPES = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix t:  <urn:trikedb:> .
t:BotShape a sh:NodeShape ;
  sh:targetSubjectsOf t:USES_ROLE ;
  sh:property [ sh:path t:type ; sh:hasValue "bot" ; sh:minCount 1 ] .
"""


def test_shacl_validate(tmp_path):
    pytest.importorskip("pyshacl")
    db = TrikeDB()
    db.add("svc-etl-02", "USES_ROLE", "ROLE_EDITOR")
    db.set_node("svc-etl-02", type="bot")
    conforms, _ = db.validate(SHAPES)
    assert conforms is True

    db.add("rogue-user", "USES_ROLE", "ROLE_ADMIN")  # no type: bot -> violation
    conforms, report = db.validate(SHAPES)
    assert conforms is False
    assert "rogue-user" in report


def test_shacl_validate_from_file(tmp_path):
    pytest.importorskip("pyshacl")
    shapes_file = tmp_path / "shapes.ttl"
    shapes_file.write_text(SHAPES)
    db = TrikeDB()
    db.add("svc-etl-02", "USES_ROLE", "ROLE_EDITOR")
    db.set_node("svc-etl-02", type="bot")
    conforms, _ = db.validate(str(shapes_file))
    assert conforms is True


# ------------------------------------------------------------- workspace

def _make_workspace(tmp_path):
    fin = TrikeDB(tmp_path / "finance.yaml", ontology={"OWNS_BUDGET": ""})
    fin.add("tanaka", "OWNS_BUDGET", "project-atlas")
    fin.set_node("tanaka", type="person")
    fin.save()
    plat = TrikeDB(tmp_path / "platform.yaml", ontology={"USES": ""})
    plat.add("project-atlas", "USES", "ACME_DWH")
    plat.save()
    ws = tmp_path / "workspace.yaml"
    ws.write_text("graphs:\n  finance: finance.yaml\n  platform: platform.yaml\n")
    return ws


def test_workspace_union(tmp_path):
    db = TrikeDB(_make_workspace(tmp_path))
    assert db.workspace == {"finance": "finance.yaml", "platform": "platform.yaml"}
    assert len(db) == 2
    assert {t.attrs["graph"] for t in db} == {"finance", "platform"}
    assert set(db.ontology) == {"OWNS_BUDGET", "USES"}
    assert db.node("tanaka") == {"type": "person"}
    # 自動ジョイン: 財務→基盤を跨ぐパスがSPARQLで引ける
    rows = db.sparql("SELECT ?env WHERE { t:tanaka t:OWNS_BUDGET ?pj . ?pj t:USES ?env }")
    assert rows == [{"env": "ACME_DWH"}]


def test_workspace_is_read_only(tmp_path):
    db = TrikeDB(_make_workspace(tmp_path))
    for fn in (lambda: db.add("a", "OWNS_BUDGET", "b"),
               lambda: db.remove(s="tanaka"),
               lambda: db.set_node("x", type="y"),
               lambda: db.save(),
               lambda: db.sparql("INSERT DATA { t:a t:OWNS_BUDGET t:b }")):
        with pytest.raises(ValueError, match="read-only workspace"):
            fn()


def test_workspace_html_has_graph_filter_and_theme(tmp_path):
    db = TrikeDB(_make_workspace(tmp_path))
    html = db.to_html()
    block = html.split("GRAPHS = ")[1].split(";")[0]
    assert '"finance"' in block and '"platform"' in block
    assert "btn-theme" in html and "body.light" in html  # light mode present


# ----------------------------------------------------------------- serve

def test_serve_ui_and_rest(tmp_path):
    pytest.importorskip("starlette")
    from starlette.testclient import TestClient

    from trikedb.serve import build_app

    g = tmp_path / "g.yaml"
    db = TrikeDB(g)
    db.add("a", "P", "b")
    db.save()

    client = TestClient(build_app(str(g), with_mcp=False))
    page = client.get("/")
    assert page.status_code == 200 and "vis-network" in page.text
    r = client.post("/sparql", json={"query": "SELECT ?o WHERE { t:a t:P ?o }"})
    assert r.json() == {"rows": [{"o": "b"}]}
    w = client.post("/sparql", json={"query": "INSERT DATA { t:c t:P t:d }"})
    assert w.json()["delta"] == 1
    assert ("c", "P", "d") in TrikeDB(g)  # RESTの書き込みが永続化される


def test_serve_token_gate(tmp_path):
    pytest.importorskip("starlette")
    from starlette.testclient import TestClient

    from trikedb.serve import build_app

    g = tmp_path / "g.yaml"
    TrikeDB(g, autosave=True).add("a", "P", "b")
    client = TestClient(build_app(str(g), token="sekrit", with_mcp=False))
    assert client.get("/").status_code == 401
    ok = client.get("/", headers={"Authorization": "Bearer sekrit"})
    assert ok.status_code == 200


# ------------------------------------------------------------ check/audit

def test_content_hash_and_check(tmp_path, capsys):
    from trikedb.cli import main

    g = str(tmp_path / "g.yaml")
    h = str(tmp_path / "g.html")
    db = TrikeDB(g)
    db.add("a", "P", "b")
    db.save()
    db.to_html(h)
    assert main(["check", g, "--html", h]) == 0
    # グラフを変更 → HTMLが古い扱いになる
    db.add("c", "P", "d")
    db.save()
    assert main(["check", g, "--html", h]) == 1
    db.to_html(h)  # 再生成で復帰
    assert main(["check", g, "--html", h]) == 0


def test_audit_findings(tmp_path):
    ws_dir = tmp_path
    g1 = TrikeDB(ws_dir / "a.yaml"); g1.add("x", "P", "y"); g1.save()
    g2 = TrikeDB(ws_dir / "b.yaml"); g2.add("x", "P", "y"); g2.add("Tokyo", "P", "tokyo"); g2.save()
    (ws_dir / "ws.yaml").write_text("graphs:\n  a: a.yaml\n  b: b.yaml\n")
    db = TrikeDB(ws_dir / "ws.yaml")
    kinds = {f["kind"] for f in db.audit()}
    assert "duplicate-triple" in kinds      # 同一(s,p,o)が2グラフに
    assert "name-collision" in kinds        # Tokyo vs tokyo

    solo = TrikeDB(ws_dir / "c.yaml", ontology={"USED": "", "UNUSED": ""})
    solo.add("s", "USED", "o")
    solo.add("T", "USED", "2025-01 first event happened here today")
    solo.add("T", "USED", "2025-01 first event happened here again")
    solo.set_node("lonely", type="x")
    f = solo.audit()
    kinds = {x["kind"] for x in f}
    assert {"unused-predicate", "orphan-node", "similar-facts"} <= kinds
    assert all(x["severity"] == "warning" for x in f)  # errorなし


def test_html_fulltext_search_and_sparql_bridge():
    db = TrikeDB()
    db.add("svc-etl-01", "USES_ROLE", "ROLE_ADMIN", schedule="hourly")
    db.set_node("svc-etl-01", label="etl-bot", owner="data-platform")
    html = db.to_html()
    assert "searchIndex" in html      # 全文インデックス
    assert "btn-tosparql" in html     # SPARQL橋渡しボタン
    # プロパティ・属性値がクライアント側データに含まれている(=検索可能)
    assert "data-platform" in html and "hourly" in html


def test_autosave_is_default(tmp_path):
    # 書いたものは即ディスクにある — CLIと同じ感覚がライブラリのデフォルト
    path = tmp_path / "auto.yaml"
    TrikeDB(path).add("a", "REL", "b")
    assert len(list(TrikeDB(path).triples())) == 1
    TrikeDB(path).set_node("a", type="thing")
    assert TrikeDB(path).node("a") == {"type": "thing"}
    # opt-outは明示で
    db = TrikeDB(path, autosave=False)
    db.add("c", "REL", "d")
    assert len(list(TrikeDB(path).triples())) == 1  # まだ書かれていない
    db.save()
    assert len(list(TrikeDB(path).triples())) == 2


def test_edge_attrs_queryable_via_sparql(tmp_path):
    # 運用の金脈(note/prov)がSPARQLで引ける — RDF reification
    db = TrikeDB(tmp_path / "g.yaml")
    db.add("ACME_DWH", "AFFECTED_BY", "2026-07 task suspended",
           note="再開すると二重取り込みになる", prov="MEMORY.md")
    db.add("a", "REL", "b")  # attrsなし → reificationされない
    rows = db.sparql(
        "SELECT ?s ?o ?note WHERE { ?st rdf:subject ?s ; rdf:object ?o ; t:note ?note }"
    )
    assert rows == [{"s": "ACME_DWH", "o": "2026-07 task suspended",
                     "note": "再開すると二重取り込みになる"}]
    # provで逆引き
    assert db.sparql(
        'ASK { ?st t:prov "MEMORY.md" ; rdf:predicate t:AFFECTED_BY }') is True
    # updateのsync-backはreificationを取り込まない
    db.update("INSERT DATA { t:c t:REL t:d }")
    spos = {t.spo() for t in db.triples()}
    assert ("ACME_DWH", "AFFECTED_BY", "2026-07 task suspended") in spos
    assert len(spos) == 3  # stmtノードがYAMLに漏れていない
    # 属性は生き残っている
    t = next(db.triples(p="AFFECTED_BY"))
    assert t.attrs["note"] == "再開すると二重取り込みになる"


def test_semantic_sentences_shape(tmp_path):
    from trikedb import semantic

    db = TrikeDB(tmp_path / "g.yaml")
    db.add("svc-etl-01", "USES_ROLE", "ROLE_ADMIN", note="keypair認証")
    db.set_node("svc-etl-01", type="bot")
    items = semantic.sentences(db)
    texts = [t for t, _ in items]
    assert any("keypair認証" in t for t in texts)      # エッジ属性が検索対象
    assert any(t.startswith("svc-etl-01 type: bot") for t in texts)  # ノードprops
    kinds = {payload["kind"] for _, payload in items}
    assert kinds == {"triple", "node"}


def test_semantic_search_ranks_by_meaning(tmp_path):
    pytest.importorskip("model2vec")
    from trikedb import semantic

    db = TrikeDB(tmp_path / "g.yaml")
    db.add("ACME_DWH", "AFFECTED_BY", "2025-11 MFA必須化、キーペア認証へ移行")
    db.add("mdb", "LOADS_FROM", "mysql")
    try:
        rows = db.search("認証まわりの注意点", k=2)
    except Exception as exc:  # モデル未キャッシュ+オフライン
        pytest.skip(f"model unavailable: {exc}")
    assert rows[0]["o"].startswith("2025-11 MFA")
    assert rows[0]["score"] > rows[1]["score"]


def test_add_upsert_autosaves(tmp_path):
    # add() で既存 spo の attrs を更新したとき autosave が走ること
    path = tmp_path / "g.yaml"
    db = TrikeDB(path)
    db.add("svc-etl-01", "USES_ROLE", "ROLE_ADMIN", status="active")
    db.add("svc-etl-01", "USES_ROLE", "ROLE_ADMIN", status="retired")  # upsert
    reloaded = TrikeDB(path)
    t = next(reloaded.triples(s="svc-etl-01", p="USES_ROLE"))
    assert t.attrs["status"] == "retired"  # ディスクに反映されていること


def test_sparql_update_preserves_attrs(tmp_path):
    # SPARQL update で DELETE+INSERT した spo の attrs が消えないこと
    path = tmp_path / "g.yaml"
    db = TrikeDB(path)
    db.add("ACME_DWH", "AFFECTED_BY", "ev-2025", note="important", prov="doc.md")
    db.update("DELETE { t:ACME_DWH t:AFFECTED_BY t:ev-2025 } "
              "INSERT { t:ACME_DWH t:AFFECTED_BY t:ev-2025 } WHERE {}")
    t = next(db.triples(s="ACME_DWH", p="AFFECTED_BY"))
    assert t.attrs.get("note") == "important"
    assert t.attrs.get("prov") == "doc.md"


def test_search_k_clamps_to_positive(tmp_path):
    # k=0 や k=-1 でもクラッシュせず最低1件返すこと
    from trikedb import semantic
    db = TrikeDB(tmp_path / "g.yaml")
    db.add("a", "REL", "b")
    items = semantic.sentences(db)
    # sentences があれば k<=0 でも 1 件返る
    from unittest.mock import MagicMock, patch
    import numpy as np
    fake_model = MagicMock()
    fake_model.encode = lambda texts: [[0.1, 0.2]] * len(texts)
    with patch("trikedb.semantic._load_model", return_value=fake_model):
        rows = semantic.search(db, "test", k=0)
        assert len(rows) >= 1
        rows = semantic.search(db, "test", k=-5)
        assert len(rows) >= 1


def test_readme_links_are_absolute_for_pypi():
    """README relative links (docs/, examples/, benchmarks/) render broken on
    PyPI, which serves the README standalone. Every non-anchor link must be an
    absolute URL. Guards against shipping dead doc links in a release."""
    import re
    from pathlib import Path

    readme = Path(__file__).resolve().parent.parent / "README.md"
    text = readme.read_text(encoding="utf-8")
    md_targets = re.findall(r"\]\(([^)]+)\)", text)
    html_targets = re.findall(r'(?:src|href)="([^"]+)"', text)
    relative = [
        t for t in md_targets + html_targets
        if not t.startswith(("http://", "https://", "#", "mailto:"))
    ]
    assert not relative, f"README has relative links that break on PyPI: {relative}"
