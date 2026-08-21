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


def test_networkx_projection(db):
    """The property-graph view: node props + edge label/attrs preserved, and
    real graph algorithms run over it — the same YAML that speaks SPARQL."""
    nx = pytest.importorskip("networkx")
    db.set_node("RAW_CRM_CONTACTS", type="table", pii=True)
    g = db.to_networkx()
    assert isinstance(g, nx.MultiDiGraph)
    # node properties carried across
    assert g.nodes["RAW_CRM_CONTACTS"] == {"type": "table", "pii": True}
    # edge carries predicate as label + its attributes, keyed by predicate
    edge = g.get_edge_data("crm-sync-job", "RAW_CRM_CONTACTS")["INGESTS_TO"]
    assert edge["label"] == "INGESTS_TO" and edge["schedule"] == "hourly"
    # a real property-graph traversal works over the projection
    assert nx.shortest_path(g, "salesflow-crm", "RAW_CRM_CONTACTS") == [
        "salesflow-crm", "crm-sync-job", "RAW_CRM_CONTACTS"]
    # multigraph=False collapses to a plain DiGraph
    assert isinstance(db.to_networkx(multigraph=False), nx.DiGraph)


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


# ------------------------------------------------------------------ oauth

ISSUER = "https://tenant.example.com/"
RESOURCE = "https://kg.example.com/mcp"


@pytest.fixture
def idp(monkeypatch):
    """A fake IdP: a real RSA keypair, minus the network round-trip.

    Discovery and JWKS fetching are the only parts stubbed out — the tokens
    are genuinely signed and genuinely verified.
    """
    pytest.importorskip("jwt")
    pytest.importorskip("mcp")
    import time

    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    from trikedb import oauth

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class _Keys:
        def get_signing_key_from_jwt(self, token):
            return type("K", (), {"key": key.public_key()})()

    async def _signing_keys(self):
        self._issuer_claim = ISSUER
        return _Keys()

    monkeypatch.setattr(oauth.JWKSVerifier, "_signing_keys", _signing_keys)

    def mint(**overrides):
        claims = {
            "iss": ISSUER,
            "aud": RESOURCE,
            "sub": "auth0|ryuto",
            "azp": "claude-ai-connector",
            "scope": "kg:read kg:write",
            "exp": int(time.time()) + 300,
        }
        claims.update(overrides)
        return jwt.encode(claims, key, algorithm="RS256")

    return mint


def test_oauth_verifier_accepts_and_rejects(idp):
    import asyncio
    import time

    from trikedb.oauth import JWKSVerifier

    v = JWKSVerifier(ISSUER, RESOURCE)
    verify = lambda t: asyncio.run(v.verify_token(t))  # noqa: E731

    good = verify(idp())
    assert good is not None
    assert set(good.scopes) == {"kg:read", "kg:write"}
    assert good.subject == "auth0|ryuto" and good.client_id == "claude-ai-connector"

    # A token minted for some other service must not open the graph (RFC 8707).
    assert verify(idp(aud="https://someone-elses-api.example.com")) is None
    assert verify(idp(exp=int(time.time()) - 1)) is None
    assert verify(idp(iss="https://evil.example.com/")) is None
    assert verify("not-even-a-jwt") is None


def test_oauth_verifier_reads_auth0_rbac_permissions(idp):
    import asyncio

    from trikedb.oauth import JWKSVerifier

    v = JWKSVerifier(ISSUER, RESOURCE)
    token = idp(scope="openid", permissions=["kg:read"])
    assert set(asyncio.run(v.verify_token(token)).scopes) == {"openid", "kg:read"}


def test_serve_oauth_protects_ui_and_rest(tmp_path, idp):
    pytest.importorskip("starlette")
    from starlette.testclient import TestClient

    from trikedb.serve import build_app

    g = tmp_path / "g.yaml"
    TrikeDB(g, autosave=True).add("a", "P", "b")
    app = build_app(
        str(g), with_mcp=False,
        oauth_issuer=ISSUER, public_url="https://kg.example.com",
    )
    client = TestClient(app)

    anon = client.get("/")
    assert anon.status_code == 401
    # The 401 must tell the client where to discover the auth server (RFC 9728).
    assert "/.well-known/oauth-protected-resource/mcp" in anon.headers["www-authenticate"]

    auth = {"Authorization": f"Bearer {idp()}"}
    assert client.get("/", headers=auth).status_code == 200
    rows = client.post("/sparql", json={"query": "SELECT ?o WHERE { t:a t:P ?o }"}, headers=auth)
    assert rows.json() == {"rows": [{"o": "b"}]}
    assert client.post("/sparql", json={"query": "SELECT ?o WHERE {?s ?p ?o}"}).status_code == 401


def test_serve_oauth_publishes_resource_metadata(tmp_path, idp):
    """Discovery has to work *before* the client has a token, or it can never get one."""
    pytest.importorskip("starlette")
    from starlette.testclient import TestClient

    from trikedb.serve import build_app

    g = tmp_path / "g.yaml"
    TrikeDB(g, autosave=True).add("a", "P", "b")
    app = build_app(
        str(g), oauth_issuer=ISSUER, public_url="https://kg.example.com",
        required_scopes=["kg:read"],
    )
    with TestClient(app) as client:
        meta = client.get("/.well-known/oauth-protected-resource/mcp")
        assert meta.status_code == 200
        body = meta.json()
        assert body["resource"] == RESOURCE
        assert body["authorization_servers"] == [ISSUER]
        assert body["scopes_supported"] == ["kg:read"]
        # ...and /mcp itself still challenges anonymous callers.
        assert client.post("/mcp", json={}).status_code == 401


def test_serve_oauth_enforces_scopes_on_every_door(tmp_path, idp):
    """One --required-scope has to mean the same thing on /, /sparql and /mcp."""
    pytest.importorskip("starlette")
    from starlette.testclient import TestClient

    from trikedb.serve import build_app

    g = tmp_path / "g.yaml"
    TrikeDB(g, autosave=True).add("a", "P", "b")
    client = TestClient(build_app(
        str(g), with_mcp=False, oauth_issuer=ISSUER,
        public_url="https://kg.example.com", required_scopes=["kg:admin"],
    ))

    thin = {"Authorization": f"Bearer {idp(scope='kg:read')}"}
    short = client.get("/", headers=thin)
    assert short.status_code == 403
    assert 'error="insufficient_scope"' in short.headers["www-authenticate"]
    assert 'scope="kg:admin"' in short.headers["www-authenticate"]

    full = {"Authorization": f"Bearer {idp(scope='kg:read kg:admin')}"}
    assert client.get("/", headers=full).status_code == 200
    assert client.post("/sparql", json={"query": "ASK { t:a t:P t:b }"}, headers=full).json() == {"ask": True}


def test_serve_trusts_its_own_public_hostname(tmp_path, idp):
    """Behind a proxy or tunnel the Host header is the public name, not localhost.

    The SDK's DNS-rebinding guard trusts only localhost by default, so without
    declaring the public host every authenticated request dies with 421 — after
    the token has already been verified, which makes it look like an auth bug.
    """
    pytest.importorskip("starlette")
    from starlette.testclient import TestClient

    from trikedb.mcp_server import _transport_security
    from trikedb.serve import build_app

    s = _transport_security("https://kg.example.com")
    assert "kg.example.com" in s.allowed_hosts      # Host: kg.example.com (443)
    assert "kg.example.com:*" in s.allowed_hosts    # Host: kg.example.com:8443
    assert "localhost:*" in s.allowed_hosts         # local dev still works
    assert _transport_security(None) is None        # stdio keeps SDK defaults

    g = tmp_path / "g.yaml"
    TrikeDB(g, autosave=True).add("a", "P", "b")
    with TestClient(build_app(
        str(g), oauth_issuer=ISSUER, public_url="https://kg.example.com",
    )) as client:
        r = client.post(
            "/mcp",
            headers={
                "Authorization": f"Bearer {idp()}",
                "Host": "kg.example.com",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                             "clientInfo": {"name": "t", "version": "0"}}},
        )
        assert r.status_code == 200 and "trikedb" in r.text


def test_serve_stateless_serves_requests_with_no_session(tmp_path):
    """Some clients never echo Mcp-Session-Id back, and replicas don't share sessions.

    A session lives in one process's memory, so the stateful transport answers
    `400 Bad Request: Missing session ID` to any follow-up that arrives without
    it — which is also what a second replica behind a load balancer would do.
    `--stateless` drops the session so each request stands alone.
    """
    pytest.importorskip("starlette")
    from starlette.testclient import TestClient

    from trikedb.serve import build_app

    g = tmp_path / "g.yaml"
    TrikeDB(g, autosave=True).add("a", "P", "b")
    headers = {"Accept": "application/json, text/event-stream",
               "Content-Type": "application/json"}
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}

    public = "http://testserver"  # what TestClient puts in the Host header

    with TestClient(build_app(str(g), public_url=public)) as client:  # stateful
        r = client.post("/mcp", headers=headers, json=call)
        assert r.status_code == 400 and "session ID" in r.text

    with TestClient(build_app(str(g), public_url=public, stateless=True)) as client:
        r = client.post("/mcp", headers=headers, json=call)
        assert r.status_code == 200
        assert "sparql" in r.text and "add_triple" in r.text


