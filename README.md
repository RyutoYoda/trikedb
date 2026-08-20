<p align="center">
  <img src="https://raw.githubusercontent.com/RyutoYoda/trikedb/main/docs/logo.png" width="260" alt="TrikeDB — a triceratops carrying a knowledge graph on its frill">
</p>

<p align="center">
  <a href="https://pypi.org/project/trikedb/"><img src="https://img.shields.io/pypi/v/trikedb?style=flat&color=4a6fa5&cacheSeconds=300" /></a>
  <img src="https://img.shields.io/pypi/pyversions/trikedb?style=flat&color=4a6fa5" />
  <img src="https://img.shields.io/badge/license-MIT-4a6fa5?style=flat" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/SPARQL%201.1-3D7EBB?style=flat&logo=w3c&logoColor=white" />
  <img src="https://img.shields.io/badge/RDF-0C479C?style=flat&logo=w3c&logoColor=white" />
  <img src="https://img.shields.io/badge/MCP-191919?style=flat&logo=modelcontextprotocol&logoColor=white" />
</p>

<p align="center">
  <b><a href="https://ryutoyoda.github.io/trikedb/">🦕 Live demo</a></b> — 600 real Freebase facts, click around, run SPARQL in the browser
  &nbsp;·&nbsp; <a href="https://ryutoyoda.github.io/trikedb/workspace.html">workspace demo</a> — the same facts as 6 domain graphs, tiled and filterable
  &nbsp;·&nbsp; <a href="https://pypi.org/project/trikedb/">PyPI</a>
</p>

# trikedb

**The single-file graph database.** You query it like a real triple store — full SPARQL 1.1, reads *and* writes. Underneath, it's one YAML file. Built for LLM agents.

```yaml
triples:
  - {s: salesflow-crm, p: PROVIDES, o: crm-sync-job}
  - {s: crm-sync-job, p: INGESTS_TO, o: RAW_CRM_CONTACTS, schedule: hourly}
  - {s: LEGACY_DUMP, p: MIGRATED_TO, o: RAW_CRM_CONTACTS, deprecated: true}
```

That file **is** the database. No server, no daemon, no cloud deployment. It diffs cleanly in git, survives in a repo next to your code, and — the part trikedb is actually designed around — **an LLM agent can `Read` it directly and reason over your domain without hallucinating entity names.**

