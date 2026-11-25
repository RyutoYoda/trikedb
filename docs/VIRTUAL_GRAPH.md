# Virtual RDF graph over relational data

TrikeDB keeps its YAML graph for curated facts and workflows. For large rows
already held in a relational database or warehouse, use a separate virtual
RDF view: R2RML describes how table rows become RDF terms, while queries read
the source tables at request time. No row data is copied into the YAML graph
or into a warehouse graph-document row. Curated graphs and R2RML mappings
remain reviewable files.

The mapping is standard [W3C R2RML](https://www.w3.org/TR/r2rml/) Turtle,
not a TrikeDB-specific relational-mapping dialect. The SQLite implementation
passes all 63 R2RML cases in the pinned W3C suite. It supports base tables,
`rr:sqlQuery` views, subject/predicate/object/graph maps and shortcuts,
named graphs, blank nodes, classes, and parent-map joins. The suite does not
cover every SQL dialect or mapping edge case; see
[standards compatibility](STANDARDS_COMPATIBILITY.md).

## Example

The same mapping works with any DB-API source that exposes the **same logical
table and column names**. Connector credentials remain outside the mapping.

```turtle
@prefix rr: <http://www.w3.org/ns/r2rml#> .
@prefix ex: <https://example.org/> .

<#Order> a rr:TriplesMap ;
  rr:logicalTable [ rr:tableName "orders" ] ;
  rr:subjectMap [ rr:template "https://example.org/order/{id}" ; rr:class ex:Order ] ;
  rr:predicateObjectMap [
    rr:predicate ex:status ;
    rr:objectMap [ rr:column "status" ]
  ] .
```

```python
import sqlite3
from trikedb import R2RMLVirtualGraph

connection = sqlite3.connect("example.sqlite")
view = R2RMLVirtualGraph("orders.ttl", connection)
rows = view.sparql("""SELECT ?order WHERE {
  ?order <https://example.org/status> "approved"
}""")
for row in rows:
    print(row.order)

# A snapshot for another RDF system, including Neo4j n10s on supported
# self-managed editions. This export is explicit and can be large.
open("orders.nt", "w", encoding="utf-8").write(view.export_rdf("nt"))

# Preserve named graphs with view.export_rdf("nquads") when the mapping
# includes rr:graph or rr:graphMap.
```

Pass an already authenticated, **read-only** DB-API connection and set
`dialect="snowflake"`, `"bigquery"`, or `"databricks"` as appropriate.
The default binding marker is `%s` for the Snowflake Python connector and `?`
for BigQuery and Databricks connectors. Set `placeholder` explicitly when
your connector uses a different binding style. Pass `base_iri=` when the
mapping generates relative IRIs and needs a base other than its Turtle
`@base`; R2RML concatenates this base with the generated value. Table names must be trusted
and match the database's case-sensitive quoted identifiers. In particular,
Snowflake mappings should use uppercase names for unquoted tables.

For BigQuery, use `google.cloud.bigquery.dbapi.Connection` with an already
authenticated client. The mapping's `rr:tableName` can be a fully qualified
`project.dataset.table` name; no BigQuery graph-document table is created.

```python
from google.cloud import bigquery
from google.cloud.bigquery import dbapi
from trikedb import R2RMLVirtualGraph

client = bigquery.Client()  # configure credentials outside the mapping
connection = dbapi.Connection(client=client, prefer_bqstorage_client=False)
view = R2RMLVirtualGraph("mapping.ttl", connection, dialect="bigquery")
```

Queries are virtual. A bare `SELECT` or `ASK` basic graph pattern with one
subject, constant predicates, and exactly one eligible triples map compiles
to one SQL `SELECT`. The SQL joins the needed source rows and parent maps;
bound subjects and plain string literals become parameters. Rows that map to
the same RDF subject are joined by the subject template columns, so RDF graph
joins do not require both facts to come from the same table row. Other SPARQL
shapes, cross-map joins, `FILTER`, `OPTIONAL`, `UNION`, and aggregates use
RDFLib over the virtual store. This is **not** a general SPARQL-to-SQL
optimizer. Full-graph queries and RDF export may read entire tables. Apply
source access control and use selective query patterns for large tables.

R2RML defines *mapping semantics*, not a required SPARQL-to-SQL optimizer.
See [standards compatibility](STANDARDS_COMPATIBILITY.md) for test coverage,
SQL-backend limits, and the separate query standards.

An N-Triples export is a portable RDF interchange artifact. Neo4j's n10s can
import RDF in supported self-managed deployments; Neo4j Aura needs a separate
property-graph import path. RDF and Neo4j property-graph models also differ,
so one mapping does not automatically guarantee identical labels, properties,
and relationship identities in both systems.

Curated definitions stay in files; relational rows are read from the source.
