import pytest
import yaml

from triplite import OntologyError, TripLite


@pytest.fixture
def db(tmp_path):
    db = TripLite(tmp_path / "graph.yaml")
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
    db = TripLite()
    db.add("T", "AFFECTED_BY", "2025-04 API v3: units changed")
    rows = db.query(['?t AFFECTED_BY "2025-04 API v3: units changed"'])
    assert rows == [{"t": "T"}]


def test_save_load_roundtrip(db, tmp_path):
    path = db.save()
    again = TripLite(path)
    assert len(again) == len(db)
    assert [t.to_dict() for t in again] == [t.to_dict() for t in db]


def test_saved_yaml_is_flat_and_readable(db):
    doc = yaml.safe_load(db.save().read_text())
    assert {"s", "p", "o", "schedule"} <= set(doc["triples"][1])


def test_ontology_rejects_unknown_predicate(tmp_path):
    db = TripLite(tmp_path / "g.yaml", ontology={"PROVIDES": "vendor -> job"})
    db.add("a", "PROVIDES", "b")
    with pytest.raises(OntologyError):
        db.add("a", "TOTALLY_MADE_UP", "b")


def test_ontology_loaded_from_file(tmp_path):
    path = tmp_path / "g.yaml"
    path.write_text(
        "ontology:\n  predicates:\n    ONLY: allowed one\n"
        "triples:\n  - {s: a, p: ONLY, o: b}\n"
    )
    db = TripLite(path)
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
    assert "triplite knowledge graph" in html  # default title
    assert "urn:triplite:LEGACY_DUMP" in html  # embedded N-Triples for the engine


def test_html_event_predicates_detected(tmp_path):
    db = TripLite()
    db.add("T", "AFFECTED_BY", "2025-04 API v3: units changed")
    db.add("a", "DEPENDS_ON", "b")
    html = db.to_html()
    assert '"AFFECTED_BY"' in html.split("EVENT_PREDICATES = ")[1].split(";")[0]


def test_examples_load_and_query():
    from pathlib import Path

    examples = Path(__file__).resolve().parent.parent / "examples"
    acme = TripLite(examples / "acme_pipeline.yaml")
    assert len(acme.ontology) == 5
    rows = acme.query(["?v PROVIDES ?j", "?j INGESTS_TO ?t"])
    assert {"v": "salesflow-crm", "j": "crm-sync-job", "t": "RAW_CRM_CONTACTS"} in rows

    eco = TripLite(examples / "python_ecosystem.yaml")
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
        'SELECT ?t WHERE { ?j t:INGESTS_TO ?t . FILTER(STRSTARTS(STR(?t), "urn:triplite:RAW_CRM")) }'
    )
    assert rows == [{"t": "RAW_CRM_CONTACTS"}]


def test_sparql_ask(db):
    assert db.sparql("ASK { ?x t:MIGRATED_TO ?y }") is True
    assert db.sparql("ASK { ?x t:NOPE ?y }") is False


def test_sparql_freetext_objects_are_literals():
    db = TripLite()
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
    db = TripLite(tmp_path / "g.yaml", ontology={"PROVIDES": ""})
    db.add("a", "PROVIDES", "b")
    with pytest.raises(OntologyError):
        db.sparql("INSERT DATA { t:a t:MADE_UP t:b }")


def test_autosave_roundtrip(tmp_path):
    path = tmp_path / "g.yaml"
    db = TripLite(path, autosave=True)
    db.add("a", "P", "b")
    db.sparql("INSERT DATA { t:c t:P t:d }")
    assert len(TripLite(path)) == 2
    db.remove(s="a")
    assert len(TripLite(path)) == 1
