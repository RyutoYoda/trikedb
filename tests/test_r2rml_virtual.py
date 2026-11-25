"""A W3C R2RML mapping over a DB-API connection, without graph storage."""

import sqlite3

import pytest
from rdflib import Graph, Literal, URIRef

from trikedb.r2rml import R2RMLVirtualGraph


MAPPING = """@prefix rr: <http://www.w3.org/ns/r2rml#> .
@prefix ex: <https://example.org/> .

<#Person> a rr:TriplesMap ;
  rr:logicalTable [ rr:tableName "people" ] ;
  rr:subjectMap [ rr:template "https://example.org/person/{id}" ; rr:class ex:Person ] ;
  rr:predicateObjectMap [ rr:predicate ex:name ; rr:objectMap [ rr:column "name" ] ] ;
  rr:predicateObjectMap [ rr:predicate ex:worksFor ; rr:objectMap [
    rr:parentTriplesMap <#Company> ;
    rr:joinCondition [ rr:child "company_id" ; rr:parent "id" ]
  ] ] .

<#Company> a rr:TriplesMap ;
  rr:logicalTable [ rr:tableName "companies" ] ;
  rr:subjectMap [ rr:template "https://example.org/company/{id}" ; rr:class ex:Company ] ;
  rr:predicateObjectMap [ rr:predicate ex:label ; rr:objectMap [ rr:column "name" ] ] .
"""


def _fixture(tmp_path):
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT, company_id INTEGER)")
    connection.execute("CREATE TABLE companies (id INTEGER PRIMARY KEY, name TEXT)")
    connection.executemany("INSERT INTO people VALUES (?, ?, ?)",
                           [(1, "Ada", 10), (2, "Bo", None)])
    connection.execute("INSERT INTO companies VALUES (10, 'Example Co')")
    mapping = tmp_path / "mapping.ttl"
    mapping.write_text(MAPPING, encoding="utf-8")
    return connection, mapping


def test_r2rml_virtual_sparql_joins_live_rows_without_graph_copy(tmp_path):
    connection, mapping = _fixture(tmp_path)
    graph = R2RMLVirtualGraph(mapping, connection)
    result = list(graph.sparql("""PREFIX ex: <https://example.org/>
        SELECT ?person ?company WHERE {
          ?person ex:worksFor ?company .
          ?person ex:name "Ada" .
        }"""))
    assert result == [(URIRef("https://example.org/person/1"),
                       URIRef("https://example.org/company/10"))]
    connection.execute("UPDATE people SET name = 'Adele' WHERE id = 1")
    assert not list(graph.sparql('SELECT ?s WHERE { ?s <https://example.org/name> "Ada" }'))
    assert list(graph.sparql('SELECT ?s WHERE { ?s <https://example.org/name> "Adele" }'))


def test_same_mapping_exports_standard_rdf_for_neo4j(tmp_path):
    connection, mapping = _fixture(tmp_path)
    graph = R2RMLVirtualGraph(mapping, connection)
    rdf = graph.export_rdf("nt")
    assert '<https://example.org/person/1> <https://example.org/worksFor> <https://example.org/company/10> .' in rdf
    assert '<https://example.org/person/1> <https://example.org/name> "Ada" .' in rdf
    independent = Graph().parse(data=rdf, format="nt")
    assert (URIRef("https://example.org/person/1"),
            URIRef("https://example.org/worksFor"),
            URIRef("https://example.org/company/10")) in independent
    assert graph.graph.value(URIRef("https://example.org/person/1"),
                             URIRef("https://example.org/name")) == Literal("Ada")


def test_rejects_unimplemented_mapping_instead_of_silently_dropping_it(tmp_path):
    connection, mapping = _fixture(tmp_path)
    mapping.write_text(MAPPING.replace('rr:tableName "people"',
                                      'rr:sqlQuery "SELECT * FROM people"'), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported"):
        R2RMLVirtualGraph(mapping, connection)


def test_null_join_and_iri_escape(tmp_path):
    connection, mapping = _fixture(tmp_path)
    connection.execute("INSERT INTO people VALUES (3, 'A / B', NULL)")
    graph = R2RMLVirtualGraph(mapping, connection)
    assert (URIRef("https://example.org/person/3"),
            URIRef("https://example.org/name"), Literal("A / B")) in graph.graph
    assert not list(graph.sparql("""SELECT ?company WHERE {
      <https://example.org/person/3> <https://example.org/worksFor> ?company
    }"""))


def test_rejects_unsafe_identifier_and_unhandled_predicate_map(tmp_path):
    connection, mapping = _fixture(tmp_path)
    mapping.write_text(MAPPING.replace('rr:tableName "people"',
                                      'rr:tableName "people; DROP TABLE companies"'),
                       encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe SQL identifier"):
        R2RMLVirtualGraph(mapping, connection)
    assert connection.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 1

    mapping.write_text(MAPPING.replace('rr:predicate ex:name',
                                      'rr:predicateMap [ rr:constant ex:name ]'),
                       encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported"):
        R2RMLVirtualGraph(mapping, connection)


def test_query_pushes_bound_subject_into_sql(tmp_path):
    connection, mapping = _fixture(tmp_path)
    statements = []
    connection.set_trace_callback(statements.append)
    graph = R2RMLVirtualGraph(mapping, connection)
    list(graph.sparql("""SELECT ?name WHERE {
      <https://example.org/person/1> <https://example.org/name> ?name
    }"""))
    assert any('"id" = ' in sql for sql in statements)


@pytest.mark.parametrize("dialect", ["snowflake", "bigquery", "databricks"])
def test_dbapi_dialects_emit_safe_selects_and_bind_values(tmp_path, dialect):
    base, mapping = _fixture(tmp_path)
    statements = []

    class Cursor:
        def __init__(self):
            self.inner = base.cursor()

        def execute(self, sql, params):
            statements.append((sql, params))
            self.inner.execute(sql.replace("%s", "?").replace("`", '"'), params)

        def fetchmany(self, size):
            return self.inner.fetchmany(size)

        def close(self):
            self.inner.close()

    class Connection:
        def cursor(self):
            return Cursor()

    graph = R2RMLVirtualGraph(mapping, Connection(), dialect=dialect)
    assert list(graph.sparql("""SELECT ?name WHERE {
      <https://example.org/person/1> <https://example.org/name> ?name
    }"""))
    assert all(sql.startswith("SELECT ") for sql, _ in statements)
    assert any(params == ("1",) for _, params in statements)
    assert any(("%s" if dialect == "snowflake" else "?") in sql
               for sql, _ in statements)
