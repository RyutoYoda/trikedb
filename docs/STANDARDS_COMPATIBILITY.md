# RDF and W3C compatibility

TrikeDB has a curated YAML graph and a separate read-only relational RDF
view. Standard RDF terms can be exported from both, but support for one
standard does not imply support for every construct in another.

| Standard | Current scope |
| --- | --- |
| [RDF 1.1](https://www.w3.org/TR/rdf11-concepts/) and [Turtle](https://www.w3.org/TR/turtle/) | RDF interchange and SPARQL terms; the curated YAML format is TrikeDB's own compact syntax. |
| [SPARQL 1.1 Query](https://www.w3.org/TR/sparql11-query/) | Curated graphs use Oxigraph. Virtual relational graphs use RDFLib with a narrow SQL pushdown for same-subject basic graph patterns. |
| [R2RML](https://www.w3.org/TR/r2rml/) | Strict subset for virtual relational views. Supported: `rr:tableName`, subject IRI templates, `rr:class`, constant predicates, object columns/templates/constants, and parent triples map joins with `rr:joinCondition`. Unsupported mapping properties are rejected. No full-conformance claim. |
| [Direct Mapping](https://www.w3.org/TR/rdb-direct-mapping/) | Not implemented. This is a separate automatic RDB-to-RDF mapping standard. |
| [SHACL](https://www.w3.org/TR/shacl/) | Optional shape validation for curated graphs; not inferred from relational schemas. |
| [PROV-O](https://www.w3.org/TR/prov-o/) | Can be represented with explicit IRIs. TrikeDB-specific provenance and event fields are not automatically converted into PROV-O activities or agents. |
| [SKOS](https://www.w3.org/TR/skos-reference/), [DCAT](https://www.w3.org/TR/vocab-dcat-3/), [OWL-Time](https://www.w3.org/TR/owl-time/) | Usable as explicit RDF vocabularies; TrikeDB does not infer them from arbitrary YAML fields. |

P-Plan is a community ontology for plans and steps, not a W3C Recommendation.
TrikeDB projects declared workflows to its current `isPrecededBy` vocabulary
in RDF output; this does not turn step execution into a PROV-O activity by
itself.

## R2RML gaps

The virtual view has not passed the [W3C R2RML test
cases](https://www.w3.org/TR/rdb2rdf-test-cases/). Known unsupported areas
include `rr:sqlQuery` and SQL views, shortcut subject/predicate/object/graph
forms, predicate and graph term maps, named graphs, blank-node subjects,
`rr:inverseExpression`, IRI-valued column maps, and the full SQL-to-RDF
datatype conversion rules. Some supported constructs may still have edge
cases; passing the official test suite is the gate for claiming conformance.

SPARQL-to-SQL query optimization is a separate implementation concern. This
release combines one eligible same-subject basic graph pattern into one SQL
statement. It does not optimize every SPARQL query, expose a [SPARQL
Protocol](https://www.w3.org/TR/sparql11-protocol/) endpoint for the virtual
view, or implement [SPARQL Federated
Query](https://www.w3.org/TR/sparql11-federated-query/).
