# Architecture

## The whole thing, in one picture

```mermaid
flowchart TB
    LA["<b>LAYER 1</b><br/>Interface — writing"]
    LG[" "]
    LB["<b>LAYER 2</b><br/>Core — exactly one"]
    LC["<b>LAYER 3</b><br/>Storage — pick exactly one"]
    LD["<b>LAYER 4</b><br/>Projection — never stored"]
    LE["<b>LAYER 1</b><br/>Interface — reading"]
    LA ~~~ LG ~~~ LB ~~~ LC ~~~ LD ~~~ LE

    WA("agent<br/>MCP")
    WC("person<br/>CLI · editor")
    WI("bulk import<br/>CSV · Markdown · YAML")
    WP("program<br/>Python")
    WU("program<br/>SPARQL UPDATE")
    G{{"the ontology guard — every write passes here<br/>an undeclared predicate never lands"}}
    C("<b>ONE document</b><br/>triples · nodes · ontology")
    SF("file<br/>graph.yaml · graph.json")
    SO("object<br/>s3:// · gs:// · az://")
    SW("table row<br/>snowflake:// · bigquery://")
    PO("oxigraph<br/>runs SPARQL")
    PR("rdflib.Graph<br/>owlrl · pyshacl · exports")
    PN("networkx<br/>graph algorithms")
    PV("SQL views<br/>over the warehouse row")
    PD("no engine at all<br/>the document as JSON")
    RA("agent<br/>MCP")
    RP("app<br/>REST · Python")
    RG("program<br/>Python")
    RS("SQL<br/>BI · dbt · notebook")
    RH("person<br/>HTML workbench")

    WA --> G
    WC --> G
    WI --> G
    WP --> G
    WU --> G
    G --> C
    C <--> SF
    C <--> SO
    C <--> SW
    SF ~~~ PO
    SF ~~~ PR
    SO ~~~ PN
    SW -.-> PV
    SW ~~~ PD
    C -.-> PO
    C -.-> PR
    C -.-> PN
    C -.-> PD
    PO --> RA
    PR --> RP
    PN --> RG
    PV --> RS
    PD --> RH

    classDef lbl fill:none,stroke:none,color:#8b8b8b
    classDef iface fill:#1f2937,stroke:#6b7280,color:#e5e7eb,rx:10,ry:10
    classDef core fill:#312e2b,stroke:#a16207,color:#fef3c7,rx:10,ry:10
    classDef store fill:#1e2b2b,stroke:#0e7490,color:#cffafe,rx:10,ry:10
    classDef proj fill:#2a2135,stroke:#7c3aed,color:#ede9fe,rx:10,ry:10
    class LA,LG,LB,LC,LD,LE lbl
    class WA,WC,WI,WP,WU,RA,RP,RG,RS,RH iface
    class C,G core
    class SF,SO,SW store
    class PO,PR,PN,PV,PD proj
```






Read it top to bottom: each row is one layer, colour-coded, with the layer's
name on the left. Solid arrows move bytes; dotted arrows are *derived* — built
on demand from the document and thrown away. Read a column downward and you
have one real path end to end: `oxigraph → agent over MCP`,
`SQL views → dbt`, `no engine at all → the HTML workbench`.

**Four layers, and layer 1 is the bread on both ends** — the same interface
layer, writing on the way in and reading on the way out. The core between them
is single. Storage and projection are sets you choose from.

| Layer | How many | Owns | Does *not* own |
|---|---|---|---|
| **1 · Interface** | one per medium | translating CLI / MCP / REST / HTML into core calls | any graph logic |
| **2 · Core** | **exactly one** | the document, the guard, and what the graph *means* | where bytes go, how queries run |
| **3 · Storage** | **pick one** | which destination, and the conditional write protecting it | anything about meaning |
| **4 · Projection** | **pick any** | views of the same statements — RDF, property graph, SQL | storing anything |

Two things about that stack are worth saying out loud, because both are
choices and not omissions.

**There is no separate metadata layer.** The ontology is not a registry
beside the data; it is a key of the same document as the triples. So a change
to the vocabulary and a change to the facts land in the same diff, and there
is nothing to keep in sync. A system that puts meaning in a layer above the
data gets to change it without touching the data — that is the better trade
when the data is too large to move, and the worse one when you want the whole
change reviewable at once.