And it renders as an interactive workbench ([live demo](https://ryutoyoda.github.io/trikedb/) — 600 real Freebase facts):

<p align="center">
  <a href="https://ryutoyoda.github.io/trikedb/">
    <img src="https://raw.githubusercontent.com/RyutoYoda/trikedb/main/docs/screenshot.png" alt="trikedb HTML workbench — 600 Freebase facts as force-directed clusters, with a node detail panel open">
  </a>
</p>

## Why

RDF graph databases are powerful, correct — and heavy. SPARQL endpoints, OWL reasoners, enterprise semantic layers: great at scale, overkill when what you need is a curated map of a few hundred facts that your AI agents (and teammates) can trust.

trikedb keeps the *interface* of the big system — real SPARQL 1.1 (rdflib's engine, not a homegrown subset) — and shrinks the *machinery* down to an embedded library over a file you can read, diff, and commit:

|  | A full triple-store deployment | trikedb |
|---|---|---|
| Storage | server / cloud service | one YAML file |
| Query | SPARQL 1.1 | SPARQL 1.1 (same language, rdflib engine) |
| Graph model | usually pick one: RDF *or* property graph (two systems) | **both from one file** — SPARQL/RDF (`to_rdflib`) and property graph (`to_networkx`, via `[networkx]`) |
| Writes | SPARQL Update | SPARQL Update — persisted back to the YAML |
| Schema | OWL + reasoners | a predicate whitelist, plus SHACL shapes via `[shacl]` |
| Inference | DL reasoning engines | OWL-RL materialization via `[owl]` — inferred facts land in the YAML, reviewable |
| Agent integration | a service to operate | the agent reads the file, `trikedb mcp` (stdio), or `trikedb serve` (remote MCP + UI + REST) |
| Setup time | an afternoon (or a sprint) | `pip install trikedb` |

If you need full OWL-DL reasoning at scale, named graphs, and multi-tenant governance, you want a full enterprise semantic platform. If you want a knowledge graph **today, in a file, in git** — that's trikedb. And because the storage maps cleanly onto RDF, graduating to a bigger system later is an export, not a rewrite: each team keeps its own YAML graph, and stitching them together (or migrating them wholesale) is just merging triples.

### Curation-first, not extraction-first

Most "AI knowledge graph" tools use an LLM to extract triples from text. That's great for bootstrapping, but extracted graphs inherit hallucinations. trikedb takes the opposite stance: **the graph is curated data** (by humans, or by agents you supervise), the ontology constrains what can be said, and LLMs *consume* the graph rather than invent it. When an agent reads

```yaml
- {s: crm-sync-job, p: INGESTS_TO, o: RAW_CRM_CONTACTS}
```

there is no step where a table name can be made up.

## Install

From [PyPI](https://pypi.org/project/trikedb/):

```bash
pip install trikedb             # library + CLI (PyYAML + rdflib only)
pip install 'trikedb[all]'      # everything below in one shot

pip install 'trikedb[mcp]'      # + MCP server for AI agents (stdio)
pip install 'trikedb[serve]'    # + UI / REST / remote MCP over HTTP
pip install 'trikedb[oauth]'    # + OAuth 2.1 for the claude.ai / ChatGPT UIs
pip install 'trikedb[remote]'   # + s3:// gs:// graphs
pip install 'trikedb[snowflake]' # + snowflake:// graphs (the warehouse is the store)
pip install 'trikedb[shacl]'    # + SHACL validation
pip install 'trikedb[owl]'      # + OWL-RL inference
pip install 'trikedb[semantic]' # + semantic search (numpy + model2vec, no torch)
pip install 'trikedb[networkx]' # + property-graph projection (to_networkx)
```

## Quickstart (Python)

```python
from trikedb import TrikeDB

# A typed knowledge graph that lives in one YAML file. The predicates you declare
# are the schema — that whitelist catches typos and junk on write.
db = TrikeDB("pipeline.yaml", ontology={
    "PROVIDES":   "SaaS vendor -> ingestion job",
    "INGESTS_TO": "ingestion job -> warehouse table",
    "MIGRATED_TO": "deprecated table -> its replacement",
})

# Add facts. Any keyword becomes an edge attribute — and `prov` is the one to
# standardize on: cite where each fact came from so the graph stays verifiable.
db.add("salesflow-crm", "PROVIDES", "crm-sync-job")
db.add("crm-sync-job", "INGESTS_TO", "RAW_CRM_CONTACTS",
       schedule="hourly", prov="https://runbook.example/crm#sync")
db.add("LEGACY_DUMP", "MIGRATED_TO", "RAW_CRM_CONTACTS", deprecated=True)

# The ontology is a guardrail: db.add("crm-sync-job", "OWNS", "x") would raise
# OntologyError — 'OWNS' isn't a declared predicate, so the typo never lands.

# Describe nodes: `type` colors the graph and is queryable; attach anything else.
db.set_node("RAW_CRM_CONTACTS", type="table", pii=True,
            url="https://catalog.example/raw_crm_contacts")

# Ask questions — join patterns with zero dependencies …
db.query(["?vendor PROVIDES ?job", "?job INGESTS_TO ?table"])
# [{'vendor': 'salesflow-crm', 'job': 'crm-sync-job', 'table': 'RAW_CRM_CONTACTS'}]

# … or full SPARQL 1.1 (FILTER, OPTIONAL, aggregates — delegated to rdflib, t: pre-bound)
db.sparql('SELECT ?t WHERE { ?t t:type "table" ; t:pii true }')   # every PII table
db.sparql('SELECT ?s ?o WHERE { ?st rdf:subject ?s ; rdf:object ?o ; t:schedule "hourly" }')  # edge attrs, too

# Let the graph classify itself — declare RDFS/OWL semantics and materialize what
# follows (pip install 'trikedb[owl]'). Inferred facts land in the YAML, reviewable.
db.declare("INGESTS_TO", "domain:job")    # subjects of INGESTS_TO are jobs
db.declare("INGESTS_TO", "range:table")   # objects are tables
db.infer(apply=True)   # -> crm-sync-job a job, RAW_CRM_CONTACTS a table (tagged inferred: true)

# Check it before you trust it — validate against SHACL shapes (pip install 'trikedb[shacl]')
ok, report = db.validate('''@prefix sh: <http://www.w3.org/ns/shacl#> . @prefix t: <urn:trikedb:> .
  t:IngestShape a sh:NodeShape ; sh:targetObjectsOf t:INGESTS_TO ;
    sh:property [ sh:path t:type ; sh:minCount 1 ] .''')   # does every landed table declare a type?

# Find facts by meaning, not spelling (pip install 'trikedb[semantic]')
db.search("what syncs the CRM?", k=5)

# Hybrid retrieval for agents — semantic recall + a hard structured filter, in one
# call: cast a wide net by meaning, then keep only what precisely matches.
db.find("where is the customer CRM data?", where={"type": "table", "pii": True})
# -> [{'node': 'RAW_CRM_CONTACTS', 'props': {'type': 'table', 'pii': True, ...}, 'facts': [...]}]

# Writes go through SPARQL too and autosave straight back to the YAML
db.sparql("INSERT DATA { t:figly t:PROVIDES t:figly-export-job }")

# Ship one self-contained HTML file your team can actually click through
db.to_html("pipeline.html")     # searchable graph + node details + in-browser SPARQL console
db.to_rdflib(); db.to_jsonld()  # RDF/SPARQL view — or graduate to any RDF tool
db.to_networkx()                # property-graph view: run networkx algorithms on the
                                # same file (shortest path, centrality) — 'trikedb[networkx]'
```

## Quickstart (CLI)

```bash
trikedb add pipeline.yaml salesflow-crm PROVIDES crm-sync-job
# `prov` is just an edge attribute, but the one to standardize on: cite each fact's source.
trikedb add pipeline.yaml crm-sync-job INGESTS_TO RAW_CRM_CONTACTS -a schedule=hourly -a prov=https://runbook.example/crm#sync

trikedb query pipeline.yaml -w "?vendor PROVIDES ?job" -w "?job INGESTS_TO ?table"
# vendor         job           table
# -------------  ------------  ----------------
# salesflow-crm  crm-sync-job  RAW_CRM_CONTACTS

trikedb sparql pipeline.yaml \
  "SELECT ?v ?t WHERE { ?v t:PROVIDES ?j . ?j t:INGESTS_TO ?t }"

# updates persist straight back to the file
trikedb sparql pipeline.yaml \
  "INSERT DATA { t:figly t:PROVIDES t:figly-export-job }"

# semantic search: meaning, not spelling ([semantic] extra)
trikedb search pipeline.yaml "what syncs the CRM?" -k 5

trikedb stats pipeline.yaml
trikedb html pipeline.yaml -o pipeline.html
trikedb jsonld pipeline.yaml
```

## Importing from CSV and Markdown docs

The YAML file is the store, but triples can come from wherever your team already writes:

```bash
# CSV/TSV with an s,p,o header — extra columns become edge attributes
trikedb import pipeline.yaml new_vendors.csv

# Markdown: every table whose header has s/p/o columns is picked up;
# prose and other tables are ignored. Your design docs are data.
trikedb import pipeline.yaml design_doc.md
```

```markdown
<!-- anywhere inside an ordinary design doc: -->
| s                 | p          | o                  | schedule  |
|-------------------|------------|--------------------|-----------|
| clickpath-pa      | PROVIDES   | clickpath-webhook  |           |
| clickpath-webhook | INGESTS_TO | RAW_PRODUCT_EVENTS | streaming |
```

Imports are deterministic — no LLM extraction, so nothing gets invented. The ontology is enforced on the way in, and `"true"`/`"false"` cells become booleans. See [`examples/acme_design_doc.md`](https://github.com/RyutoYoda/trikedb/blob/main/examples/acme_design_doc.md) and [`examples/acme_new_vendors.csv`](https://github.com/RyutoYoda/trikedb/blob/main/examples/acme_new_vendors.csv).

## Validation and inference (SHACL / OWL)

The predicate whitelist is the seatbelt; when you want real schema
validation, use SHACL (`pip install 'trikedb[shacl]'` — delegated to
[pySHACL](https://github.com/RDFLib/pySHACL), not hand-rolled):

```python
conforms, report = db.validate("""
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix t:  <urn:trikedb:> .
t:BotShape a sh:NodeShape ;
  sh:targetSubjectsOf t:USES_ROLE ;
  sh:property [ sh:path t:type ; sh:hasValue "bot" ; sh:minCount 1 ] .
""")
```

```bash
trikedb validate graph.yaml shapes.ttl   # exit code 1 on violations — CI-friendly
```

For inference, declare RDFS/OWL semantics on your predicates (and
classes) and materialize what follows (`pip install 'trikedb[owl]'`,
OWL-RL via [owlrl](https://github.com/RDFLib/OWL-RL)):

```python
# OWL property characteristics
db.declare("INHERITS", "transitive")     # stored as a reviewable triple
db.add("admin", "INHERITS", "editor")
db.add("editor", "INHERITS", "viewer")
db.infer(apply=True)                     # adds (admin, INHERITS, viewer) — marked inferred: true

# RDFS class hierarchy + typing
db.declare("Cat", "subclass_of:Animal")        # rdfs:subClassOf
db.declare("authored", "domain:Person")        # rdfs:domain  → subjects get typed
db.declare("authored", "range:Book")           # rdfs:range   → objects get typed
db.declare("bornIn", "subproperty_of:locatedIn")  # rdfs:subPropertyOf
db.add("felix", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "Cat")
db.infer()   # → (felix, rdf:type, Animal)  via subClassOf; domain/range typing; etc.
```

`infer()` surfaces classifications and hierarchy (rdf:type, subClassOf,
subPropertyOf) as well as OWL edges (transitive / symmetric / inverse),
while suppressing the reasoner's rdf/owl bookkeeping noise.

Inference is **materialization, not magic**: derived facts land in the
YAML tagged `inferred: true`, so the git diff shows exactly what the
reasoner concluded and a human can review it like any other change.
(For ad-hoc transitivity you often don't need OWL at all — SPARQL
property paths like `t:INHERITS+` already walk chains at query time.)

## Where the graph lives: your storage, your choice

The file doesn't have to be local, and it doesn't have to be a file.
Everything above storage only ever asks for one whole document, so the
destination swaps out and nothing else changes — SPARQL, the MCP tools,
SHACL and `to_networkx` behave identically wherever the bytes are.

**Object storage** (`pip install 'trikedb[remote]'`):

```python
db = TrikeDB("s3://team-bucket/kg/pipeline.yaml")   # read and write
```

```bash
trikedb sparql s3://team-bucket/kg/pipeline.yaml "SELECT ?s WHERE { ?s ?p ?o } LIMIT 5"
trikedb mcp s3://team-bucket/kg/pipeline.yaml       # whole team's agents share one graph
```

Auth is delegated to the standard AWS credential chain (env vars,
`~/.aws/credentials` profiles, SSO, IAM roles) via fsspec/s3fs — trikedb
stores no credentials, and your bucket policy *is* the access control:
readers get `s3:GetObject`, writers get `s3:PutObject`, per-prefix
policies give each team its own graph. `gs://`, `az://` and plain
`https://` (read-only) work through the same mechanism with the
matching fsspec backend installed.

**A warehouse table** (`pip install 'trikedb[snowflake]'`) — for teams
whose governance says data lives in the warehouse:

```python
db = TrikeDB("snowflake://ANALYTICS.PUBLIC.TRIKE_GRAPHS/sales/crm")
```

One graph is one row (`name`, `doc`, `version`, `updated_at`), and one
table holds many graphs — adopting trikedb costs a company one table, not
one per graph. There's no local copy and nothing to synchronise: the
`doc` column holds the same YAML document, byte for byte, and the row
*is* the graph. Create the table first (trikedb won't run DDL in your
warehouse on its own):

```bash
trikedb sql-init snowflake://ANALYTICS.PUBLIC.TRIKE_GRAPHS/sales/crm --print   # review the DDL
trikedb sql-init snowflake://ANALYTICS.PUBLIC.TRIKE_GRAPHS/sales/crm           # or just run it
```

Connection settings come from the environment (`SNOWFLAKE_ACCOUNT`,
`SNOWFLAKE_USER`, `SNOWFLAKE_PRIVATE_KEY_PATH` or `SNOWFLAKE_PASSWORD`,
plus role/warehouse/database as needed), or name an entry in your
`connections.toml` with `SNOWFLAKE_CONNECTION_NAME` and let your existing
Snowflake tooling own it. Same as S3: trikedb stores no credentials, and
your grants are the access control.

Concurrent writes are safe on both. A save is conditional on the stored
graph still being the one it was read from, so a write that would clobber
someone else is refused with `ConcurrentWriteError` rather than silently
winning — S3 does it with an ETag precondition, a warehouse with a
version column and an affected-row count. Ten concurrent writers land ten
triples in either. `gs://`, `az://` and local files have no conditional
write, so they stay last-write-wins: point writers through a single MCP
process or keep writes in git-reviewed batches.

Adding a backend happens in one place. A warehouse is four SQL templates
and a connect function.

## Workspaces: many graphs, one view

Real teams have more than one graph — finance, data platform, HR. A
workspace file unions them:

```yaml
# workspace.yaml
graphs:
  finance:  finance.yaml
  platform: s3://team-bucket/kg/platform.yaml   # local and remote mix freely
  warehouse: ../infra/ontology/warehouse.yaml
```

Every command accepts it (`trikedb sparql workspace.yaml ...`,
`trikedb html workspace.yaml`, `trikedb serve workspace.yaml`). In the
HTML view each project tiles into its own cluster with a per-graph
filter bar; every triple carries a `graph:` attribute naming its source.

The payoff is **automatic joins**: because RDF triples merge on shared
names, `(tanaka, OWNS_BUDGET, project-atlas)` in finance and
`(project-atlas, USES, ACME_DWH)` in platform become one SPARQL-walkable path —
no foreign keys, no schema negotiation. Unions are **read-only views**;
each member graph stays owned (and permissioned) by its team, and
writes go to the member file.

## Keeping a growing graph healthy

Ontologies accumulate facts from many hands (and agents). Two commands
keep that sustainable:

```bash
# CI / pre-commit: does the graph parse, and is the exported HTML current?
# Generated HTML embeds a content hash of the graph, so staleness is detectable.
trikedb check graph.yaml --html docs/index.html   # exit 1 if stale

# health findings: duplicate triples across workspace members, Tokyo-vs-tokyo
# name collisions, near-duplicate free-text facts, orphan node props,
# declared-but-unused predicates
trikedb audit workspace.yaml            # exit 1 on errors; --strict fails on warnings too
```

`audit` is deterministic by design — for semantic dedup beyond these
heuristics, hand the `--json` report to an LLM agent and let it propose
merges as a reviewable PR.

**The review gate depends on where the graph lives.** A file in git gives
you the strongest story: every change is a diff, `check` and `audit` run
in CI, history comes free. An `s3://` or `snowflake://` graph has no pull
request — writes land immediately — so review moves to the ontology guard
at the write boundary, `audit` on a schedule instead of per-change, and
the backend's own history (object versions, warehouse time travel, the
`updated_at` column). Some teams run both on purpose: the reviewed graph
in git, a shared graph agents write to, unioned with a workspace file so
curation and accumulation don't block each other.

## Do you have to write YAML by hand?

No — YAML is the storage format, not the authoring interface. It's what
the graph is written down as, chosen so a human can read a diff. Every
write path produces the same document and passes the same ontology check:

| | |
|---|---|
| `db.add(s, p, o, **attrs)` | Python — scripts, notebooks, ETL |
| `trikedb add FILE S P O -a k=v` | one fact from a shell |
| `trikedb import FILE data.csv` | a spreadsheet or Markdown table already has the facts |
| `db.sparql("INSERT DATA {...}")` | you think in SPARQL |
| MCP `add_triple` / `set_node` | an agent is writing — the usual case |
| `db.infer(apply=True)` | materialize what already follows |
| editing the YAML | a text editor is a legitimate client too |

The guard applies to all of them equally, so "an agent wrote it" and "a
human wrote it" can't diverge in vocabulary.

The HTML workbench is a *rendering*, and where the graph lives never
decides where the page goes: a local graph renders next to itself, a
remote one into the working directory, and `-o` takes a path or an object
URL (`-o s3://site/kg.html` publishes it). It's one self-contained file —
no build step, no server — so publishing is just putting it somewhere.

## Serving a graph (UI + REST + remote MCP)

One process, three doors (`pip install 'trikedb[serve]'`):

```bash
trikedb serve workspace.yaml --port 8080 --token $SECRET
```

- `/` — the workbench UI, always showing the current graph
- `/sparql` — minimal REST: `POST {"query": "..."}` → JSON, for apps
- `/mcp` — MCP over Streamable HTTP, for agents anywhere:

```bash
claude mcp add kg https://kg.internal:8080/mcp --transport http \
  --header "Authorization: Bearer $SECRET"
```

Same eleven MCP tools as stdio — the server definition is shared, only
the transport differs. Pair it with an `s3://` graph and the server is
stateless — run it anywhere.

### OAuth 2.1, for the claude.ai and ChatGPT UIs

A static token is fine for a script, but the web UIs want a real login.
Point trikedb at an IdP you already run and it becomes an OAuth 2.1
resource server — the thing both connector UIs know how to talk to:

```bash
pip install 'trikedb[serve,oauth]'
trikedb serve graph.yaml --public-url https://kg.example.com \
  --oauth-issuer https://idp.example.com/ --required-scope kg:read
```

Then add `https://kg.example.com/mcp` as a custom connector and log in
as yourself. trikedb **verifies** tokens; it never issues them. There is
no authorization server here, no user table, no password — just a JWKS
lookup against your issuer and a check that the token's signature,
expiry, and audience are right. Your IdP stays the only place identity
lives, and the graph stays a file.

Three things to get right:

- **`--public-url` must be the HTTPS URL clients actually reach.** Tokens
  are bound to `<public-url>/mcp` as their audience (RFC 8707), so a
  token minted for another service can't open your graph. Override with
  `--oauth-audience` if your IdP issues a fixed API identifier instead.
- **The IdP needs to register the connector.** Dynamic Client Registration
  is the smooth path (Auth0, Okta, Keycloak, WorkOS all support it); if
  yours doesn't, claude.ai also accepts a Client ID Metadata Document or
  a client ID/secret you paste in.
- **It has to be publicly reachable over HTTPS.** Neither UI can connect
  to `localhost` — use a tunnel while you're developing.

Discovery is served for you at
`/.well-known/oauth-protected-resource/mcp`, and an unauthenticated
request gets the RFC 9728 challenge that starts the login flow.

## The file format

A trikedb file is ordinary YAML with three top-level keys (only `triples` is required):

```yaml
ontology:            # optional — omit it for free-form predicates
  predicates:
    PROVIDES: "SaaS vendor -> ingestion job"
    AFFECTED_BY: "table -> change event"

nodes:               # optional — free-form node properties
  salesflow-crm: {type: saas, url: "https://salesflow.example", plan: enterprise}
  RAW_CRM_CONTACTS: {type: table, schema: ACME_RAW, pii: true}

triples:
  # compact form for plain facts
  - {s: adastra-ads, p: PROVIDES, o: ads-spend-collector}

  # any extra keys become edge attributes
  - s: RAW_AD_SPEND_DAILY
    p: AFFECTED_BY
    o: "2025-04-01 adastra API v3: spend now in micros (was cents)"
```

Three conventions worth stealing (see [`examples/acme_pipeline.yaml`](https://github.com/RyutoYoda/trikedb/blob/main/examples/acme_pipeline.yaml)):

- **Change events as objects.** `AFFECTED_BY` edges pointing at dated event strings give your graph a memory — "why did this number change in April?" becomes a query.
- **`deprecated: true`** on edges renders them dashed in the HTML view and lets agents filter dead paths.
- **`via:` / `schedule:`** attributes carry operational detail without polluting the node set.
- **Node properties keep growing.** That's the RDF promise: attach `type`, `url`, `schema`, owners — whatever your team needs — without a schema migration. `type` drives color grouping in the HTML view, and node properties are queryable in SPARQL (`?x t:type "table"`). Set them from code with `db.set_node("RAW_CRM_CONTACTS", pii=True)`.

## Hybrid retrieval for agents

Semantic search is great at recall (finds what you mean) but not precision — the score is uncalibrated and it never says "no match." SPARQL is the opposite: exact, but only if you already know the names. `find()` combines them in one call — **semantic recall, then a hard structured filter** — which is the retrieval an agent actually wants:

```python
# "cast a wide net by meaning, then keep only what precisely matches"
db.find("where is the customer CRM data?",
        where={"type": "table", "pii": True})   # dict of required node props …
db.find("customer data", where=lambda name, props: props.get("pii"))  # … or a predicate

# each result is a ready-to-use payload: the node, its properties, its facts
# [{"node": "RAW_CRM_CONTACTS", "props": {"type": "table", "pii": True, ...},
#   "facts": [["INGESTS_TO", ...], ...]}]
```

Recall casts a wide net (`search`, cross-lingual, synonym-tolerant); the `where` filter drops the false positives with no fuzz and pulls exact structured facts. Use the recall stage for candidates and the filter for correctness — never gate on the raw similarity score. The same two-stage move is available to LLM agents as the **`find` MCP tool** below, or hand-rolled from `search` + `sparql`/`match` when you want full control.

## An ontology layer for AI agents (MCP)

trikedb is embedded, not hosted. For agents, "embedded" means MCP over stdio — the graph runs inside the agent session, no server to operate. Register it with any MCP client:

```json
{
  "mcpServers": {
    "kg": {
      "command": "uvx",
      "args": ["--from", "trikedb[mcp]", "trikedb", "mcp", "/absolute/path/to/graph.yaml"]
    }
  }
}
```

The agent gets `sparql`, `match`, `search`, `find`, `get_node`, `ontology`, `stats` to read, and `add_triple`, `set_node`, `remove_triples`, `import_source` to write. Every write autosaves to the YAML — so agent contributions arrive as reviewable git diffs.

This is also the answer to "just throw docs at it": **the agent is the extractor, trikedb is the validated write path.** Point your agent at a pile of documents and ask it to record the facts; it reads them (any format — it's an LLM), calls `add_triple` for each fact, and the ontology rejects any predicate it tries to invent. Extraction stays flexible, the graph stays clean, and a human reviews the diff.

## Using it with LLM agents (no MCP)

The zero-setup loop:

1. Keep `graph.yaml` in your repo, next to the code it describes.
2. Tell your agent about it once (in your agent's project instructions / system prompt):

   > Before any task touching the data pipeline, read `pipeline.yaml`.
   > It is the source of truth for which jobs feed which tables.
   > Predicates are limited to the ontology declared in the file.

3. Agents propose edits as diffs to the YAML — reviewable in a PR like any other change. The ontology check (`trikedb.add` raises on unknown predicates) keeps generated edits inside the vocabulary you chose.
4. Humans browse the same graph via `trikedb html`.

One source of truth, two projections: YAML for machines, HTML for people.

## What trikedb is not

- **Not a SPARQL implementation of its own.** The SPARQL surface is deliberately *not* hand-rolled — your YAML is loaded into [rdflib](https://github.com/RDFLib/rdflib) and queried/updated by rdflib's battle-tested engine. Mapping rule: subjects/predicates become URIs under `urn:trikedb:`; objects with whitespace (change events, notes) become literals. Triples inserted via SPARQL start without edge attributes; surviving triples keep theirs. The lighter `query()`/`triples()` API also exists for quick pattern matching.
- **Not an extraction pipeline.** It won't turn your PDFs into a graph. Pair it with an extractor if you want that — then curate what comes out.
- **Not for millions of triples.** Everything is in memory and scans are linear. The sweet spot is the hundreds-to-thousands range, where a curated graph is even possible.

## Examples

- [`examples/freebase_sample.yaml`](https://github.com/RyutoYoda/trikedb/blob/main/examples/freebase_sample.yaml) — **real-world data**: ~600 facts from the Freebase knowledge graph (CC BY, extracted from the WebQSP benchmark subgraphs) around Tupac Shakur, Agatha Christie, Nikola Tesla and more. Node types are inferred from predicate domains. This powers the live demo.
- [`examples/freebase_workspace.yaml`](https://github.com/RyutoYoda/trikedb/blob/main/examples/freebase_workspace.yaml) — the same facts split into 6 domain graphs (film / music / books / people / places / misc) and unioned back as a **workspace**: each member renders as its own island with a filter chip. This powers the workspace demo.
- [`examples/acme_pipeline.yaml`](https://github.com/RyutoYoda/trikedb/blob/main/examples/acme_pipeline.yaml) — a fictional data platform showing the operational conventions: ontology, deprecations, change events.
- [`examples/python_ecosystem.yaml`](https://github.com/RyutoYoda/trikedb/blob/main/examples/python_ecosystem.yaml) — free-form predicates, no ontology.
- [`examples/trikedb_quickstart.ipynb`](https://github.com/RyutoYoda/trikedb/blob/main/examples/trikedb_quickstart.ipynb) — runnable notebook quickstart with an inline graph.

**Live demo:** https://ryutoyoda.github.io/trikedb/ · **Workspace demo:** https://ryutoyoda.github.io/trikedb/workspace.html

The exported HTML is a small workbench, not just a picture: click a node for a right-hand panel with all its properties (URLs become links), search nodes top-right, and open the **SPARQL console** to run real SPARQL 1.1 in the browser — powered by [Oxigraph](https://github.com/oxigraph/oxigraph) compiled to WASM, loaded from CDN on first use. Change events render as red diamonds with a timeline bar at the bottom; the initial layout adapts to graph shape (`--layout flow|free|auto`). Filter the view by toggling node-type checkboxes (with **all / none** shortcuts) — the legend slides horizontally when types get numerous — and, in a workspace, toggle member graphs the same way.

## Benchmark

On [WebQSP](https://aclanthology.org/P16-2033/) (knowledge-graph QA), the same small LLM answers **60% alone vs 83% with a trikedb graph as context** — a +23-point delta under a deterministic, reproducible protocol. Scripts, method, and an honest scoring-sensitivity analysis live in [`benchmarks/`](https://github.com/RyutoYoda/trikedb/tree/main/benchmarks).

## Documentation

- [docs/REFERENCE.md](https://github.com/RyutoYoda/trikedb/blob/main/docs/REFERENCE.md) — every feature and how to use it (CLI, Python API, MCP, serve, extras) · [日本語版](https://github.com/RyutoYoda/trikedb/blob/main/docs/REFERENCE_jp.md)
- [docs/ARCHITECTURE.md](https://github.com/RyutoYoda/trikedb/blob/main/docs/ARCHITECTURE.md) — the layering and where new code goes
- [docs/SCALING.md](https://github.com/RyutoYoda/trikedb/blob/main/docs/SCALING.md) — measured limits at 1k/10k/100k triples, and when to move from whole-file reads to a served graph
- [benchmarks/](https://github.com/RyutoYoda/trikedb/tree/main/benchmarks) — WebQSP methodology and findings

## Development

Uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync --extra dev
uv run pytest
```

## License

MIT
