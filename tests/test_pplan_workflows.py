"""Workflow RDF follows P-Plan without changing the YAML authoring contract."""

from pathlib import Path

import pytest
from rdflib import Graph, Namespace, RDF

from trikedb import TrikeDB


PPLAN = Namespace("http://purl.org/net/p-plan#")
T = Namespace("urn:trikedb:")


def test_branching_workflow_projects_pplan_in_both_engines_and_after_save(tmp_path):
    path = tmp_path / "workflow.yaml"
    path.write_text("""workflows:
  report:
    steps:
      - id: collect
        next: [publish, revise]
      - id: publish
      - id: revise
""", encoding="utf-8")
    db = TrikeDB(path)
    graph = db.to_rdflib()
    expected = {
        (T.report, RDF.type, PPLAN.Plan),
        (T.collect, RDF.type, PPLAN.Step),
        (T.publish, RDF.type, PPLAN.Step),
        (T.revise, RDF.type, PPLAN.Step),
        (T.collect, PPLAN.isStepOfPlan, T.report),
        (T.publish, PPLAN.isStepOfPlan, T.report),
        (T.revise, PPLAN.isStepOfPlan, T.report),
        (T.publish, PPLAN.isPrecededBy, T.collect),
        (T.revise, PPLAN.isPrecededBy, T.collect),
    }
    assert expected <= set(graph)
    assert expected <= set(Graph().parse(data=graph.serialize(format="turtle"), format="turtle"))
    query = "ASK { t:publish pplan:isPrecededBy t:collect }"
    assert db.sparql(query)
    db.save()
    reopened = TrikeDB(path)
    assert expected <= set(reopened.to_rdflib())
    assert reopened.sparql(query)
    reopened.sparql_engine = "oxigraph"
    assert reopened.sparql(query)


def test_pplan_projection_only_maps_declared_workflow_steps(tmp_path):
    db = TrikeDB(tmp_path / "graph.yaml")
    db.add("unrelated", "NEXT_STEP", "other")
    db.set_node("unrelated", type="document")
    db.set_node("other", type="document")
    graph = db.to_rdflib()
    assert (T.other, PPLAN.isPrecededBy, T.unrelated) not in graph
    assert (T.unrelated, RDF.type, PPLAN.Step) not in graph


def test_pplan_export_passes_shacl(tmp_path):
    pyshacl = pytest.importorskip("pyshacl")
    path = tmp_path / "workflow.yaml"
    path.write_text("""workflows:
  report:
    steps:
      - id: collect
        next: publish
      - id: publish
""", encoding="utf-8")
    shapes = Graph().parse(data="""@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix pplan: <http://purl.org/net/p-plan#> .
[] a sh:NodeShape ; sh:targetClass pplan:Step ;
   sh:property [ sh:path pplan:isStepOfPlan ; sh:minCount 1 ;
                 sh:class pplan:Plan ] .
""", format="turtle")
    conforms, _, report = pyshacl.validate(TrikeDB(path).to_rdflib(), shacl_graph=shapes)
    assert conforms, report


def test_prov_execution_and_plan_can_share_one_yaml_and_round_trip(tmp_path):
    source = Path(__file__).resolve().parents[1] / "examples" / "provenance_workflow.yaml"
    db = TrikeDB(source)
    assert db.sparql("ASK { t:run-001 pplan:correspondsToStep t:build-report }")
    assert db.sparql("ASK { t:run-001 prov:used t:sample-input }")
    assert db.sparql("ASK { t:report-v2 prov:wasGeneratedBy t:run-001 }")
    assert db.sparql("ASK { t:report-v2 prov:wasRevisionOf t:report-v1 }")
    assert db.sparql("ASK { t:build-report pplan:isPrecededBy t:gather-input }")
    graph = db.to_rdflib()
    assert (T["run-001"], RDF.type, Namespace("http://www.w3.org/ns/prov#").Activity) in graph
    copy = tmp_path / "copy.yaml"
    copy.write_bytes(source.read_bytes())
    TrikeDB(copy).save()
    assert TrikeDB(copy).sparql("ASK { t:report-v2 prov:wasRevisionOf t:report-v1 }")
