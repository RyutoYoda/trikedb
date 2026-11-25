# RDF and W3C compatibility

TrikeDB has a curated YAML graph and a separate read-only relational RDF
view. Standard RDF terms can be exported from both, but support for one
standard does not imply support for every construct in another.

| Standard | Current scope |
| --- | --- |
| [RDF 1.1](https://www.w3.org/TR/rdf11-concepts/) and [Turtle](https://www.w3.org/TR/turtle/) | RDF interchange and SPARQL terms; the curated YAML format is TrikeDB's own compact syntax. |
| [SPARQL 1.1 Query](https://www.w3.org/TR/sparql11-query/) | Curated graphs use Oxigraph. Virtual relational graphs use RDFLib with a narrow SQL pushdown for same-subject basic graph patterns. |
| [R2RML](https://www.w3.org/TR/r2rml/) | The virtual relational view passes all 63 R2RML cases in the pinned W3C test suite on SQLite, including negative cases. It supports SQL views, shortcut maps, term maps, named graphs, blank nodes, joins, and tested SQL-to-RDF conversions. This is a tested compatibility claim, not a guarantee for every SQL backend or untested edge case. |
| [Direct Mapping](https://www.w3.org/TR/rdb-direct-mapping/) | Not implemented. This is a separate automatic RDB-to-RDF mapping standard. |
| [SHACL](https://www.w3.org/TR/shacl/) | Optional shape validation for curated graphs; not inferred from relational schemas. |
| [PROV-O](https://www.w3.org/TR/prov-o/) | Can be represented with explicit IRIs. TrikeDB-specific provenance and event fields are not automatically converted into PROV-O activities or agents. |
| [SKOS](https://www.w3.org/TR/skos-reference/), [DCAT](https://www.w3.org/TR/vocab-dcat-3/), [OWL-Time](https://www.w3.org/TR/owl-time/) | Usable as explicit RDF vocabularies; TrikeDB does not infer them from arbitrary YAML fields. |

P-Plan is a community ontology for plans and steps, not a W3C Recommendation.
TrikeDB projects declared workflows to its current `isPrecededBy` vocabulary
in RDF output; this does not turn step execution into a PROV-O activity by
itself.

## R2RML test coverage and limits

CI downloads the [W3C RDB2RDF test suite](https://www.w3.org/TR/rdb2rdf-test-cases/)
from a pinned archive, verifies its SHA-256, and compares the generated RDF
dataset including named graphs and blank-node isomorphism. All 63 R2RML
cases pass with SQLite. The suite is a W3C Working Group Note, not a formal
certification program. It does not cover every valid R2RML mapping, all SQL
2008 behavior, or every connector. In particular, schema-qualified table
names and non-SQLite datatype behavior need backend-specific testing.

`rr:inverseExpression` is accepted as optimization metadata; TrikeDB does
not use it to reverse-map terms into SQL filters. The `rr:sqlQuery` path
currently requires a single `SELECT` statement that the connected database
accepts. Nontrivial virtual queries and RDF exports can scan full source
tables, including the parent side of referencing-object-map joins.

SPARQL-to-SQL query optimization is a separate implementation concern. This
release combines one eligible same-subject basic graph pattern into one SQL
statement. It does not optimize every SPARQL query, expose a [SPARQL
Protocol](https://www.w3.org/TR/sparql11-protocol/) endpoint for the virtual
view, or implement [SPARQL Federated
Query](https://www.w3.org/TR/sparql11-federated-query/).
