<p align="center">
  <img src="https://raw.githubusercontent.com/RyutoYoda/trikedb/main/docs/logo.png" width="260" alt="TrikeDB — a triceratops carrying a knowledge graph on its frill">
</p>

<p align="center">
  <a href="https://pypi.org/project/trikedb/"><img src="https://img.shields.io/pypi/v/trikedb?style=flat&color=4a6fa5" /></a>
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
| Writes | SPARQL Update | SPARQL Update — persisted back to the YAML |
| Schema | OWL + reasoners | a list of allowed predicates |
| Agent integration | a service to operate | the agent reads the file, or `trikedb mcp` (stdio, embedded) |
| Setup time | an afternoon (or a sprint) | `pip install trikedb` |

If you need inference engines, named graphs, and multi-tenant governance, you want a full enterprise semantic platform. If you want a knowledge graph **today, in a file, in git** — that's trikedb. And because the storage maps cleanly onto RDF, graduating to a bigger system later is an export, not a rewrite: each team keeps its own YAML graph, and stitching them together (or migrating them wholesale) is just merging triples.

### Curation-first, not extraction-first

Most "AI knowledge graph" tools use an LLM to extract triples from text. That's great for bootstrapping, but extracted graphs inherit hallucinations. trikedb takes the opposite stance: **the graph is curated data** (by humans, or by agents you supervise), the ontology constrains what can be said, and LLMs *consume* the graph rather than invent it. When an agent reads

```yaml
- {s: crm-sync-job, p: INGESTS_TO, o: RAW_CRM_CONTACTS}
```

there is no step where a table name can be made up.

## Install

