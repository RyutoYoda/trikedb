"""Exercise a standard SHACL shape through the installed CLI and YAML store."""

import subprocess
import sys

import pytest
from rdflib import Literal, RDF, URIRef

from trikedb import TrikeDB


@pytest.mark.parametrize("case,component", [
    ("min_count", "MinCountConstraintComponent"),
    ("datatype", "DatatypeConstraintComponent"),
    ("class", "ClassConstraintComponent"),
    ("closed", "ClosedConstraintComponent"),
    ("max_count", "MaxCountConstraintComponent"),
    ("node_kind", "NodeKindConstraintComponent"),
    ("pattern", "PatternConstraintComponent"),
    ("in", "InConstraintComponent"),
    ("has_value", "HasValueConstraintComponent"),
    ("min_length", "MinLengthConstraintComponent"),
])
def test_shacl_core_corpus_matches_pyshacl_on_valid_and_invalid_graphs(
    tmp_path, case, component,
):
    """Check the CLI boundary against pySHACL across common Core constraints."""
    pyshacl = pytest.importorskip("pyshacl")
    from rdflib import Graph

    prefix = """@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix t: <urn:trikedb:> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
"""
    constraints = {
        "min_count": "sh:property [ sh:path t:name ; sh:minCount 1 ]",
        "datatype": "sh:property [ sh:path t:age ; sh:datatype xsd:integer ]",
        "class": "sh:property [ sh:path t:memberOf ; sh:class t:Organization ]",
        "closed": "sh:closed true ; sh:property [ sh:path t:status ]",
        "max_count": "sh:property [ sh:path t:memberOf ; sh:maxCount 1 ]",
        "node_kind": "sh:property [ sh:path t:memberOf ; sh:nodeKind sh:IRI ]",
        "pattern": 'sh:property [ sh:path t:name ; sh:pattern "^EMP-[0-9]+$" ]',
        "in": 'sh:property [ sh:path t:status ; sh:in ("active" "inactive") ]',
        "has_value": 'sh:property [ sh:path t:status ; sh:hasValue "active" ]',
        "min_length": "sh:property [ sh:path t:name ; sh:minLength 4 ]",
    }
    shape_text = prefix + (
        "t:Shape a sh:NodeShape ; sh:targetNode t:alice ; "
        + constraints[case] + " .\n"
    )
    shapes_path = tmp_path / "shapes.ttl"
    shapes_path.write_text(shape_text, encoding="utf-8")
    shape_graph = Graph().parse(data=shape_text, format="turtle")

    for valid in (False, True):
        path = tmp_path / ("valid.yaml" if valid else "invalid.yaml")
        db = TrikeDB(path)
        if case == "min_count":
            db.add("alice", "RELATED_TO", "bob")
            if valid:
                db.set_node("alice", name="Alice")
        elif case == "datatype":
            db.set_node("alice", age=42 if valid else "forty-two")
        elif case == "class":
            db.add("alice", "memberOf", "group")
            db.set_node("group", type="Organization" if valid else "Person")
        elif case == "closed":
            db.set_node("alice", status="active", **({} if valid else {"extra": "bad"}))
        elif case == "max_count":
            db.add("alice", "memberOf", "group")
            if not valid:
                db.add("alice", "memberOf", "other-group")
        elif case == "node_kind":
            if valid:
                db.add("alice", "memberOf", "group")
            else:
                db.set_node("alice", memberOf="literal value")
        elif case == "pattern":
            db.set_node("alice", name="EMP-123" if valid else "not-an-id")
        elif case == "in":
            db.set_node("alice", status="active" if valid else "paused")
        elif case == "has_value":
            db.set_node("alice", status="active" if valid else "paused")
        else:
            db.set_node("alice", name="Alice" if valid else "Al")
        db.save()

        expected, _, direct_report = pyshacl.validate(
            db.to_rdflib(edge_attrs=False), shacl_graph=shape_graph, inference="none"
        )
        command = subprocess.run(
            [sys.executable, "-m", "trikedb.cli", "validate", str(path), str(shapes_path)],
            capture_output=True, text=True, check=False,
        )
        assert bool(expected) is valid
        assert command.returncode == (0 if valid else 1), command.stdout + command.stderr
        assert f"Conforms: {expected}" in command.stdout
        if not valid:
            assert component in str(direct_report)
            assert component in command.stdout


