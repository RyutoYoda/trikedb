"""Exercise a standard SHACL shape through the installed CLI and YAML store."""

import subprocess
import sys

import pytest
from rdflib import Literal, RDF, URIRef

from trikedb import TrikeDB


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
