"""Standard RDF files cross the YAML boundary without changing RDF terms."""

import json
import subprocess
import sys

import pytest
from rdflib import BNode, Graph, Literal, Namespace, RDF, URIRef
from rdflib.compare import isomorphic

from trikedb import TrikeDB


EX = Namespace("https://example.org/")


@pytest.mark.parametrize("suffix,format", [(".ttl", "turtle"), (".nt", "nt"),
                                           (".jsonld", "json-ld")])
def test_standard_rdf_import_preserves_term_kinds_and_round_trips(tmp_path, suffix, format):
    source = Graph()
    source.add((EX.alice, RDF.type, EX.Person))
    source.add((EX.alice, EX.name, Literal("アリス", lang="ja")))
    source.add((EX.alice, EX.age, Literal("42", datatype=URIRef("http://www.w3.org/2001/XMLSchema#integer"))))
    source.add((EX.alice, EX.knows, BNode("friend")))
    source.add((BNode("friend"), EX.name, Literal("Bob")))
    source.add((EX.alice, EX.sameText, Literal("https://example.org/value")))
    source.add((EX.alice, EX.sameText, EX.value))
    rdf_path = tmp_path / ("people" + suffix)
    rdf_path.write_text(source.serialize(format=format), encoding="utf-8")

    path = tmp_path / "people.yaml"
    db = TrikeDB(path)
    assert db.import_file(rdf_path) == len(source)
    db.save()
    reloaded = TrikeDB(path)
    assert isomorphic(source, reloaded.to_rdflib(node_props=False, edge_attrs=False))
    assert reloaded.import_file(rdf_path) == 0


def test_cli_turtle_export_and_shacl_validation_of_imported_rdf(tmp_path):
    pytest.importorskip("pyshacl")
    source = tmp_path / "people.ttl"
    source.write_text("""@prefix ex: <https://example.org/> .
ex:alice a ex:Person ; ex:name "Alice" .
""", encoding="utf-8")
    path = tmp_path / "people.yaml"
    imported = subprocess.run([sys.executable, "-m", "trikedb.cli", "import", str(path), str(source)],
                              capture_output=True, text=True)
    assert imported.returncode == 0, imported.stderr
    exported = subprocess.run([sys.executable, "-m", "trikedb.cli", "turtle", str(path)],
                              capture_output=True, text=True)
    assert exported.returncode == 0, exported.stderr
    assert isomorphic(Graph().parse(data=exported.stdout, format="turtle"),
                      Graph().parse(source, format="turtle"))

    shapes = tmp_path / "shapes.ttl"
    shapes.write_text("""@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <https://example.org/> .
ex:PersonShape a sh:NodeShape ; sh:targetClass ex:Person ;
  sh:property [ sh:path ex:name ; sh:minCount 1 ] .
""", encoding="utf-8")
    validated = subprocess.run([sys.executable, "-m", "trikedb.cli", "validate", str(path), str(shapes)],
                               capture_output=True, text=True)
    assert validated.returncode == 0, validated.stdout + validated.stderr


def test_jsonld_import_does_not_fetch_remote_contexts(tmp_path):
    source = tmp_path / "remote.jsonld"
    source.write_text(json.dumps({"@context": "https://example.org/context.jsonld",
                                  "@id": "https://example.org/alice"}), encoding="utf-8")
    with pytest.raises(ValueError, match="remote JSON-LD context"):
        TrikeDB().read_file(source)


def test_native_yaml_exports_a_round_trippable_rdf_graph(tmp_path):
    source = TrikeDB(tmp_path / "native.yaml")
    source.set_node("alice", type="Person", label="Alice")
    source.add("alice", "KNOWS", "bob", prov="example")
    source.save()
    turtle = tmp_path / "native.ttl"
    turtle.write_text(source.to_rdflib().serialize(format="turtle"), encoding="utf-8")
    imported = TrikeDB(tmp_path / "imported.yaml")
    imported.import_file(turtle)
    assert isomorphic(source.to_rdflib(), imported.to_rdflib())