def test_conditional_write_refuses_to_clobber(tmp_path, monkeypatch):
    """A save must not overwrite bytes it never read.

    Only backends that can express the condition get the guarantee, so this
    drives the storage layer with a stub filesystem that behaves like S3:
    ``pipe_file(..., IfMatch=)`` fails when the stored token has moved on.
    """
    from trikedb import storage

    stored = {"etag": "v1"}

    class FakeS3:
        protocol = ("s3", "s3a")

        def info(self, key):
            if stored.get("etag") is None:
                raise FileNotFoundError(key)
            return {"ETag": f'"{stored["etag"]}"'}

        def pipe_file(self, key, data, mode=None, IfMatch=None):
            if mode == "create" and stored.get("etag") is not None:
                raise FileExistsError(key)
            if IfMatch is not None and IfMatch != stored["etag"]:
                raise RuntimeError("An error occurred (PreconditionFailed)")
            stored["etag"] = "v2"

    monkeypatch.setattr(storage, "_conditional_fs", lambda path: (FakeS3(), "k"))

    assert storage.version("s3://b/k") == "v1"
    with pytest.raises(storage.ConcurrentWriteError):
        storage.write_text("s3://b/k", "x", expect="v0")   # someone else saved
    storage.write_text("s3://b/k", "x", expect="v1")       # ours is still current
    assert stored["etag"] == "v2"

    stored["etag"] = None                                   # nothing stored yet
    storage.write_text("s3://b/k", "x", expect=None)        # create wins the race
    stored["etag"] = "someone-else"
    with pytest.raises(storage.ConcurrentWriteError):
        storage.write_text("s3://b/k", "x", expect=None)    # ...or loses it


def test_reload_picks_up_the_other_writer(tmp_path):
    """reload() is the documented way out of a conflict, so it has to work."""
    g = tmp_path / "g.yaml"
    a = TrikeDB(g, autosave=True)
    a.add("a", "P", "b")

    TrikeDB(g, autosave=True).add("c", "P", "d")   # another writer
    assert len(a) == 1                              # not visible yet
    a.reload()
    assert {t.s for t in a.triples()} == {"a", "c"}


def test_missing_extra_error_keeps_the_real_cause(monkeypatch, tmp_path):
    """A broken install must not be reported as a missing one.

    "pip install 'trikedb[mcp]'" is the right hint when the package is absent
    and actively misleading when it is present but failing to import for some
    other reason — the package metadata is gone, a shared library won't load.
    Keeping the original error as __cause__ costs nothing and is often the
    only thing that names the real problem.
    """
    import sys

    from trikedb.mcp_server import build_server

    # None in sys.modules makes the import fail the way a broken install does.
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", None)
    with pytest.raises(ImportError) as caught:
        build_server(tmp_path / "g.yaml")

    assert "trikedb[mcp]" in str(caught.value)   # the hint survives
    assert caught.value.__cause__ is not None    # ...and so does the reason
    # Non-latin-1 characters in the message are dropped by some runtimes'
    # error reporting (AWS Lambda's init handler among them), which loses the
    # whole traceback. Keep exception text plain.
    assert str(caught.value).isascii()


def test_serve_oauth_requires_public_url(tmp_path):
    pytest.importorskip("starlette")
    from trikedb.serve import build_app

    with pytest.raises(ValueError, match="public-url"):
        build_app(str(tmp_path / "g.yaml"), oauth_issuer=ISSUER, with_mcp=False)


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


def _hybrid_db(tmp_path):
    db = TrikeDB(tmp_path / "g.yaml")
    db.add("crm-sync-job", "INGESTS_TO", "RAW_CRM_CONTACTS", note="顧客データを毎時同期")
    db.add("billing-etl", "INGESTS_TO", "RAW_INVOICES", note="請求データのETL")
    db.set_node("RAW_CRM_CONTACTS", type="table", pii=True, desc="customer contacts")
    db.set_node("RAW_INVOICES", type="table", pii=False, desc="invoice line items")
    return db


def test_find_hybrid_recall_then_filter(tmp_path):
    pytest.importorskip("model2vec")
    db = _hybrid_db(tmp_path)
    try:
        # recall casts a wide net; the where filter enforces hard constraints
        rows = db.find("where is the customer CRM data?",
                       where={"type": "table", "pii": True}, k=8)
    except Exception as exc:  # model uncached + offline
        pytest.skip(f"model unavailable: {exc}")
    names = [r["node"] for r in rows]
    assert "RAW_CRM_CONTACTS" in names        # semantically recalled + passes filter
    assert "RAW_INVOICES" not in names        # a table, but pii=False → dropped
    hit = next(r for r in rows if r["node"] == "RAW_CRM_CONTACTS")
    assert hit["props"]["pii"] is True
    assert isinstance(hit["facts"], list)     # ready-to-use structured payload


def test_find_where_callable_and_none(tmp_path):
    pytest.importorskip("model2vec")
    db = _hybrid_db(tmp_path)
    try:
        cb = db.find("customer data", where=lambda name, p: p.get("pii") is True, k=8)
        every = db.find("customer data", where=None, k=8)
    except Exception as exc:
        pytest.skip(f"model unavailable: {exc}")
    assert [r["node"] for r in cb] == ["RAW_CRM_CONTACTS"]
    assert len(every) >= len(cb)              # no filter keeps at least as many


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


# ------------------------------------------------- warehouse-backed storage

class FakeWarehouse:
    """A DB-API-shaped stand-in that understands the statements storage_sql
    issues, so the compare-and-swap can be tested without a warehouse.

    The row counts are the point: a real warehouse serialises UPDATE/MERGE on
    a table and reports how many rows it touched, and that count is the whole
    conflict-detection mechanism. Getting it wrong here would make the tests
    agree with a bug.
    """

    def __init__(self):
        self.rows = {}        # graph name -> [doc, version]
        self.created = []     # tables sql-init made
        self.views = []       # projection views sql-init made
        self.opens = 0
        self.fail_once_with = None

    # -- DB-API surface used by storage_sql
    def cursor(self):
        return FakeCursor(self)

    def is_closed(self):
        return False

    def close(self):
        pass


class FakeCursor:
    def __init__(self, warehouse):
        self._wh = warehouse
        self.rowcount = -1
        self.description = None
        self._rows = []

    def execute(self, sql, params=None):
        if self._wh.fail_once_with is not None:
            exc, self._wh.fail_once_with = self._wh.fail_once_with, None
            raise exc
        sql = " ".join(sql.split())
        if sql.startswith("CREATE TABLE"):
            self._wh.created.append(sql)
            self.rowcount = 0
        elif sql.startswith("CREATE OR REPLACE VIEW"):
            self._wh.views.append(sql.split()[4])
            self.rowcount = 0
        elif sql.startswith("SELECT"):
            row = self._wh.rows.get(params[0])
            self._rows = [(row[0], row[1])] if row else []
            self.description = [("doc",), ("version",)]
        elif sql.startswith("UPDATE"):
            doc, token, name, expect = params
            current = self._wh.rows.get(name)
            hit = current is not None and current[1] == expect
            if hit:
                self._wh.rows[name] = [doc, token]
            self.rowcount = 1 if hit else 0
        elif sql.startswith("MERGE"):
            name, doc, token = params
            present = name in self._wh.rows
            replaces = "WHEN MATCHED THEN UPDATE" in sql
            if not present or replaces:
                self._wh.rows[name] = [doc, token]
                self.rowcount = 1
            else:
                self.rowcount = 0
        else:
            raise AssertionError(f"unexpected SQL: {sql}")

    def fetchall(self):
        return self._rows

    def close(self):
        pass


@pytest.fixture
def warehouse(monkeypatch):
    """A snowflake:// scheme wired to FakeWarehouse instead of Snowflake."""
    import dataclasses

    from trikedb import storage_sql

    fake = FakeWarehouse()

    def connect(config):
        fake.opens += 1
        return fake

    monkeypatch.setitem(
        storage_sql.DIALECTS,
        "snowflake",
        dataclasses.replace(
            storage_sql.SNOWFLAKE,
            connect=connect,
            config_from_env=lambda: {"account": "test"},
        ),
    )
    monkeypatch.setattr(storage_sql, "_CONNECTIONS", {})
    return fake


TABLE = "MYDB.PUBLIC.TRIKE_GRAPHS"
URL = f"snowflake://{TABLE}/sales/crm"


def test_sql_url_parsing():
    """The table name is interpolated into SQL, so it has to be validated."""
    from trikedb import storage_sql

    for url, table, name in (
        ("snowflake://T/g", "T", "g"),
        ("snowflake://S.T/g", "S.T", "g"),
        (URL, "MYDB.PUBLIC.TRIKE_GRAPHS", "sales/crm"),
    ):
        dialect, got_table, got_name = storage_sql._split(url)
        assert (got_table, got_name) == (table, name)
        assert dialect.name == "snowflake"

    with pytest.raises(ValueError, match="no graph name"):
        storage_sql._split("snowflake://T")
    with pytest.raises(ValueError, match="DATABASE.SCHEMA.TABLE"):
        storage_sql._split("snowflake://a.b.c.d/g")
    # An identifier cannot be parameterised, so injection has to die at the door
    for hostile in ("snowflake://T; DROP TABLE X/g", "snowflake://T--/g",
                    "snowflake://\"T\"/g", "snowflake:///g"):
        with pytest.raises(ValueError):
            storage_sql._split(hostile)


def test_sql_backend_roundtrip(warehouse):
    """A warehouse row is a graph: the layers above must not notice."""
    db = TrikeDB(URL)
    assert len(db) == 0                      # no row yet == empty graph
    db.add("salesflow-crm", "PROVIDES", "crm-sync-job")

    stored = warehouse.rows["sales/crm"][0]  # autosave wrote it through
    assert "PROVIDES" in stored
    assert yaml.safe_load(stored)["triples"]  # it really is the YAML document

    again = TrikeDB(URL)
    assert [(t.s, t.p, t.o) for t in again.triples()] == [
        ("salesflow-crm", "PROVIDES", "crm-sync-job")
    ]
    # SPARQL and friends sit above storage, so they come along for free
    assert again.sparql(
        "SELECT ?o WHERE { t:salesflow-crm t:PROVIDES ?o }"
    ) == [{"o": "crm-sync-job"}]