**There is no query layer that owns state.** Layer 4 is built from layer 2 on
demand and thrown away. That is what makes two SPARQL engines possible at all
and why nothing can drift between them.

This document is about *why* it is shaped that way. For the API see
[REFERENCE.md](REFERENCE.md); for measurements see
[benchmarks/](../benchmarks/README.md).

## One decision, and everything that follows from it

**The layer below the core moves one whole document at a time.** Not a row,
not a delta, not a page — the entire graph, in and out, as text.

```
storage:  read_text · write_text · exists · version
                    ↑
          one document. always.
```

Nearly every property trikedb has, good and bad, is a consequence of that
one line:

- **The destination becomes swappable.** Anywhere that can hold one document
  can hold a graph — a file on disk, an object in a bucket, a row in a
  warehouse. Nothing above the storage layer learns which one it got.
- **Concurrency control becomes whole-document compare-and-swap.** There is
  no row locking to design because there are no rows; a save either replaces
  the document it read or is refused. Simple, and it means there is no
  partial write either.
- **The ceiling is a few MB.** Adding one fact rewrites everything. That is
  not a bug to fix later; it is the same decision, seen from the other side.

Being able to name the trade in one sentence is the point. A design where the
flexibility and the limit come from *different* places is a design where you
can't predict either.

The claim was tested rather than asserted: adding a backend that is not a
filesystem at all — a graph as a row in a SQL table, with network round trips
and a real transaction model — required no change to SPARQL, the MCP tools,
SHACL, OWL inference, `to_networkx`, or the CLI. `storage.py` and one new
module, and nothing else moved.

## Projection, not translation

A graph has many useful shapes. trikedb stores **one** and derives the rest:

```
_statements()          ← the single source of truth for what the graph MEANS
      ├─→ rdflib graph        (the RDF view — exports, OWL, SHACL, updates)
      ├─→ oxigraph store      (the same RDF view, for fast reads)
      ├─→ networkx graph      (the property-graph view — algorithms)
      └─→ SQL views           (the table view — whatever else reads SQL)
```

None of those is stored. They are projections, built on demand from the same
generator, which decides the things that are easy to get subtly wrong: which
objects are URIs and which are literals, how edge attributes reify, which node
properties surface.

That matters because the failure mode of duplicating those rules is the worst
kind. Two engines answering *differently* about the same graph both look
plausible; nothing raises. Keeping one source of truth makes that impossible
by construction rather than by discipline — and it is why a second SPARQL
engine could be introduced at all. (25 of 26 SPARQL forms then agreed
exactly; the 26th was a case the spec leaves undefined. See
`test_engines_agree_across_the_sparql_surface`.)

The same principle draws the line for new features: **a new way to look at the
graph is a projection; it does not get to add a second copy of the data.**

## The guard is at the write boundary

The ontology — a whitelist of predicates — is enforced when a fact is
*written*, not when it is read or in a later linting pass. Every write path
goes through it: the Python API, the CLI, CSV/Markdown import, SPARQL
`INSERT`, the MCP tools an agent calls, OWL materialization, and a person
editing the file by hand.

The consequence is the reason for the design: **"an agent wrote it" and "a
human wrote it" cannot diverge in vocabulary.** An agent cannot invent a
predicate, because the invented predicate never lands. Checking after the
fact would report the problem; checking at the boundary means there is no
problem to report.

This is the trade in the other direction from a schema-on-read system, which
accepts anything and applies meaning later. That is the better choice when you
are putting meaning on top of data you did not write. This is the better one
when the writer is a language model.

## Different features have different ceilings

A single number for "how big can it get" would be misleading, because the
features do not degrade together. Semantic search becomes unusable while
SPARQL over the same graph is still answering in milliseconds; the workbench
export gets unwieldy long before storage does.

This is a design fact, not an accident of tuning: each capability has a
different relationship to graph size. Search re-embeds everything per query
(deliberately index-free, so results can never drift from the file). SPARQL
runs against a built index. Save rewrites the document.

