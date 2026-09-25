<!-- Two failures with the same wording on different dates are two records,
     not one: a scorer that dedupes on (s, p, o) would score the right
     answer as a duplicate. "The ingest job" is `ingest` in the graph.
     "We should size the pool properly" is not a fact about anything.
     The 2024 ownership move has no predicate for a past owner, and
     OWNED_BY is functional, so re-stating current ownership is the only
     ownership row — and it is already in the graph. -->

| s | p | o | at | prov |
|---|---|---|---|---|
| ingest | AFFECTED_BY | failed overnight | 2026-03-04 | The ingest job failed overnight |
| ingest | AFFECTED_BY | failed overnight | 2026-09-04 | failed overnight again, same cause |
| ingest | DEPENDS_ON | warehouse |  | the job cannot run without the warehouse |
| ingest | OWNED_BY | platform |  | The ingest job is owned by Platform |
