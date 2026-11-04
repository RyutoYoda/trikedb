# TrikeDB 1.0 release gates

The 1.0 label means a stable contract for a small, curated, single-document
knowledge graph. It does not imply a distributed RDF dataset server or
unbounded scale. Do not bump the version until every gate below has evidence.

| Gate | Evidence required | Current state |
|---|---|---|
| File/API compatibility | Frozen YAML and Python API examples; round-trip fixtures across the last supported release and 1.0 | Open |
| RDF interoperability | Turtle, N-Triples and JSON-LD round trips checked by an independent RDF parser, including IRIs, literals, language tags, blank nodes and metadata | Partial; existing regression tests cover the projection |
| SHACL behavior | Standard Turtle shapes and reports compared with pySHACL on valid and invalid fixtures | Partial; adapter and tests exist, conformance corpus pending |
| Safe local edits | Two processes cannot silently overwrite each other; MCP/REST see external local edits; malformed reload never turns into an empty graph | Implemented in the local concurrency change; CI and cross-platform checks pending |
| Manual YAML validation | A documented strict load/check mode rejects undeclared or contradictory facts without preventing repair of historical files | Implemented as opt-in `validate_on_load` plus audit; CI pending |
| Remote safety | S3 and SQL conflict tests; explicit limitations for other remote backends; live integration evidence where credentials exist | Partial |
| Offline graph export | A private graph can be opened without CDN requests; browser smoke checks the exported file offline | Implemented with bundled assets and browser smoke; CI pending |
| Release provenance | CI for supported Python versions, typed package marker, signed or otherwise verifiable release artifact, GitHub release notes and PyPI publishing without a long-lived token | Partial; issue #3 |
| Scale and adoption | Published performance envelope and at least one independent installation/use report | Partial; measured envelope exists, independent use pending |

The gates are release criteria, not a reason to publish an intermediate package
after each fix. Merge compatible improvements into `main`, then perform one
versioned release after the complete gate review.