def test_sql_conditional_write_refuses_to_clobber(warehouse):
    """The row count is the conflict: no error-message matching needed."""
    from trikedb.storage import ConcurrentWriteError

    a = TrikeDB(URL, autosave=False)
    a.add("a", "P", "b")
    a.save()

    b = TrikeDB(URL, autosave=False)       # reads a's version
    a.add("c", "P", "d")
    a.save()                               # a moves the version on

    b.add("e", "P", "f")
    with pytest.raises(ConcurrentWriteError):
        b.save()                           # b's version is stale
    landed = yaml.safe_load(warehouse.rows["sales/crm"][0])["triples"]
    assert [t["s"] for t in landed] == ["a", "c"]       # nothing was written

    b.reload()                             # the documented way out
    b.add("e", "P", "f")
    b.save()
    assert {t.s for t in TrikeDB(URL)} == {"a", "c", "e"}


def test_sql_create_is_a_race_too(warehouse):
    """Two writers finding no row must not both think they created it."""
    from trikedb.storage import ConcurrentWriteError

    a = TrikeDB(URL, autosave=False)
    b = TrikeDB(URL, autosave=False)       # both saw an empty graph
    a.add("a", "P", "b")
    b.add("x", "P", "y")
    a.save()
    with pytest.raises(ConcurrentWriteError):
        b.save()
    assert {t.s for t in TrikeDB(URL)} == {"a"}


def test_sql_missing_table_says_how_to_fix(warehouse):
    """"Object does not exist" is unactionable unless it names the command."""
    from trikedb import storage_sql

    warehouse.fail_once_with = RuntimeError(
        "002003 (42S02): SQL compilation error: Object "
        "'MYDB.PUBLIC.TRIKE_GRAPHS' does not exist or not authorized."
    )
    with pytest.raises(storage_sql.TableMissing, match="sql-init"):
        TrikeDB(URL)


def test_sql_reconnects_when_the_session_went_away(warehouse):
    """Warehouse sessions expire on their own schedule; a save must survive."""
    TrikeDB(URL, autosave=False).save()          # opens and caches a connection
    assert warehouse.opens == 1

    warehouse.fail_once_with = RuntimeError("Connection is closed")
    db = TrikeDB(URL, autosave=False)            # hits the dead session, retries
    db.add("a", "P", "b")
    db.save()
    assert warehouse.opens == 2
    assert warehouse.rows["sales/crm"]


def test_sql_init_creates_the_table(warehouse, capsys):
    from trikedb.cli import main

    assert main(["sql-init", URL, "--print"]) == 0
    printed = capsys.readouterr().out
    assert "CREATE TABLE IF NOT EXISTS MYDB.PUBLIC.TRIKE_GRAPHS" in printed
    assert not warehouse.created                 # --print must not touch it

    assert main(["sql-init", URL]) == 0
    assert warehouse.created
    assert warehouse.views == [
        "MYDB.PUBLIC.KG_NODE", "MYDB.PUBLIC.KG_EDGE",
        "MYDB.PUBLIC.KG_PREDICATE", "MYDB.PUBLIC.KG_TRIPLE",
    ]


def test_snowflake_missing_connector_error_keeps_the_real_cause(monkeypatch):
    """Same contract as the other extras: hint without hiding the reason."""
    import sys

    from trikedb import storage_sql

    monkeypatch.setitem(sys.modules, "snowflake.connector", None)
    with pytest.raises(ImportError) as caught:
        storage_sql._snowflake_connect({"account": "x"})
    assert "trikedb[snowflake]" in str(caught.value)
    assert caught.value.__cause__ is not None
    assert str(caught.value).isascii()


def test_a_file_that_isnt_a_graph_fails_clearly(tmp_path):
    """Valid YAML that isn't a mapping used to surface as an AttributeError.

    ``'str' object has no attribute 'get'`` names whichever key happened to be
    read first and sends the reader hunting in the wrong place. It matters more
    once the graph lives somewhere other people can write to — a shared
    warehouse row, a bucket — than it did for a file you own outright.
    """
    for content in ("just a string\n", "- a\n- b\n"):
        g = tmp_path / "not-a-graph.yaml"
        g.write_text(content, encoding="utf-8")
        with pytest.raises(ValueError, match="does not hold a graph"):
            TrikeDB(g)

    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    assert len(TrikeDB(empty)) == 0        # empty is still a legitimate graph


def test_html_output_location_is_independent_of_where_the_graph_lives():
    """The workbench is a rendering, not part of the graph.

    Deriving the page name by swapping the graph's extension breaks on any
    URL: `snowflake://DB.PUBLIC.TRIKE_GRAPHS/sales/crm` became
    `snowflake://DB.PUBLIC.html`, and even the s3 case produced a path that
    could only ever fail to open.
    """
    from trikedb.cli import _default_html_out

    assert _default_html_out("graph.yaml") == "graph.html"
    assert _default_html_out("kg/graph.yaml") == "kg/graph.html"
    assert _default_html_out("mygraph") == "mygraph.html"
    # remote graphs render to the working directory, named after the graph
    assert _default_html_out("s3://bucket/kg/graph.yaml") == "graph.html"
    assert _default_html_out(
        "snowflake://DB.PUBLIC.TRIKE_GRAPHS/sales/crm") == "crm.html"
    assert _default_html_out("snowflake://T/g") == "g.html"


def test_html_can_be_published_to_object_storage(tmp_path):
    """`-o s3://...` used to raise FileNotFoundError on a local path that was
    never going to exist. The page goes through the storage layer now."""
    pytest.importorskip("fsspec")
    db = TrikeDB()
    db.add("a", "P", "b")

    url = "memory://kg/workbench.html"
    db.to_html(url)
    from trikedb import storage

    assert "vis-network" in storage.read_text(url)

    # ...and `check --html` can verify a published page, not just a local file
    from trikedb.cli import main

    g = tmp_path / "g.yaml"
    db.save(g)
    db.to_html(url)
    assert main(["check", str(g), "--html", url]) == 0
    db.add("c", "P", "d")
    db.save(g)
    assert main(["check", str(g), "--html", url]) == 1   # now stale


def test_html_refuses_to_overwrite_a_graph_row():
    """A warehouse row holds a graph; writing a page into it would destroy it."""
    db = TrikeDB()
    db.add("a", "P", "b")
    with pytest.raises(ValueError, match="holds a graph, not a page"):
        db.to_html("snowflake://DB.PUBLIC.TRIKE_GRAPHS/sales/crm")


def test_json_is_valid_yaml_so_the_loader_needs_no_change():
    """The whole warehouse-JSON switch rests on this being true.

    A warehouse row holds JSON so SQL can crack it open; the loader still
    calls yaml.safe_load. If any document trikedb writes round-tripped
    differently through the two parsers, graphs would quietly change meaning
    on the way to the warehouse and back.
    """
    import json

    db = TrikeDB(ontology={"P": "a predicate", "Q": ""})
    db.add("a", "P", "b", schedule="hourly", deprecated=True, count=3)
    db.add("x", "Q", "2025-04 API v3: units changed")       # free text, colon
    db.add("日本語", "P", "値", note="改行なし")              # non-ascii
    db.set_node("a", type="job", pii=False, level=2)
    doc = {
        "ontology": {"predicates": dict(db.ontology)},
        "nodes": {k: dict(v) for k, v in db.nodes_meta.items()},
        "triples": [t.to_dict() for t in db],
    }
    text = json.dumps(doc, ensure_ascii=False, indent=2)
    assert yaml.safe_load(text) == json.loads(text) == doc


def test_warehouse_graphs_are_written_as_json(warehouse):
    """Files get YAML for humans; a warehouse row gets JSON for SQL."""
    from trikedb import storage

    assert storage.serialization("g.yaml") == "yaml"
    assert storage.serialization("s3://b/g.yaml") == "yaml"
    assert storage.serialization(URL) == "json"

    db = TrikeDB(URL, autosave=False)
    db.add("salesflow", "PROVIDES", "crm-sync-job", schedule="hourly")
    db.set_node("crm-sync-job", type="job", owner="data-platform")
    db.save()

    import json

    stored = warehouse.rows["sales/crm"][0]
    doc = json.loads(stored)                       # really is JSON, not YAML
    assert doc["triples"][0]["schedule"] == "hourly"
    assert doc["nodes"]["crm-sync-job"]["owner"] == "data-platform"

    # ...and it reads back through the unchanged loader
    assert [(t.s, t.p, t.o) for t in TrikeDB(URL)] == [
        ("salesflow", "PROVIDES", "crm-sync-job")
    ]


def test_sql_init_creates_the_projection_views(warehouse, capsys):
    """The views are what make the graph readable from SQL at all, so they
    are part of setting the table up rather than a step to remember."""
    from trikedb.cli import main

    assert main(["sql-init", URL, "--print"]) == 0
    printed = capsys.readouterr().out
    for view in ("KG_NODE", "KG_EDGE", "KG_PREDICATE", "KG_TRIPLE"):
        assert f"CREATE OR REPLACE VIEW MYDB.PUBLIC.{view}" in printed
    # KG_NODE / KG_EDGE carry the conventional property-graph column names
    for column in ("NODE_ID", "NODE_TYPE", "PROPS", "SRC_ID", "DST_ID", "EDGE_TYPE"):
        assert column in printed
    assert "PARSE_JSON" in printed          # the doc is JSON now, so SQL can read it

    assert main(["sql-init", URL, "--no-views"]) == 0
    assert "CREATE OR REPLACE VIEW" not in capsys.readouterr().out