def test_shacl_rejects_invalid_import_before_yaml_is_written(tmp_path):
    pytest.importorskip("pyshacl")
    path = tmp_path / "people.yaml"
    source = tmp_path / "people.ttl"
    source.write_text("""@prefix ex: <https://example.org/> .
ex:alice a ex:Person .
""", encoding="utf-8")
    shapes = tmp_path / "shapes.ttl"
    shapes.write_text("""@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <https://example.org/> .
ex:PersonShape a sh:NodeShape ; sh:targetClass ex:Person ;
  sh:property [ sh:path ex:name ; sh:minCount 1 ] .
""", encoding="utf-8")
    command = [sys.executable, "-m", "trikedb.cli", "import", str(path), str(source),
               "--shapes", str(shapes)]
    invalid = subprocess.run(command, capture_output=True, text=True)
    assert invalid.returncode == 1
    assert "Conforms: False" in invalid.stderr
    assert not path.exists()

    source.write_text(source.read_text(encoding="utf-8") +
                      'ex:alice ex:name "Alice" .\n', encoding="utf-8")
    valid = subprocess.run(command, capture_output=True, text=True)
    assert valid.returncode == 0, valid.stderr
    assert len(TrikeDB(path)) == 2


def test_explicit_base_iri_is_shared_by_exports_queries_and_shacl(tmp_path):
    pytest.importorskip("pyshacl")
    path = tmp_path / "native.yaml"
    db = TrikeDB(path)
    db.set_node("alice", type="Person")
    db.add("alice", "KNOWS", "bob")
    base = "https://example.org/id/"
    turtle = subprocess.run([sys.executable, "-m", "trikedb.cli", "turtle", str(path),
                             "--base", base], capture_output=True, text=True)
    assert turtle.returncode == 0, turtle.stderr
    graph = Graph().parse(data=turtle.stdout, format="turtle")
    assert (URIRef(base + "alice"), RDF.type, URIRef(base + "Person")) in graph

    jsonld = subprocess.run([sys.executable, "-m", "trikedb.cli", "jsonld", str(path),
                             "--base", base], capture_output=True, text=True)
    assert jsonld.returncode == 0, jsonld.stderr
    assert isomorphic(graph, Graph().parse(data=jsonld.stdout, format="json-ld"))

    query = subprocess.run([sys.executable, "-m", "trikedb.cli", "sparql", str(path),
                            "SELECT ?s WHERE { ?s t:KNOWS t:bob }", "--base", base],
                           capture_output=True, text=True)
    assert query.returncode == 0, query.stderr
    assert "alice" in query.stdout

    shapes = tmp_path / "shapes.ttl"
    shapes.write_text("""@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <https://example.org/id/> .
ex:PersonShape a sh:NodeShape ; sh:targetClass ex:Person ;
  sh:property [ sh:path ex:KNOWS ; sh:minCount 1 ] .
""", encoding="utf-8")
    validated = subprocess.run([sys.executable, "-m", "trikedb.cli", "validate", str(path),
                                str(shapes), "--base", base], capture_output=True, text=True)
    assert validated.returncode == 0, validated.stdout + validated.stderr


def test_import_shacl_uses_the_requested_base_iri(tmp_path):
    pytest.importorskip("pyshacl")
    path = tmp_path / "native.yaml"
    db = TrikeDB(path)
    db.set_node("alice", type="Person")
    original = path.read_bytes()
    source = tmp_path / "extra.ttl"
    source.write_text('<https://example.org/extra> <https://example.org/knows> '
                      '<https://example.org/alice> .\n', encoding="utf-8")
    shapes = tmp_path / "shapes.ttl"
    shapes.write_text("""@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <https://example.org/id/> .
ex:PersonShape a sh:NodeShape ; sh:targetClass ex:Person ;
  sh:property [ sh:path ex:KNOWS ; sh:minCount 1 ] .
""", encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", "trikedb.cli", "import",
                             str(path), str(source), "--shapes", str(shapes),
                             "--base", "https://example.org/id/"],
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert "Conforms: False" in result.stderr
    assert path.read_bytes() == original


def test_native_uri_template_is_a_valid_rdf_iri_without_changing_yaml_name(tmp_path):
    path = tmp_path / "native.yaml"
    db = TrikeDB(path)
    template = "https://example.org/workspaces/{workspace_id}/usage"
    db.add(template, "POINTS_TO", "https://example.org/report")
    exported = db.to_rdflib().serialize(format="nt")
    reparsed = Graph().parse(data=exported, format="nt")
    assert (URIRef("https://example.org/workspaces/%7Bworkspace_id%7D/usage"),
            URIRef("urn:trikedb:POINTS_TO"), URIRef("https://example.org/report")) in reparsed
    assert next(TrikeDB(path).triples()).s == template
