"""W3C R2RML 2012 test suite. Set TRIKEDB_W3C_R2RML_SUITE to its directory.

Source: https://dvcs.w3.org/hg/rdb2rdf-tests/raw-file/default/rdb2rdf-ts.zip
SHA-256: 128270b483042fd7612e10c071c3b81eb44c1c534f341ec6d5c2286675781f71
The test files are downloaded by CI and are not bundled in the package.
"""

import os
from pathlib import Path
import sqlite3

import pytest
from rdflib import BNode, Dataset, Graph, Namespace, RDF, URIRef
from rdflib.compare import isomorphic

from trikedb import R2RMLVirtualGraph


TEST = Namespace("http://purl.org/NET/rdb2rdf-test#")
QUAD = Namespace("urn:trikedb:w3c:quad:")
DEFAULT = URIRef("urn:trikedb:w3c:default")
SUITE = Path(os.environ["TRIKEDB_W3C_R2RML_SUITE"]) if os.environ.get(
    "TRIKEDB_W3C_R2RML_SUITE") else None


def _cases():
    if SUITE is None:
        return []
    result = []
    for manifest in sorted(SUITE.glob("*/manifest.ttl")):
        graph = Graph().parse(manifest, format="turtle")
        for case in graph.subjects(RDF.type, TEST.R2RML):
            result.append((manifest.parent, str(graph.value(case, TEST.mappingDocument)),
                           str(graph.value(case, TEST.output)) if graph.value(case, TEST.output) else None,
                           str(graph.value(case, TEST.hasExpectedOutput)) == "true"))
    return result


CASES = _cases()


def _quad_graph(dataset):
    """Encode quads as triples so RDF graph isomorphism covers blank nodes."""
    graph = Graph()
    for subject, predicate, obj, context in dataset.quads((None, None, None, None)):
        statement = BNode()
        graph.add((statement, QUAD.subject, subject))
        graph.add((statement, QUAD.predicate, predicate))
        graph.add((statement, QUAD.object, obj))
        graph.add((statement, QUAD.graph,
                   DEFAULT if context == dataset.default_graph.identifier else context))
    return graph


@pytest.mark.skipif(SUITE is None, reason="download the pinned W3C suite and set TRIKEDB_W3C_R2RML_SUITE")
def test_official_suite_has_expected_case_count():
    assert len(CASES) == 63


@pytest.mark.parametrize("directory,mapping_file,expected_file,positive", CASES,
                         ids=[f"{directory.name}/{mapping_file}" for directory, mapping_file, _, _ in CASES])
def test_w3c_r2rml_case(directory, mapping_file, expected_file, positive):
    connection = sqlite3.connect(":memory:")
    connection.executescript((directory / "create.sql").read_text(encoding="utf-8"))
    mapping = directory / mapping_file
    if not positive:
        with pytest.raises((ValueError, sqlite3.OperationalError)):
            R2RMLVirtualGraph(mapping, connection).export_rdf("nquads")
        return
    actual = Dataset().parse(
        data=R2RMLVirtualGraph(mapping, connection).export_rdf("nquads"),
        format="nquads")
    expected = Dataset().parse(directory / expected_file, format="nquads")
    assert isomorphic(_quad_graph(actual), _quad_graph(expected))