def test_write_retry_survives_heavy_contention_without_long_sleeps(tmp_path, monkeypatch):
    """Eight attempts with uncapped doubling was measurably too tight.

    Ten concurrent writers against one warehouse row used all eight and
    occasionally wanted a ninth — a warehouse serialises DML per table, so
    writers to *different* graphs queue too, and collisions are the norm
    rather than the exception. Raising the count alone does not fix it:
    uncapped, attempt 11 would sleep for minutes. Cap the delay and the
    extra attempts are affordable.
    """
    pytest.importorskip("mcp")
    from trikedb import mcp_server
    from trikedb.storage import ConcurrentWriteError

    slept = []
    monkeypatch.setattr(mcp_server.time if hasattr(mcp_server, "time") else __import__("time"),
                        "sleep", lambda s: slept.append(s))

    real_write = mcp_server.TrikeDB.save
    losses = {"left": 9}          # more than the old budget of 8 allowed

    def flaky_save(self, path=None):
        if losses["left"] > 0:
            losses["left"] -= 1
            raise ConcurrentWriteError("someone else got there first")
        return real_write(self, path)

    monkeypatch.setattr(mcp_server.TrikeDB, "save", flaky_save)

    import asyncio

    server = mcp_server.build_server(tmp_path / "g.yaml")
    asyncio.run(server.call_tool("add_triple", {"s": "a", "p": "P", "o": "b"}))

    assert losses["left"] == 0                    # it kept going past 8
    assert slept, "backoff never ran"
    assert max(slept) <= 1.0, f"a single retry slept {max(slept)}s"
    assert sum(slept) < 10, f"total backoff {sum(slept):.1f}s is too long to wait"


def test_read_only_refuses_every_mutation(tmp_path):
    """An app that only reads should not be holding a write path.

    The motivating case is a warehouse-backed graph served to a dashboard:
    writes belong to whatever owns the graph (a reviewed file in git, say),
    and a bug or an agent cannot spend a capability it was never given.
    """
    g = tmp_path / "g.yaml"
    TrikeDB(g).add("a", "P", "b")

    ro = TrikeDB(g, read_only=True)
    assert len(ro) == 1                      # reading is the whole point
    assert ro.sparql("ASK { ?s t:P ?o }") is True

    for mutate in (
        lambda: ro.add("x", "P", "y"),
        lambda: ro.remove(p="P"),
        lambda: ro.set_node("a", type="job"),
        lambda: ro.save(),
        lambda: ro.update("INSERT DATA { t:x t:P t:y }"),
    ):
        with pytest.raises(ValueError, match="read_only=True"):
            mutate()

    assert len(TrikeDB(g)) == 1               # nothing landed


def test_read_only_survives_reload(tmp_path):
    """reload() used to reset the flag, which would hand back a writable graph.

    It runs on every conflict recovery, so losing read-only there would mean
    the guarantee quietly expires exactly when the graph is contended.
    """
    g = tmp_path / "g.yaml"
    TrikeDB(g).add("a", "P", "b")

    ro = TrikeDB(g, read_only=True)
    TrikeDB(g).add("c", "P", "d")             # someone else writes
    ro.reload()
    assert len(ro) == 2                       # it picked their change up
    assert ro.read_only is True
    with pytest.raises(ValueError, match="read_only=True"):
        ro.add("x", "P", "y")