From [PyPI](https://pypi.org/project/trikedb/):

```bash
pip install trikedb           # library + CLI
pip install 'trikedb[mcp]'    # + MCP server for AI agents
```

## Quickstart (Python)

```python
from trikedb import TrikeDB

db = TrikeDB("pipeline.yaml", ontology={
    "PROVIDES": "SaaS vendor -> ingestion job",
    "INGESTS_TO": "ingestion job -> warehouse table",
    "MIGRATED_TO": "deprecated table -> its replacement",
})

db.add("salesflow-crm", "PROVIDES", "crm-sync-job")
db.add("crm-sync-job", "INGESTS_TO", "RAW_CRM_CONTACTS", schedule="hourly")
db.add("crm-sync-job", "OWNS", "x")   # OntologyError: predicate not declared

# Pattern matching — None is a wildcard, '*' globs
for t in db.triples(p="INGESTS_TO", o="RAW_*"):
    print(t.s, "->", t.o, t.attrs)

# Multi-pattern queries with variable joins (zero dependencies)
db.query(["?vendor PROVIDES ?job", "?job INGESTS_TO ?table"])
# [{'vendor': 'salesflow-crm', 'job': 'crm-sync-job', 'table': 'RAW_CRM_CONTACTS'}]

# Or real SPARQL 1.1 — FILTER, OPTIONAL, aggregates, the lot.
# Delegated to rdflib, not hand-rolled. The prefix t: is pre-bound.
db.sparql("""
  SELECT ?vendor ?table WHERE {
    ?vendor t:PROVIDES ?job .
    ?job t:INGESTS_TO ?table .
    FILTER(STRSTARTS(STR(?table), "urn:trikedb:RAW_"))
  }
""")
db.sparql("ASK { ?x t:MIGRATED_TO ?y }")  # True

# Writes go through SPARQL too — and land back in the YAML
db.sparql("INSERT DATA { t:figly t:PROVIDES t:figly-export-job }")
db.sparql("DELETE WHERE { ?job t:INGESTS_TO t:LEGACY_CONTACTS_DUMP }")
db.save()  # or pass autosave=True and skip this

db.to_rdflib()               # plain rdflib.Graph, if you want to go further
db.to_html("pipeline.html")  # interactive graph workbench (see demos below)
db.to_jsonld()               # best-effort export for real RDF tooling
```

## Quickstart (CLI)

```bash
trikedb add pipeline.yaml salesflow-crm PROVIDES crm-sync-job
trikedb add pipeline.yaml crm-sync-job INGESTS_TO RAW_CRM_CONTACTS -a schedule=hourly

trikedb query pipeline.yaml -w "?vendor PROVIDES ?job" -w "?job INGESTS_TO ?table"
# vendor         job           table
# -------------  ------------  ----------------
# salesflow-crm  crm-sync-job  RAW_CRM_CONTACTS

trikedb sparql pipeline.yaml \
  "SELECT ?v ?t WHERE { ?v t:PROVIDES ?j . ?j t:INGESTS_TO ?t }"

# updates persist straight back to the file
trikedb sparql pipeline.yaml \
  "INSERT DATA { t:figly t:PROVIDES t:figly-export-job }"

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

Imports are deterministic — no LLM extraction, so nothing gets invented. The ontology is enforced on the way in, and `"true"`/`"false"` cells become booleans. See [`examples/acme_design_doc.md`](examples/acme_design_doc.md) and [`examples/acme_new_vendors.csv`](examples/acme_new_vendors.csv).

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

Three conventions worth stealing (see [`examples/acme_pipeline.yaml`](examples/acme_pipeline.yaml)):

- **Change events as objects.** `AFFECTED_BY` edges pointing at dated event strings give your graph a memory — "why did this number change in April?" becomes a query.
- **`deprecated: true`** on edges renders them dashed in the HTML view and lets agents filter dead paths.
- **`via:` / `schedule:`** attributes carry operational detail without polluting the node set.
- **Node properties keep growing.** That's the RDF promise: attach `type`, `url`, `schema`, owners — whatever your team needs — without a schema migration. `type` drives color grouping in the HTML view, and node properties are queryable in SPARQL (`?x t:type "table"`). Set them from code with `db.set_node("RAW_CRM_CONTACTS", pii=True)`.

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

The agent gets `sparql`, `match`, `get_node`, `ontology`, `stats` to read, and `add_triple`, `set_node`, `remove_triples`, `import_source` to write. Every write autosaves to the YAML — so agent contributions arrive as reviewable git diffs.

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

- [`examples/freebase_sample.yaml`](examples/freebase_sample.yaml) — **real-world data**: ~600 facts from the Freebase knowledge graph (CC BY, extracted from the WebQSP benchmark subgraphs) around Tupac Shakur, Agatha Christie, Nikola Tesla and more. Node types are inferred from predicate domains. This powers the live demo.
- [`examples/acme_pipeline.yaml`](examples/acme_pipeline.yaml) — a fictional data platform showing the operational conventions: ontology, deprecations, change events.
- [`examples/python_ecosystem.yaml`](examples/python_ecosystem.yaml) — free-form predicates, no ontology.
- [`examples/trikedb_quickstart.ipynb`](examples/trikedb_quickstart.ipynb) — runnable notebook quickstart with an inline graph.

**Live demo:** https://ryutoyoda.github.io/trikedb/

The exported HTML is a small workbench, not just a picture: click a node for a right-hand panel with all its properties (URLs become links), search nodes top-right, and open the **SPARQL console** to run real SPARQL 1.1 in the browser — powered by [Oxigraph](https://github.com/oxigraph/oxigraph) compiled to WASM, loaded from CDN on first use. Change events render as red diamonds with a timeline bar at the bottom; the initial layout adapts to graph shape (`--layout flow|free|auto`).

## Benchmark

On [WebQSP](https://aclanthology.org/P16-2033/) (knowledge-graph QA), the same small LLM answers **60% alone vs 83% with a trikedb graph as context** — a +23-point delta under a deterministic, reproducible protocol. Scripts, method, and an honest scoring-sensitivity analysis live in [`benchmarks/`](benchmarks/).

## Development

Uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync --extra dev
uv run pytest
```

## License

MIT