def test_article_style_class_shape_validates_node_types_end_to_end(tmp_path):
    pytest.importorskip("pyshacl")
    graph_path = tmp_path / "people.yaml"
    shapes_path = tmp_path / "shapes.ttl"
    shapes_path.write_text(
        """@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix t: <urn:trikedb:> .

t:EmployeeShape a sh:NodeShape ;
  sh:targetClass t:Employee ;
  sh:property [ sh:path t:employeeId ; sh:minCount 1 ;
                sh:maxCount 1 ; sh:datatype <http://www.w3.org/2001/XMLSchema#string> ] ;
  sh:property [ sh:path t:worksFor ; sh:minCount 1 ; sh:class t:Organization ] .
""",
        encoding="utf-8",
    )

    db = TrikeDB(graph_path)
    db.set_node("yamada", type="Employee")
    db.set_node("abc", type="Person")
    db.add("yamada", "worksFor", "abc")

    def validate():
        return subprocess.run(
            [sys.executable, "-m", "trikedb.cli", "validate", str(graph_path), str(shapes_path)],
            capture_output=True, text=True, check=False,
        )

    invalid = validate()
    assert invalid.returncode == 1, invalid.stdout + invalid.stderr
    assert "yamada" in invalid.stdout
    assert "employeeId" in invalid.stdout
    assert "worksFor" in invalid.stdout

    db.set_node("yamada", employeeId="E001")
    db.set_node("abc", type="Organization", replace=True)
    valid = validate()
    assert valid.returncode == 0, valid.stdout + valid.stderr
    assert "Conforms: True" in valid.stdout

    rdf = TrikeDB(graph_path).to_rdflib()
    assert (URIRef("urn:trikedb:yamada"), RDF.type, URIRef("urn:trikedb:Employee")) in rdf
    assert (URIRef("urn:trikedb:yamada"), URIRef("urn:trikedb:type"), Literal("Employee")) in rdf


def test_sparql_shape_compares_related_resources_end_to_end(tmp_path):
    pytest.importorskip("pyshacl")
    graph_path = tmp_path / "access.yaml"
    shapes_path = tmp_path / "tenant-shapes.ttl"
    shapes_path.write_text(
        '''@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix t: <urn:trikedb:> .

t:TeamTenantShape a sh:NodeShape ;
  sh:targetClass t:Team ;
  sh:sparql [
    sh:message "Team and workspace must belong to the same tenant" ;
    sh:select """
      SELECT $this WHERE {
        $this t:canAccessWorkspace ?workspace ; t:belongsToTenant ?teamTenant .
        ?workspace t:belongsToTenant ?workspaceTenant .
        FILTER (?teamTenant != ?workspaceTenant)
      }
    """
  ] .
''',
        encoding="utf-8",
    )
    db = TrikeDB(graph_path)
    db.set_node("analytics", type="Team")
    db.set_node("reporting", type="Workspace")
    db.add("analytics", "canAccessWorkspace", "reporting")
    db.add("analytics", "belongsToTenant", "tenant-a")
    db.add("reporting", "belongsToTenant", "tenant-b")

    command = [sys.executable, "-m", "trikedb.cli", "validate", str(graph_path), str(shapes_path)]
    invalid = subprocess.run(command, capture_output=True, text=True, check=False)
    assert invalid.returncode == 1, invalid.stdout + invalid.stderr
    assert "analytics" in invalid.stdout
    assert "same tenant" in invalid.stdout

    db.remove("reporting", "belongsToTenant", "tenant-b")
    db.add("reporting", "belongsToTenant", "tenant-a")
    valid = subprocess.run(command, capture_output=True, text=True, check=False)
    assert valid.returncode == 0, valid.stdout + valid.stderr
