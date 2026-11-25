"""Workflow RDF follows P-Plan without changing the YAML authoring contract."""

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
        (T.publish, PPLAN.isPreceededBy, T.collect),
        (T.revise, PPLAN.isPreceededBy, T.collect),
    }
    assert expected <= set(graph)
    assert expected <= set(Graph().parse(data=graph.serialize(format="turtle"), format="turtle"))
    query = "ASK { t:publish pplan:isPreceededBy t:collect }"
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
    assert (T.other, PPLAN.isPreceededBy, T.unrelated) not in graph
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