So the honest answer to "how large" is per-feature, and it is measured rather
than estimated — see
[benchmarks: where is the ceiling](../benchmarks/README.md#where-is-the-ceiling).
The one thing that does *not* degrade is the diff: a one-fact change is one
line at any size, which is what keeps review possible even when reading the
whole graph is not.

## Where does everything actually live?

Three questions people ask in this order, so they are answered in that order:
what is *stored*, where the *meaning* is kept, and what *executes a query*.

```yaml
# one file, three keys — this is the whole storage format
ontology:                       # the meaning: which predicates may exist
  predicates:
    PROVIDES: "vendor -> job"

nodes:                          # what is known about an entity itself
  crm-sync-job: {type: job, owner: data-platform}

triples:                        # the facts, with attributes on the edge
  - {s: salesflow, p: PROVIDES, o: crm-sync-job, prov: runbook.md}
```

**Data and metadata are the same document.** The ontology is not a schema
registry, the node properties are not a side table: `triples`, `nodes` and
`ontology` are three keys of one YAML/JSON document, saved and loaded
together. That is why a change to the vocabulary and a change to the facts
arrive in the *same* diff, and why there is no migration step when either
moves.

**The backend decides nothing except where those bytes sit.** Opening and
saving differ; everything after that is identical, because the graph is
answered from memory. A `snowflake://` row and a local file give the same
answer to the same query in the same time — measured, see
[benchmarks](../benchmarks/README.md#where-is-the-ceiling).

| | Where the document is | What changes |
|---|---|---|
| `graph.yaml` | a file on disk | reviewable in a diff; slowest to open |
| `graph.json` | a file on disk | ~17x faster to open; a diff nobody enjoys |
| `s3://` `gs://` `az://` | an object in a bucket | shared, and S3 gets conditional writes |
| `snowflake://` `bigquery://` | one row of one table | shared, conditional writes, **and readable by SQL** |

Only the last row adds a genuinely new capability: the document is stored as
JSON, and `sql-init` creates views (`KG_NODE`, `KG_EDGE`, `KG_PREDICATE`,
`KG_TRIPLE`) that project it as ordinary tables. So the same graph answers
SPARQL from memory and SQL from the warehouse, with no second copy.

## Which engine does what

The most common question about the internals, because there are two RDF
engines and they are not interchangeable.

The split is **not** read versus write — that was a mislabel, and it confuses
more than it explains. `validate()` and `to_rdflib()` write nothing;
`infer(apply=False)` writes nothing either. The real question is what the
operation *needs*:

```mermaid
flowchart LR
    ST["_statements()<br/>the one source of<br/>what the graph means"]

    subgraph q["needs a query run, fast"]
        OX["oxigraph<br/>Rust, real indexes"]
    end
    subgraph o["needs an rdflib.Graph<br/>object to hand somewhere"]
        RD["rdflib<br/>→ owlrl · pyshacl · serializers"]
    end
    subgraph plain["needs neither"]
        PP["pure Python<br/>dict + list"]
    end

    ST --> OX
    ST --> RD
    ST --> PP
```

`owlrl` and `pyshacl` are third-party libraries whose API takes an
`rdflib.Graph`. `to_rdflib()` and `to_jsonld()` are exports where rdflib *is*
the format. And `update()` runs the SPARQL update on an rdflib graph and then
diffs the result back onto the store — it needs the object, not just an
answer. None of that is something a query engine can do for us, which is why
rdflib stays no matter how fast the alternative gets.

| Operation | Engine | Changes the graph? | Why that engine |
|---|---|---|---|
| `sparql()` — SELECT, ASK | **oxigraph** | no | only an answer is needed, and it is 6–40x faster |
| `sparql()` — INSERT, DELETE | rdflib | **yes** | runs the update on a graph, then diffs it back |
| `infer()` — OWL-RL | rdflib | only with `apply=True` | `owlrl` takes an `rdflib.Graph` |
| `validate()` — SHACL | rdflib | no | `pyshacl` takes an `rdflib.Graph` |
| `to_rdflib()`, `to_jsonld()` | rdflib | no | exports; rdflib *is* the format |
| `triples()`, `query()` | none | no | pattern matching over a Python list |
| `search()`, `find()` | none | no | static embeddings; no SPARQL involved |
| `to_networkx()` | none | no | a projection into networkx objects |

Only one row in that table writes. Grouping the rest as "writes" was simply
wrong.

Two things worth knowing about that split.

**Nothing was removed when oxigraph arrived.** OWL and SHACL never went
through the query path — they take rdflib graphs from `to_rdflib()`, which is
untouched. Verified rather than assumed: both engines produce identical
inference and identical SHACL verdicts
(`test_engines_agree_across_the_sparql_surface` covers 25 SPARQL forms; the
26th is a case the spec leaves undefined).

**Inference happens at write time, not query time.** `infer(apply=True)` runs
OWL-RL and writes the derived facts into the document, tagged
`inferred: true`. After that they are ordinary triples, and the query engine
never reasons about anything. That is why swapping the engine could not cost
any inference accuracy — and it is also the trade: materialised facts are a
snapshot, so adding a fact that would imply more means running `infer()`
again. Reviewability was chosen over automatic freshness.

Both stay core dependencies for that reason: rdflib because `owlrl` and
`pyshacl` need it and updates diff through it, pyoxigraph because it was
faster at every graph size measured. Where pyoxigraph is unavailable — a
curated package channel, a vendored subset of the files — reads fall back to
rdflib and everything keeps working, slower.


## The layers

Dependencies point inward only.

```mermaid
flowchart LR
    subgraph adapters["Interface adapters"]
        direction TB
        CLI("cli.py<br/>18 subcommands")
        MCP("mcp_server.py<br/>11 MCP tools")
        SERVE("serve.py<br/>UI + REST + remote MCP")
        HTML("html.py<br/>workbench export")
        IMP("importers.py<br/>CSV / Markdown")
    end

    CORE("db.py — core<br/>Triple + TrikeDB + _statements")

    subgraph ext["Extensions (lazy, optional deps)"]
        direction TB
        SEM("semantics.py<br/>OWL · SHACL")
        EMB("semantic.py<br/>embedding search")
        AUD("audit.py<br/>health findings")
    end

    STORE("storage.py<br/>read_text · write_text · version<br/>one whole document at a time")

    subgraph backends["Backends — a graph lives in exactly one"]
        direction TB
        LOCAL("pathlib<br/>graph.yaml · graph.json")
        FS("fsspec<br/>s3:// gs:// az:// https://")
        SQL("storage_sql.py<br/>snowflake:// · bigquery://<br/>a graph is a row in a table")
    end

    SERVE --> MCP
    CLI --> CORE
    MCP --> CORE
    SERVE --> CORE
    HTML --> CORE
    IMP --> CORE
    CORE --> STORE
    STORE -->|"a path"| LOCAL
    STORE -->|"an object URL"| FS
    STORE -->|"a warehouse URL"| SQL
    CORE -.-> SEM
    CORE -.-> EMB
    CORE -.-> AUD
```

`storage.py` dispatches on the URL scheme and **exactly one branch runs**.
A warehouse graph never touches fsspec; an object-storage graph never opens a
database connection. They are alternatives, not a pipeline, and nothing is
stored twice.

- **`db.py` — core.** The `Triple` model and the `TrikeDB` store: CRUD with
  ontology enforcement, pattern matching, SPARQL, workspace unions, and
  `_statements()` — the projection source above. It also decides *which
  engine* answers a read and *which serialization* a destination wants;
  see "Which engine does what". Depends only on `storage` and (lazily)
  `semantics`. No HTTP, no CLI, no HTML in here, ever.
- **`storage.py` — the interface and its dispatcher.** Anything about *where
  bytes live* — new schemes, optimistic locking, caching, which
  serialization a destination wants — belongs here and nowhere else.
- **`storage_sql.py` — the same interface over a SQL table.** A database is
  not a filesystem, so it does not reach fsspec: a graph is a row
  (`name`, `doc`, `version`, `updated_at`), and one table holds many graphs,
  so adopting trikedb costs an organisation one table rather than one per
  graph. Two engines are implemented — `snowflake://` and `bigquery://` —
  and everything either does differently lives in a `_Dialect`, which is
  *data*:

  | | Snowflake | BigQuery |
  |---|---|---|
  | opening JSON | `TRY_PARSE_JSON` + `LATERAL FLATTEN` | `SAFE.PARSE_JSON` + `JSON_QUERY_ARRAY` + `UNNEST` |
  | parameters | positional `%s` | named `%(name)s` |
  | identifiers | `A-Za-z0-9_$`, unquoted | hyphens allowed, backtick-quoted |
  | hashing | `MD5(...)` | `TO_HEX(MD5(...))` |

  Adding BigQuery cost one `_Dialect` literal plus three things the shared
  code had assumed were universal — one identifier rule, one place to quote,
  and one parameter order. All three failed *silently* rather than raising,
  which is why they are the interesting part of that changelog.

  Two things land more cleanly here than on object storage. Optimistic
  locking goes inside the statement (`UPDATE ... WHERE version = ?`), so a
  conflict is an affected-row count of zero rather than an error message to
  pattern-match — verified identical on both engines. And the document can be
  *read by other tools*: stored as JSON, four views project it as ordinary
  tables (`KG_NODE`, `KG_EDGE`, `KG_PREDICATE`, `KG_TRIPLE`), so anything
  that speaks SQL can query the graph without knowing trikedb exists.

  The trade to know: a database typically serialises writes per *table*, where
  object storage serialises per object. One table holding many graphs means
  writers to unrelated graphs still queue behind each other. Harmless at the
  rate a person or an agent edits a graph; it does mean a more generous retry
  budget than object storage needs.
- **`semantics.py` — optional semantic layers.** OWL declarations and OWL-RL
  materialization, SHACL validation. Imported lazily; the core stays useful
  without them and failures name the extra to install.
- **`semantic.py` — optional embedding search.** Index-free on purpose: the
  whole graph is re-embedded per query, so a result can never disagree with
  the file. That choice is also the reason search has the earliest ceiling —
  a legible cost rather than a hidden one.
- **Interface adapters** — each a thin translation of the core API into one
  medium; none contains graph logic:
  - `cli.py`: argparse commands, one `_cmd_*` per subcommand.
  - `mcp_server.py`: the FastMCP server definition. Transport is the caller's
    choice — stdio and Streamable HTTP share this one definition.
  - `serve.py`: the HTTP composition — workbench UI, `/sparql` REST, the
    mounted MCP app, wrapped in auth.
  - `html.py`: the self-contained workbench page, generated from graph data.
  - `importers.py`: deterministic CSV/TSV/Markdown-table ingestion.

## Rules of thumb for changes

- **`storage.py` must stay importable on its own.** trikedb gets vendored as a
  subset of its files into hosts that cannot install packages, so
  `db.py` + `storage.py` + `__init__.py` has to be a working install. Only a
  warehouse URL may reach for `storage_sql` — which is why the SQL schemes are
  *named* in `storage.py` rather than imported from it. This has been broken
  once by an unconditional import; it turned "open a local file" into an
  ImportError.
- **New way to *store* a graph** → `storage.py` (a filesystem-shaped backend)
  or a `_Dialect` in `storage_sql.py` (a table-shaped one). Never above those
  two files.
- **New way to *look at* a graph** → a projection over `_statements()`. If it
  needs its own copy of the data, that is the signal to stop and reconsider.
- **New *reasoning or validation*** → `semantics.py`, exposed as a delegating
  method, behind an optional extra.
- **New way to *talk to* a graph** (protocol, format, UI) → a new adapter
  module plus a CLI subcommand. Never import one adapter from another;
  compose them in a `serve.py`-style module.
- **Anything an agent can do must exist in all three interfaces** — Python
  API, CLI, MCP. Parity is a feature, not a coincidence.
- **A cache is a correctness problem before it is a speed problem.** Two live
  here: the built query graph and the `(s, p, o)` index behind `add()`. Both
  fail *silently* when stale — answering from a graph that moved, or deciding
  a triple already exists and dropping the write. So invalidation is
  deliberately over-eager, and every path that replaces the triple list
  clears them explicitly. A length check is a backstop, never the mechanism:
  two different lists can be the same length.
- **Heavy dependencies are optional extras.** The core is PyYAML, rdflib and
  pyoxigraph. pyoxigraph earned it by being faster at every graph size
  measured, down to a few hundred triples; rdflib stays because `owlrl` and
  `pyshacl` take rdflib graphs and updates diff through one.
- **Claims about behaviour get a test; claims about speed get a benchmark.**
  Both of those directories exist so that a sentence in a README can be
  checked rather than believed.