def test_read_only_error_names_the_right_cause(tmp_path):
    """A workspace union and an explicit read_only need different advice."""
    member = tmp_path / "m.yaml"
    TrikeDB(member).add("a", "P", "b")
    ws = tmp_path / "ws.yaml"
    ws.write_text(f"graphs:\n  m: {member.name}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="workspace union"):
        TrikeDB(ws).add("x", "P", "y")
    with pytest.raises(ValueError, match="read_only=True"):
        TrikeDB(member, read_only=True).add("x", "P", "y")


def test_read_only_works_on_a_warehouse_graph(warehouse):
    """The case this was asked for: read the row, never write it."""
    seed = TrikeDB(URL, autosave=False)               # seeded by someone else
    seed.add("a", "P", "b")
    seed.save()

    ro = TrikeDB(URL, read_only=True)
    assert [t.s for t in ro] == ["a"]
    with pytest.raises(ValueError, match="read_only=True"):
        ro.add("agent", "P", "wrote")
    with pytest.raises(ValueError, match="read_only=True"):
        ro.save()


def test_a_new_dialect_is_one_literal():
    """Everything warehouse-specific has to live in the dialect.

    Projection SQL used to sit in a registry beside the dialects, keyed by
    name. Two parallel places to update is how the second dialect gets
    expensive, and the SQL is exactly what differs between warehouses —
    `TRY_PARSE_JSON`/`FLATTEN` here, `jsonb_to_recordset` on Postgres,
    `json_each` on SQLite.
    """
    import dataclasses

    from trikedb import storage_sql

    assert "views" in storage_sql.SNOWFLAKE.__dataclass_fields__
    assert set(storage_sql.SNOWFLAKE.views) == {
        "KG_NODE", "KG_EDGE", "KG_PREDICATE", "KG_TRIPLE"}
    assert not hasattr(storage_sql, "VIEWS")     # no registry to forget

    # A backend may store graphs without projecting them: views default empty
    bare = dataclasses.replace(storage_sql.SNOWFLAKE, name="bare", views={})
    store = storage_sql.SqlGraphStore(bare, "T", "g")
    assert store._dialect.views == {}


def test_a_vendored_subset_without_the_sql_backend_still_works(tmp_path, monkeypatch):
    """trikedb gets copied file-by-file into hosts that cannot pip install.

    Streamlit in Snowflake is the case in hand: db.py + storage.py +
    __init__.py, no warehouse driver available. Importing storage_sql from
    inside storage.exists() turned "open a local YAML file" into an
    ImportError there — every operation, not just saving. Nothing but a
    warehouse URL may reach for that module.
    """
    import sys

    from trikedb import storage

    # sys.modules alone is not enough: once any earlier test has imported the
    # submodule, the package keeps it as an attribute and `from . import
    # storage_sql` is satisfied from there. Remove both.
    import trikedb

    monkeypatch.setitem(sys.modules, "trikedb.storage_sql", None)
    monkeypatch.delattr(trikedb, "storage_sql", raising=False)

    g = tmp_path / "g.yaml"
    db = TrikeDB(g)                              # used to raise here
    db.add("a", "P", "b")
    db.set_node("a", type="job")
    assert len(TrikeDB(g)) == 1
    assert TrikeDB(g).sparql("ASK { ?s t:P ?o }") is True
    assert storage.serialization(g) == "yaml"    # no import needed to answer

    # ...but asking for a warehouse URL is a real error, not a silent fallback
    with pytest.raises(ImportError):
        TrikeDB("snowflake://DB.PUBLIC.T/g")


def test_sql_schemes_match_the_dialects():
    """storage.py names the SQL schemes without importing storage_sql.

    That duplication is deliberate (see the comment there) and therefore has
    to be kept honest, or a new dialect would be registered and never
    dispatched to.
    """
    from trikedb import storage, storage_sql

    assert set(storage._SQL_SCHEMES) == set(storage_sql.DIALECTS)


def test_dialect_templates_only_use_percent_s():
    """The Snowpark path rewrites %s to ?, so a stray percent would corrupt SQL."""
    import re

    from trikedb import storage_sql

    for dialect in storage_sql.DIALECTS.values():
        sql = [dialect.ddl, dialect.select, dialect.update,
               dialect.insert_if_absent, dialect.upsert, *dialect.views.values()]
        for stmt in sql:
            # %s (positional) and %(name)s (pyformat) are both legitimate;
            # anything else means a literal percent that binding would break on
            leftover = re.sub(r"%\(\w+\)s|%s", "", stmt)
            assert "%" not in leftover, f"{dialect.name}: stray percent in {stmt[:60]}"


class FakeSnowparkSession:
    """Shaped like snowflake.snowpark.Session: sql().collect(), no cursor().

    Snowflake answers DML with a row whose first cell is the affected count,
    which is what makes the compare-and-swap work without a rowcount.
    """

    def __init__(self, warehouse):
        self._wh = warehouse
        self.statements = []

    def sql(self, statement, params=None):
        self.statements.append(statement)
        assert "%s" not in statement, "Snowpark binds with ?, not %s"
        cursor = FakeCursor(self._wh)
        cursor.execute(statement.replace("?", "%s"), tuple(params or ()))
        if cursor.description is not None:      # a query: rows, or none of them
            return _Collected(list(cursor._rows))
        return _Collected([(cursor.rowcount,)])  # DML: Snowflake answers with a count


class _Collected:
    def __init__(self, rows):
        self._rows = rows

    def collect(self):
        return self._rows


def test_an_injected_connection_is_used_instead_of_building_one(warehouse):
    """Some hosts have a session and no way to make one.

    Inside Streamlit in Snowflake there are no credentials to find and no
    outbound connection to open — only the session the host already holds.
    """
    session = FakeSnowparkSession(warehouse)

    db = TrikeDB(URL, autosave=False, connection=session)
    db.add("salesflow", "PROVIDES", "crm-sync-job")
    db.save()

    assert warehouse.opens == 0, "it built a connection despite being given one"
    assert session.statements, "the injected session was never used"
    assert warehouse.rows["sales/crm"]

    # reads come back through the same session, and read_only composes
    ro = TrikeDB(URL, connection=session, read_only=True)
    assert [t.s for t in ro] == ["salesflow"]
    with pytest.raises(ValueError, match="read_only=True"):
        ro.add("x", "P", "y")


def test_injected_db_api_connection_also_works(warehouse):
    """The DB-API shape keeps working — dispatch is on capability, not type."""
    db = TrikeDB(URL, autosave=False, connection=warehouse)
    db.add("a", "P", "b")
    db.save()
    assert warehouse.opens == 0
    assert [t.s for t in TrikeDB(URL, connection=warehouse)] == ["a"]


def test_an_unusable_connection_says_what_it_needed(warehouse):
    from trikedb import storage_sql

    with pytest.raises(TypeError, match="neither a DB-API connection"):
        storage_sql.open_url(URL, connection=object()).exists()


def test_union_merges_node_properties_per_key(tmp_path):
    """Per key, not per node — and the difference is silent when wrong.

    A node declared in two members keeps the first value of each key, so a
    description only the second member carries still survives. Reimplementing
    the union as "first member's dict wins" drops it with no error anywhere:
    the graph simply comes out slightly poorer than the files it was built
    from.
    """
    a = tmp_path / "a.yaml"
    a.write_text(
        "ontology:\n  predicates:\n    P: from a\n"
        "nodes:\n  shared: {type: skill, owner: team-a}\n"
        "triples:\n- {s: shared, p: P, o: x}\n", encoding="utf-8")
    b = tmp_path / "b.yaml"
    b.write_text(
        "ontology:\n  predicates:\n    P: from b\n    Q: only in b\n"
        "nodes:\n  shared: {type: overridden, description: only in b}\n"
        "triples:\n- {s: shared, p: Q, o: y}\n", encoding="utf-8")
    ws = tmp_path / "ws.yaml"
    ws.write_text("graphs:\n  first: a.yaml\n  second: b.yaml\n", encoding="utf-8")

    db = TrikeDB(ws)
    props = db.node("shared")
    assert props["type"] == "skill"              # first member wins the key
    assert props["owner"] == "team-a"
    assert props["description"] == "only in b"   # ...but this must not vanish

    assert db.ontology["P"] == "from a"          # per predicate, first wins
    assert db.ontology["Q"] == "only in b"

    # a triple's `graph` attr is the workspace key, not the member filename
    assert {t.attrs["graph"] for t in db} == {"first", "second"}


def test_a_union_of_warehouse_members_inherits_the_connection(warehouse):
    """The shape that makes a union usable where nothing can connect.

    A host holding only a session can open a workspace whose members are
    warehouse rows: the members are opened through the same session, so no
    member has to find credentials of its own.
    """
    import json

    for name, doc in (
        ("kg/one", {"ontology": {"predicates": {"P": "from one"}},
                    "nodes": {"shared": {"type": "skill"}},
                    "triples": [{"s": "shared", "p": "P", "o": "x"}]}),
        ("kg/two", {"nodes": {"shared": {"description": "only in two"}},
                    "triples": [{"s": "shared", "p": "P", "o": "y"}]}),
    ):
        warehouse.rows[name] = [json.dumps(doc), f"v-{name}"]

    ws = {"graphs": {"one": f"snowflake://{TABLE}/kg/one",
                     "two": f"snowflake://{TABLE}/kg/two"}}
    warehouse.rows["kg/ws"] = [json.dumps(ws), "v-ws"]

    db = TrikeDB(f"snowflake://{TABLE}/kg/ws", connection=warehouse, read_only=True)

    assert warehouse.opens == 0                       # nothing connected itself
    assert db.read_only is True
    assert len(db) == 2
    assert {t.attrs["graph"] for t in db} == {"one", "two"}
    props = db.node("shared")
    assert props["type"] == "skill" and props["description"] == "only in two"
    with pytest.raises(ValueError):
        db.add("x", "P", "y")


def test_json_documents_load_through_the_fast_parser(tmp_path):
    """A warehouse row holds JSON; reading it with a YAML parser was ~400x slower.

    Correct, which is why it went unnoticed for two releases. Both parsers
    agree on JSON — it is a subset of YAML — so this is purely about which
    one runs.
    """
    import json

    from trikedb import db as db_module

    doc = {
        "ontology": {"predicates": {"P": "a -> b"}},
        "nodes": {"n": {"type": "job", "pii": False, "label": "日本語"}},
        "triples": [{"s": "a", "p": "P", "o": "b", "note": "x"},
                    {"s": "c", "p": "P", "o": "2025-04 v3: units changed"}],
    }
    as_json = json.dumps(doc, ensure_ascii=False, indent=2)
    as_yaml = yaml.dump(doc, sort_keys=False, allow_unicode=True,
                        default_flow_style=None, width=120)

    # the two forms must parse to exactly the same graph
    assert db_module._parse_document(as_json) == db_module._parse_document(as_yaml) == doc
    assert db_module._parse_document("") == {}
    assert db_module._parse_document("   \n") == {}

    # a flow-style YAML document starts with '{' but is not JSON — the
    # fallback has to catch it rather than raising
    assert db_module._parse_document("{triples: [{s: a, p: P, o: b}]}") == {
        "triples": [{"s": "a", "p": "P", "o": "b"}]}

    # end to end, both on disk
    for name, text in (("g.yaml", as_yaml), ("g.json", as_json)):
        p = tmp_path / name
        p.write_text(text, encoding="utf-8")
        loaded = TrikeDB(p)
        assert len(loaded) == 2
        assert loaded.node("n")["label"] == "日本語"
        assert loaded.ontology == {"P": "a -> b"}


def test_a_json_path_round_trips_as_json(tmp_path):
    """`.json` is the escape hatch for a graph read far more than reviewed."""
    from trikedb import storage

    assert storage.serialization("g.yaml") == "yaml"
    assert storage.serialization("g.json") == "json"
    assert storage.serialization(tmp_path / "G.JSON") == "json"

    p = tmp_path / "g.json"
    db = TrikeDB(p)
    db.add("a", "P", "b", note="x")
    db.set_node("a", type="job")

    import json

    written = json.loads(p.read_text(encoding="utf-8"))   # really JSON, not YAML
    assert written["triples"][0]["note"] == "x"
    assert [t.s for t in TrikeDB(p)] == ["a"]             # and reads back


def test_the_query_graph_is_reused_but_never_stale(tmp_path):
    """Rebuilding per call was two thirds of a query's cost.

    The danger of caching it is the opposite failure — answering from a graph
    that no longer matches the store — so every mutation path has to drop it.
    """
    db = TrikeDB(tmp_path / "g.yaml", autosave=False)
    db.add("a", "P", "b")
    Q = "SELECT ?o WHERE { t:a t:P ?o }"

    assert db.sparql(Q) == [{"o": "b"}]
    first = db._rdf_cache[1]
    assert db.sparql(Q) == [{"o": "b"}]
    assert db._rdf_cache[1] is first          # reused, not rebuilt

    for mutate, expected in (
        (lambda: db.add("a", "P", "c"), {"b", "c"}),
        (lambda: db.remove(o="c"), {"b"}),
        (lambda: db.set_node("a", type="job"), {"b"}),
        (lambda: db.update("INSERT DATA { t:a t:P t:d }"), {"b", "d"}),
        (lambda: db.save(), {"b", "d"}),
    ):
        mutate()
        assert db._rdf_cache is None, "a mutation left the built graph in place"
        assert {r["o"] for r in db.sparql(Q)} == expected

    # a different base must not be served from the cache either: the URIs in
    # the built graph depend on it, so a hit here would answer with the
    # wrong vocabulary
    assert {r["o"] for r in db.sparql(Q)} == {"b", "d"}
    assert db._rdf_cache[0][0] == "urn:trikedb:"
    # t: binds to whichever base was passed, so the answer is the same — but
    # the graph behind it is a different one and must not be a cache hit
    assert {r["o"] for r in db.sparql(Q, base="urn:other:")} == {"b", "d"}
    assert db._rdf_cache[0][0] == "urn:other:"   # rebuilt for the new base


# ------------------------------------------------- two SPARQL engines, one graph

def _engines():
    """rdflib always; oxigraph when the extra is installed."""
    from trikedb.db import _oxigraph_available

    return ["rdflib"] + (["oxigraph"] if _oxigraph_available() else [])


@pytest.fixture(params=_engines())
def engine(request):
    return request.param


def test_both_engines_answer_identically(engine, tmp_path):
    """Two SPARQL implementations over one graph must not disagree.

    This is the failure that would be hardest to catch, because either answer
    looks plausible on its own. Typed literals are the sharp edge: `t:pii true`
    matches a boolean, and an engine that stored it as a plain string returns
    nothing at all — a silent empty result, not an error.
    """
    db = TrikeDB(tmp_path / "g.yaml", autosave=False, sparql_engine=engine,
                 ontology={"PROVIDES": "", "INGESTS_TO": "", "AFFECTED_BY": ""})
    db.add("salesflow", "PROVIDES", "crm-sync-job")
    db.add("crm-sync-job", "INGESTS_TO", "RAW_CRM", schedule="hourly", prov="doc.md")
    db.add("T", "AFFECTED_BY", "2025-04 API v3: units changed")
    db.set_node("RAW_CRM", type="table", pii=True, rows=1000, ratio=2.5,
                label="生CRM")
    db.set_node("crm-sync-job", type="job", pii=False)
    assert db.sparql_engine == engine

    # plain traversal and a two-hop join
    assert db.sparql("SELECT ?o WHERE { t:salesflow t:PROVIDES ?o }") == [
        {"o": "crm-sync-job"}]
    assert db.sparql(
        "SELECT ?v ?t WHERE { ?v t:PROVIDES ?j . ?j t:INGESTS_TO ?t }") == [
        {"v": "salesflow", "t": "RAW_CRM"}]

    # ASK
    assert db.sparql("ASK { ?x t:PROVIDES ?y }") is True
    assert db.sparql("ASK { ?x t:NOPE ?y }") is False

    # typed literals — the sharp edge
    assert db.sparql('SELECT ?x WHERE { ?x t:type "table" }') == [{"x": "RAW_CRM"}]
    assert db.sparql("SELECT ?x WHERE { ?x t:pii true }") == [{"x": "RAW_CRM"}]
    assert db.sparql("SELECT ?x WHERE { ?x t:pii false }") == [{"x": "crm-sync-job"}]
    assert db.sparql("SELECT ?x WHERE { ?x t:rows 1000 }") == [{"x": "RAW_CRM"}]
    # a float property is xsd:double, while a bare 2.5 in SPARQL is
    # xsd:decimal — so it does not match, in either engine. Bind it or type it.
    assert db.sparql("SELECT ?x WHERE { ?x t:ratio 2.5 }") == []
    assert db.sparql(
        'SELECT ?x WHERE { ?x t:ratio "2.5"^^'
        "<http://www.w3.org/2001/XMLSchema#double> }") == [{"x": "RAW_CRM"}]
    assert db.sparql("SELECT ?r WHERE { t:RAW_CRM t:ratio ?r }") == [{"r": "2.5"}]

    # a free-text object is a literal, not a node
    assert db.sparql("SELECT ?e WHERE { t:T t:AFFECTED_BY ?e }") == [
        {"e": "2025-04 API v3: units changed"}]

    # non-ascii names survive percent-encoding in both
    assert db.sparql('SELECT ?x WHERE { ?x t:label "生CRM" }') == [{"x": "RAW_CRM"}]

    # edge attributes via RDF reification
    assert db.sparql(
        "SELECT ?s ?o WHERE { ?st rdf:subject ?s ; rdf:object ?o ;"
        ' t:schedule "hourly" }') == [{"s": "crm-sync-job", "o": "RAW_CRM"}]

    # FILTER, and a property path
    assert db.sparql(
        "SELECT ?t WHERE { ?j t:INGESTS_TO ?t ."
        ' FILTER(STRSTARTS(STR(?t), "urn:trikedb:RAW")) }') == [{"t": "RAW_CRM"}]
    assert db.sparql(
        "SELECT ?t WHERE { t:salesflow t:PROVIDES/t:INGESTS_TO ?t }") == [
        {"t": "RAW_CRM"}]

    # OPTIONAL leaves the variable unbound rather than emitting an empty string
    rows = db.sparql(
        "SELECT ?j ?missing WHERE { ?v t:PROVIDES ?j ."
        " OPTIONAL { ?j t:NOPE ?missing } }")
    assert rows == [{"j": "crm-sync-job"}]


def test_updates_and_reasoning_always_use_rdflib(tmp_path):
    """Writes, OWL and SHACL stay on one engine on purpose.

    update() diffs a built graph back onto the store, and owlrl/pyshacl take
    rdflib graphs. Routing those through a second implementation would buy
    nothing and risk the paths that change data.
    """
    db = TrikeDB(tmp_path / "g.yaml", autosave=False)
    db.add("a", "P", "b")
    before = db.sparql_engine

    assert db.sparql("INSERT DATA { t:c t:P t:d }") == 1
    assert ("c", "P", "d") in db
    assert db.sparql("DELETE WHERE { ?s t:P t:d }") == -1
    assert db.sparql_engine == before          # unchanged by the write path


def test_engine_can_be_pinned(tmp_path):
    """Comparing the two on a real query has to be possible."""
    db = TrikeDB(tmp_path / "g.yaml", autosave=False, sparql_engine="rdflib")
    db.add("a", "P", "b")
    assert db.sparql_engine == "rdflib"
    assert db.sparql("SELECT ?o WHERE { t:a t:P ?o }") == [{"o": "b"}]


#: SPARQL 1.1 surface both engines must answer identically. Compiled from a
#: run-off between rdflib and oxigraph: 25 of 26 forms agreed exactly, and the
#: one that did not turned out to be a form SPARQL leaves undefined rather
#: than a disagreement about the graph (see the test below).
_AGREEMENT_QUERIES = {
    "count": "SELECT (COUNT(?j) AS ?n) WHERE { ?v t:PROVIDES ?j }",
    "group by": "SELECT ?v (COUNT(?j) AS ?n) WHERE { ?v t:PROVIDES ?j }"
                " GROUP BY ?v ORDER BY ?v",
    "having": "SELECT ?v (COUNT(?j) AS ?n) WHERE { ?v t:PROVIDES ?j }"
              " GROUP BY ?v HAVING (COUNT(?j) > 1)",
    "aggregates": "SELECT (SUM(?r) AS ?s) (AVG(?r) AS ?a) (MIN(?r) AS ?mn)"
                  " (MAX(?r) AS ?mx) WHERE { ?t t:rows ?r }",
    "distinct": "SELECT DISTINCT ?t WHERE { ?j t:INGESTS_TO ?t } ORDER BY ?t",
    "order+limit": "SELECT ?j WHERE { ?v t:PROVIDES ?j } ORDER BY DESC(?j) LIMIT 2",
    "offset": "SELECT ?j WHERE { ?v t:PROVIDES ?j } ORDER BY ?j OFFSET 1 LIMIT 1",
    "bind": "SELECT ?j ?up WHERE { ?v t:PROVIDES ?j ."
            " BIND(UCASE(STR(?j)) AS ?up) } ORDER BY ?j",
    "values": "SELECT ?t WHERE { VALUES ?t { t:T1 t:T2 } ?t t:type ?x } ORDER BY ?t",
    "union": 'SELECT ?x WHERE { { ?x t:type "table" } UNION'
             ' { ?x t:type "saas" } } ORDER BY ?x',
    "minus": 'SELECT ?t WHERE { ?t t:type "table" MINUS { ?t t:pii true } }',
    "not exists": 'SELECT ?t WHERE { ?t t:type "table"'
                  " FILTER NOT EXISTS { ?t t:pii true } }",
    "subquery": "SELECT ?v WHERE { { SELECT ?v (COUNT(?j) AS ?n) WHERE"
                " { ?v t:PROVIDES ?j } GROUP BY ?v } FILTER(?n > 1) }",
    "regex": 'SELECT ?e WHERE { ?t t:AFFECTED_BY ?e FILTER(REGEX(?e, "^2025-04")) }',
    "string functions": 'SELECT ?e WHERE { ?t t:AFFECTED_BY ?e'
                        ' FILTER(CONTAINS(?e, "units") && STRLEN(?e) > 5) }',
    "numeric filter": "SELECT ?t WHERE { ?t t:rows ?r FILTER(?r > 10) }",
    "arithmetic": "SELECT (?r * 2 AS ?d) WHERE { t:T1 t:rows ?r }",
    "lang": 'SELECT ?l WHERE { t:v1 t:label ?l FILTER(LANG(?l) = "") }',
    "coalesce": 'SELECT (COALESCE(?missing, "none") AS ?c) WHERE { t:T1 t:rows ?r }',
    "if": 'SELECT (IF(?p, "yes", "no") AS ?flag) WHERE { t:T1 t:pii ?p }',
    "path star": "SELECT ?t WHERE { t:v1 t:PROVIDES/t:INGESTS_TO* ?t } ORDER BY ?t",
    "path alternative": "SELECT ?o WHERE { t:j1 (t:INGESTS_TO|t:COSTS) ?o } ORDER BY ?o",
    "optional": "SELECT ?j ?s WHERE { ?j t:INGESTS_TO ?t"
                " OPTIONAL { ?st rdf:subject ?j ; t:schedule ?s } } ORDER BY ?j",
    "ask false": "ASK { ?x t:NOPE ?y }",
    "ask true": "ASK { ?x t:PROVIDES ?y }",
}


def _agreement_graph(engine):
    db = TrikeDB(autosave=False, sparql_engine=engine,
                 ontology={"PROVIDES": "", "INGESTS_TO": "", "COSTS": "",
                           "AFFECTED_BY": ""})
    db.add("v1", "PROVIDES", "j1")
    db.add("v1", "PROVIDES", "j2")
    db.add("v2", "PROVIDES", "j3")
    db.add("j1", "INGESTS_TO", "T1", schedule="hourly")
    db.add("j2", "INGESTS_TO", "T1")
    db.add("j3", "INGESTS_TO", "T2")
    db.add("j1", "COSTS", "100")
    db.add("T1", "AFFECTED_BY", "2025-04 API v3: units changed")
    db.set_node("T1", type="table", pii=True, rows=42)
    db.set_node("T2", type="table", pii=False, rows=7)
    db.set_node("v1", type="saas", label="ベンダー1")
    return db


@pytest.mark.parametrize("name", sorted(_AGREEMENT_QUERIES))
def test_engines_agree_across_the_sparql_surface(name):
    """The engines must not disagree about the same graph.

    Basic traversal agreeing is not enough to make one of them the default:
    aggregates, subqueries, property paths and the string functions are where
    two implementations drift, and a drift here would look like a plausible
    answer rather than an error.
    """
    from trikedb.db import _oxigraph_available

    if not _oxigraph_available():
        pytest.skip("pyoxigraph not installed")

    query = _AGREEMENT_QUERIES[name]
    assert (_agreement_graph("rdflib").sparql(query)
            == _agreement_graph("oxigraph").sparql(query))


def test_undefined_aggregates_are_not_compared_between_engines():
    """GROUP_CONCAT ordering and SAMPLE's choice are undefined in SPARQL.

    The engines do differ here, and neither is wrong: GROUP_CONCAT without an
    ORDER BY has no defined order, and SAMPLE is specified as "some value".
    Pinning either answer would be pinning an accident — so this documents the
    boundary instead, which is also the one thing to know before switching a
    graph from one engine to the other.
    """
    from trikedb.db import _oxigraph_available

    if not _oxigraph_available():
        pytest.skip("pyoxigraph not installed")

    db = _agreement_graph("oxigraph")
    ref = _agreement_graph("rdflib")

    concat = "SELECT (GROUP_CONCAT(?l; SEPARATOR=\",\") AS ?g) WHERE { ?t t:label ?l }"
    both = {db.sparql(concat)[0]["g"], ref.sparql(concat)[0]["g"]}
    assert all(set(v.split(",")) == {"ベンダー1"} for v in both)   # same members

    sample = "SELECT (SAMPLE(?t) AS ?s) WHERE { ?j t:INGESTS_TO ?t }"
    assert db.sparql(sample)[0]["s"] in {"T1", "T2"}
    assert ref.sparql(sample)[0]["s"] in {"T1", "T2"}


def test_add_does_not_scan_the_graph(tmp_path):
    """add() is an upsert, so it has to look before appending.

    Doing that with a scan made building a graph O(n^2) — 100k triples took
    289 seconds and one add cost 2.9ms against 60us on a small graph. Loading
    was never affected, so it only bit graphs being *built*, which is what an
    agent does. This asserts the shape of the curve rather than a timing,
    which would be flaky on a loaded machine.
    """
    import time

    def build_ms(n):
        db = TrikeDB(autosave=False)
        start = time.perf_counter()
        for i in range(n):
            db.add(f"s{i}", "P", f"o{i}")
        return (time.perf_counter() - start) * 1000

    small, large = build_ms(2_000), build_ms(16_000)
    per_add_ratio = (large / 16_000) / (small / 2_000)
    # linear would be ~1x; the old scan was ~8x for this 8x size step
    assert per_add_ratio < 3, (
        f"cost per add grew {per_add_ratio:.1f}x for an 8x bigger graph — "
        "add() is scanning again")


def test_the_spo_index_never_answers_for_a_graph_that_moved(tmp_path):
    """The index's failure mode is silent: add() decides a triple already
    exists, updates an object no longer in the list, and drops the write.

    reload() is the dangerous path because it replaces the list with one that
    can coincidentally be the same length — which is exactly what happens
    when recovering from a write conflict.
    """
    g = tmp_path / "g.yaml"
    TrikeDB(g, autosave=False).save()

    db = TrikeDB(g, autosave=False)
    db.add("a", "P", "b")
    db.add("dropped", "P", "x")          # in this copy only
    assert len(db) == 2

    # someone else's graph, same length, different contents
    other = TrikeDB(g, autosave=False)
    other.add("a", "P", "b")
    other.add("theirs", "P", "y")
    other.save()

    db.reload()
    assert {t.s for t in db} == {"a", "theirs"}
    db.add("dropped", "P", "x")          # must land: it is not in this graph
    assert {t.s for t in db} == {"a", "theirs", "dropped"}

    # remove() and SPARQL update replace the list too
    db.remove(s="theirs")
    db.add("theirs", "P", "y")
    assert ("theirs", "P", "y") in db
    db.update("DELETE WHERE { ?s t:P t:x }")
    db.add("dropped", "P", "x")
    assert ("dropped", "P", "x") in db

    # upsert still merges attributes onto the existing triple
    before = len(db)
    db.add("a", "P", "b", note="merged")
    assert len(db) == before
    assert next(t for t in db if t.spo() == ("a", "P", "b")).attrs["note"] == "merged"

    # a file with the same triple twice: first entry wins, as the scan did
    dupes = tmp_path / "d.yaml"
    dupes.write_text(
        "triples:\n- {s: a, p: P, o: b, tag: first}\n- {s: a, p: P, o: b, tag: second}\n",
        encoding="utf-8")
    d = TrikeDB(dupes, autosave=False)
    d.add("a", "P", "b", extra=1)
    assert d._triples[0].attrs == {"tag": "first", "extra": 1}
    assert d._triples[1].attrs == {"tag": "second"}


def test_no_version_number_drifts_out_of_date():
    """Two files carry the version; everywhere else it goes stale silently.

    A release bumps `pyproject.toml` and `__init__.py`. Any *other* place that
    spells the current version out — a doc header, a chart title, a benchmark
    caption — is a copy nobody remembers to update, and it keeps claiming a
    version that shipped releases ago. Historical references are fine
    ("`add()` was O(n^2) until 0.27.0"); a claim about *this* build is not.
    """
    import re
    from pathlib import Path

    import trikedb

    root = Path(__file__).resolve().parent.parent
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    declared = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
    assert declared == trikedb.__version__, (
        f"pyproject.toml says {declared}, __init__.py says "
        f"{trikedb.__version__} — a release bumps both")

    # Anything that pins the *current* version outside those two files is a
    # copy that will rot. Phrase it as history, or point at the benchmark.
    current = re.compile(r"\btrikedb[ @]?v?" + re.escape(declared) + r"\b")
    checked = [
        *(root / "docs").glob("*.md"),
        *(root / "benchmarks").glob("*.md"),
        *(root / "benchmarks").glob("*.py"),
        root / "README.md",
    ]
    offenders = [
        f.relative_to(root).as_posix()
        for f in checked
        if f.exists() and current.search(f.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        f"these spell out the current version and will go stale: {offenders}. "
        "Say it as history, or let the badge/benchmark script carry it.")


def test_content_hash_is_stable_across_releases():
    """`content_hash()` is a compatibility surface, not an implementation detail.

    It is what `trikedb check --html` compares to decide an export is stale,
    and consumers build CI gates on it — "does the copy in the warehouse still
    match the file in git". Changing how it is computed would make every one
    of those gates fire on the same unchanged data, and the failure would look
    like a data problem rather than an upgrade.

    So the value is pinned. Touching this test means deciding, deliberately,
    to break everyone's cache and CI comparisons — which needs a major
    version and a release note, not a refactor.
    """
    db = TrikeDB(autosave=False,
                 ontology={"PROVIDES": "vendor -> job", "AFFECTED_BY": ""})
    db.add("salesflow-crm", "PROVIDES", "crm-sync-job")
    db.add("crm-sync-job", "AFFECTED_BY", "2025-04 API v3: units changed",
           prov="doc.md", deprecated=True, n=3)
    db.add("日本語", "PROVIDES", "値")
    db.set_node("crm-sync-job", type="job", label="CRM同期", pii=False, level=2)

    assert db.content_hash() == "cb3cf633dca7f002"

    # Order of insertion must not change it — the hash is over content, not
    # over the file, which is what lets two writers agree they hold the same
    # graph after arriving at it differently.
    other = TrikeDB(autosave=False,
                    ontology={"AFFECTED_BY": "", "PROVIDES": "vendor -> job"})
    other.add("日本語", "PROVIDES", "値")
    other.set_node("crm-sync-job", label="CRM同期", level=2, type="job", pii=False)
    other.add("crm-sync-job", "AFFECTED_BY", "2025-04 API v3: units changed",
              n=3, deprecated=True, prov="doc.md")
    other.add("salesflow-crm", "PROVIDES", "crm-sync-job")
    assert other.content_hash() == db.content_hash()

    # ...and the serialization it was written with must not change it either,
    # or a graph would stop matching itself on the way to a warehouse.
    import json
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp())
    as_yaml, as_json = tmp / "g.yaml", tmp / "g.json"
    db.save(as_yaml)
    db.save(as_json)
    assert json.loads(as_json.read_text())          # really is JSON
    assert TrikeDB(as_yaml).content_hash() == "cb3cf633dca7f002"
    assert TrikeDB(as_json).content_hash() == "cb3cf633dca7f002"


def test_the_running_code_is_the_code_on_disk():
    """Guard against a stale bytecode cache answering for edited source.

    This actually happened: a `.pyc` survived with a stamp matching the
    current file but bytecode compiled from a different one, so an edit to
    `content_hash` silently did not take effect and a verification run
    reported the *old* behaviour as if it were the new one. `git diff` looked
    right and `inspect.getsource` looked right — only the compiled constants
    disagreed.

    That failure mode is worse than a wrong answer, because it makes
    "I measured it" untrue while everything looks fine. Compiling the file
    again and comparing what the two code objects reference catches it
    without having to reason about which names an import binds.
    """
    import importlib
    import pathlib as _pathlib

    def references(code, seen=None):
        """Every global name the code object and its nested ones reach for."""
        out = set(code.co_names)
        for const in code.co_consts:
            if hasattr(const, "co_names"):
                out |= references(const)
        return out

    for name in ("db", "storage", "storage_sql", "cli", "audit", "importers",
                 "semantics", "semantic", "html"):
        module = importlib.import_module(f"trikedb.{name}")
        path = _pathlib.Path(module.__file__)
        fresh = compile(path.read_text(encoding="utf-8"), str(path), "exec")

        loaded = set()
        for obj in vars(module).values():
            code = getattr(obj, "__code__", None)
            if code is not None and code.co_filename == module.__file__:
                loaded |= references(code)
            for attr in vars(obj).values() if isinstance(obj, type) else ():
                code = getattr(attr, "__code__", None)
                if code is not None and code.co_filename == module.__file__:
                    loaded |= references(code)

        drift = sorted(loaded - references(fresh))
        assert not drift, (
            f"trikedb.{name}: the loaded module references {drift}, which "
            f"recompiling {path.name} does not — the bytecode cache is stale. "
            "Delete __pycache__ and rerun; any measurement taken in this "
            "state was of the old code.")


def test_serve_opens_the_graph_once(tmp_path):
    """/sparql used to rebuild the whole graph on every request.

    The MCP tools have always opened the graph once and shared it; /sparql
    did not, so the same server answered the same question two orders of
    magnitude apart depending on which door you came in — 320 ms against
    1 ms on a 15,000-triple graph, and it never warmed up because the parsed
    graph and the built query index were discarded between calls.
    """
    pytest.importorskip("starlette")
    from starlette.testclient import TestClient

    from trikedb.serve import build_app

    g = tmp_path / "g.yaml"
    db = TrikeDB(g, autosave=False)
    for i in range(300):
        db.add(f"v{i % 20}", "PROVIDES", f"job{i}")
    db.save()

    client = TestClient(build_app(str(g), with_mcp=False))
    query = {"query": "SELECT ?o WHERE { t:v0 t:PROVIDES ?o }"}
    first = client.post("/sparql", json=query).json()["rows"]
    assert first

    # the second call must be served from the graph the first one built
    import trikedb.db as db_module

    reads = []
    original = db_module._read_text
    db_module._read_text = lambda *a, **k: (reads.append(1),
                                            original(*a, **k))[1]
    try:
        assert client.post("/sparql", json=query).json()["rows"] == first
        client.get("/")
    finally:
        db_module._read_text = original
    assert not reads, "a request re-read the graph from storage"


def test_a_rest_update_writes_once(tmp_path):
    """One statement, one write.

    The handler called save() on top of the autosave that had already run, so
    every REST update wrote the document twice — two conditional writes on a
    bucket or a warehouse, and two chances to lose a race for one change.
    """
    pytest.importorskip("starlette")
    from starlette.testclient import TestClient

    import trikedb.db as db_module
    from trikedb.serve import build_app

    g = tmp_path / "g.yaml"
    TrikeDB(g, autosave=False).save()
    client = TestClient(build_app(str(g), with_mcp=False))

    writes = []
    original = db_module._write_text
    db_module._write_text = lambda *a, **k: (writes.append(1),
                                             original(*a, **k))[1]
    try:
        body = client.post(
            "/sparql", json={"query": "INSERT DATA { t:x t:P t:y }"}).json()
    finally:
        db_module._write_text = original

    assert body["delta"] == 1
    assert len(writes) == 1, f"one update caused {len(writes)} writes"
    assert ("x", "P", "y") in TrikeDB(g)          # and it landed


def test_the_static_token_is_compared_in_constant_time():
    """`==` on a secret leaks it one character at a time under timing."""
    import inspect
    import secrets

    from trikedb import serve

    source = inspect.getsource(serve)
    assert "secrets.compare_digest" in source
    assert 'header == f"Bearer {token}"' not in source
    assert secrets.compare_digest("a", "a")       # the import is real


def test_import_does_not_rename_nodes_called_true_or_false(tmp_path):
    """s/p/o name things, so they stay text.

    Coercing them turned a node genuinely called "false" into the boolean
    False, which the store then wrote back as the string "False" — the graph
    quietly disagreed with the CSV it was built from, capital letter and all.
    Attribute columns still coerce, which is where a boolean is wanted.
    """
    csv = tmp_path / "t.csv"
    csv.write_text("s,p,o,flag\nfalse,IS,true,false\n", encoding="utf-8")

    from trikedb.importers import read_csv

    assert read_csv(csv) == [{"s": "false", "p": "IS", "o": "true", "flag": False}]

    g = tmp_path / "g.yaml"
    db = TrikeDB(g, autosave=False)
    db.import_file(str(csv))
    db.save()
    triple = next(iter(TrikeDB(g)))
    assert (triple.s, triple.p, triple.o) == ("false", "IS", "true")
    assert triple.attrs == {"flag": False}


def test_markdown_import_ignores_fenced_examples(tmp_path):
    """A table inside a code fence is an example, not data.

    Documenting "do not write this" imported exactly that, which is a nasty
    way for a design doc to poison the graph it documents.
    """
    from trikedb.importers import read_markdown

    doc = tmp_path / "doc.md"
    doc.write_text(
        "# real\n"
        "| s | p | o |\n|---|---|---|\n| a | P | b |\n\n"
        "an example of what not to write:\n\n"
        "```\n| s | p | o |\n|---|---|---|\n| BAD | BAD | BAD |\n```\n\n"
        "~~~markdown\n| s | p | o |\n|---|---|---|\n| ALSO_BAD | X | Y |\n~~~\n",
        encoding="utf-8")
    assert read_markdown(doc) == [{"s": "a", "p": "P", "o": "b"}]


def test_audit_does_not_flag_properties_on_a_predicate():
    """Attaching properties to a predicate is a documented pattern.

    REFERENCE.md recommends `set_node("PROVIDES", since="2024")` — RDF treats
    a predicate as an ordinary name — and `audit` reported it as an orphan,
    so following the advice produced a warning.
    """
    db = TrikeDB(autosave=False)
    db.add("a", "PROVIDES", "b")
    db.set_node("PROVIDES", since="2024")
    assert db.audit() == []

    db.set_node("nobody-mentions-me", type="x")     # a real orphan still is one
    assert [f["kind"] for f in db.audit()] == ["orphan-node"]


def test_search_payload_keys_cannot_be_hijacked_by_attributes():
    """`score` and `kind` are the payload's, and attributes keep their values.

    A fact annotated `score=0.99` used to come back claiming that was its
    similarity; one annotated `kind="mine"` was skipped by every caller
    checking `kind == "triple"`. Making the reserved keys win then dropped
    the attributes instead — so they are kept under `attr_<name>`.
    """
    pytest.importorskip("model2vec")
    db = TrikeDB(autosave=False)
    db.add("alpha", "PROVIDES", "beta", score=0.99, kind="mine", note="ok")
    db.set_node("gamma", node="clash", type="thing")

    hits = db.search("alpha PROVIDES beta", k=10)
    triple = next(h for h in hits if h["kind"] == "triple")
    node = next(h for h in hits if h["kind"] == "node")

    assert triple["score"] != 0.99                  # the real similarity
    assert (triple["s"], triple["p"], triple["o"]) == ("alpha", "PROVIDES", "beta")
    assert triple["attr_score"] == 0.99             # nothing was dropped
    assert triple["attr_kind"] == "mine"
    assert triple["note"] == "ok"                   # ordinary attrs untouched
    assert node["node"] == "gamma" and node["attr_node"] == "clash"


def test_bigquery_is_registered_as_a_dialect():
    """A second warehouse should cost one _Dialect literal, and did."""
    from trikedb import storage, storage_sql

    assert set(storage_sql.DIALECTS) == {"snowflake", "bigquery"}
    assert set(storage._SQL_SCHEMES) == set(storage_sql.DIALECTS)
    assert storage.serialization("bigquery://p.d.T/g") == "json"
    assert set(storage_sql.BIGQUERY.views) == {
        "KG_NODE", "KG_EDGE", "KG_PREDICATE", "KG_TRIPLE"}


def test_identifier_rules_are_per_dialect():
    """A GCP project id has hyphens; no Snowflake identifier may.

    One shared pattern rejected every real BigQuery table. The table name is
    interpolated into SQL — a parameter cannot carry an identifier — so this
    stays a whitelist per dialect rather than a relaxed one shared.
    """
    from trikedb import storage_sql

    _, table, name = storage_sql._split("bigquery://ca-data-1234.ds.T/kg/g")
    assert (table, name) == ("ca-data-1234.ds.T", "kg/g")
    _, snow, _ = storage_sql._split("snowflake://DB.PUBLIC.T/g")
    assert snow == "DB.PUBLIC.T"

    # hyphens are legal for BigQuery and not for Snowflake
    with pytest.raises(ValueError):
        storage_sql._split("snowflake://has-dash.T/g")
    # and injection dies at the door for both
    for hostile in ("bigquery://p;DROP.ds.T/g", "bigquery://`p`.ds.T/g",
                    "snowflake://T; DROP TABLE X/g"):
        with pytest.raises(ValueError):
            storage_sql._split(hostile)


def test_quoting_is_applied_at_the_point_of_use():
    """Storing the quoted name broke deriving a schema from it.

    `proj.dataset.T` became `` `proj.dataset.T` ``, and rsplitting that for the
    view's schema produced `` `proj.dataset `` — an unclosed identifier literal
    that BigQuery rejected.
    """
    from trikedb import storage_sql

    ddl = storage_sql.ddl_for("bigquery://ca-data-1234.ds.TRIKE_GRAPHS/g")
    assert "CREATE TABLE IF NOT EXISTS `ca-data-1234.ds.TRIKE_GRAPHS`" in ddl
    assert "CREATE OR REPLACE VIEW `ca-data-1234.ds.KG_NODE`" in ddl
    assert "`ca-data-1234.ds`" not in ddl          # no half-quoted schema

    snow = storage_sql.ddl_for("snowflake://DB.PUBLIC.TRIKE_GRAPHS/g")
    assert "CREATE OR REPLACE VIEW DB.PUBLIC.KG_NODE" in snow
    assert "`" not in snow                          # Snowflake takes none


def test_named_parameters_are_read_off_the_statement():
    """Each statement takes its arguments in its own order.

    Declaring one order on the dialect mismapped them — the update takes
    (doc, version, name, expect) while the insert takes (name, doc, version) —
    and being wrong there does not raise: it compares the wrong column and
    reports a conflict that never happened.
    """
    import re

    from trikedb import storage_sql

    bq = storage_sql.BIGQUERY
    assert bq.named_params is True
    assert storage_sql.SNOWFLAKE.named_params is False

    def order(sql):
        return list(dict.fromkeys(re.findall(r"%\((\w+)\)s", sql)))

    assert order(bq.select) == ["name"]
    assert order(bq.update) == ["doc", "version", "name", "expect"]
    assert order(bq.insert_if_absent) == ["name", "doc", "version"]
    assert order(bq.upsert) == ["name", "doc", "version"]

    # the mapping the executor performs, and its guard against a mismatch
    assert storage_sql._named(bq, bq.update, ("D", "V", "N", "E")) == {
        "doc": "D", "version": "V", "name": "N", "expect": "E"}
    assert storage_sql._named(
        storage_sql.SNOWFLAKE, "x = %s", ("a",)) == ("a",)
    with pytest.raises(ValueError, match="binds"):
        storage_sql._named(bq, bq.update, ("only-one",))


def test_webqsp_metrics_follow_the_reference_implementation():
    """Hits@1 and F1 are the two metrics WebQSP results are published in.

    They have to be computed the way the reference does or a score here
    cannot go next to the literature — and a number that *looks* comparable
    and is not is worse than no number. The reference normalises (lowercase,
    strip punctuation, drop articles) and matches by substring, which is
    looser than exact match.
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "benchmarks"))
    from webqsp_bench import _normalize, f1, hits_at_1

    assert _normalize("The  Beatles, (band)!") == "beatles band"
    assert _normalize("<pad> A Hard Day's Night") == "hard days night"

    gold = ["Jamaican English", "Jamaican Creole English Language"]

    # substring, not exact: prose around the answer still counts
    assert hits_at_1("Jamaican English is spoken there", gold) == 1
    assert hits_at_1("I do not know", gold) == 0

    # one gold answer is enough for Hits@1, and both are needed for F1 == 1
    assert hits_at_1("Jamaican English", gold) == 1
    assert f1("Jamaican English", gold) == pytest.approx(2 / 3)
    assert f1("Jamaican English\nJamaican Creole English Language",
              gold) == pytest.approx(1.0)

    # listing everything scores Hits@1 but is punished by precision — the
    # reason published Hits@1 sits well above published F1
    shotgun = "A\nB\nC\nD\nJamaican English"
    assert hits_at_1(shotgun, gold) == 1
    assert f1(shotgun, gold) == pytest.approx(2 * 0.2 * 0.5 / 0.7, rel=1e-3)

    # a gold answer credited once, so repeating it cannot inflate recall
    assert f1("Jamaican English\nJamaican English", gold) == pytest.approx(0.5)

    assert f1("", gold) == 0.0 and f1("anything", []) == 0.0
