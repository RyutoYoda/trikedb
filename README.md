<p align="center">
  <b>English</b>
  &nbsp;·&nbsp; <a href="https://github.com/RyutoYoda/trikedb/blob/main/README_jp.md">日本語</a>
  &nbsp;·&nbsp; <a href="https://github.com/RyutoYoda/trikedb/blob/main/README_zh.md">简体中文</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/RyutoYoda/trikedb/main/docs/logo.png" width="260" alt="TrikeDB — a triceratops carrying a knowledge graph on its frill">
</p>

<p align="center">
  <a href="https://github.com/RyutoYoda/trikedb/actions/workflows/test.yml"><img src="https://github.com/RyutoYoda/trikedb/actions/workflows/test.yml/badge.svg" alt="tests" /></a>
  <a href="https://pypi.org/project/trikedb/"><img src="https://img.shields.io/pypi/v/trikedb?style=flat&color=4a6fa5&cacheSeconds=300" /></a>
  <img src="https://img.shields.io/pypi/pyversions/trikedb?style=flat&color=4a6fa5" />
  <img src="https://img.shields.io/badge/license-MIT-4a6fa5?style=flat" />
  <img src="https://img.shields.io/badge/SPARQL%201.1-3D7EBB?style=flat&logo=w3c&logoColor=white" />
  <img src="https://img.shields.io/badge/MCP-191919?style=flat&logo=modelcontextprotocol&logoColor=white" />
</p>

# trikedb

**A knowledge graph your agent can read, in one file you can diff.**

Your agent already reads your code. What it cannot read is everything that is
*not* in the code: which job feeds which table, who owns what, which of two
similar-looking services is the live one. So it guesses, and the guess is a
plausible name that does not exist.

trikedb is where you write that down — one YAML file, in the repo, next to the
code it describes:

```yaml
triples:
  - {s: salesflow-crm, p: PROVIDES, o: crm-sync-job}
  - {s: crm-sync-job, p: INGESTS_TO, o: RAW_CRM_CONTACTS, schedule: hourly}
  - {s: LEGACY_DUMP, p: MIGRATED_TO, o: RAW_CRM_CONTACTS, deprecated: true}
```

That file **is** the database. No server, no daemon, no deployment. It diffs in
git like any other file, a human can read it, and an agent can query it with
real [SPARQL 1.1](https://www.w3.org/TR/sparql11-query/) — executed by
[Oxigraph](https://github.com/oxigraph/oxigraph), not a homegrown subset —
or just open the file and read it.

<p align="center">
  <a href="https://ryutoyoda.github.io/trikedb/workspace.html">
    <img src="https://raw.githubusercontent.com/RyutoYoda/trikedb/main/docs/screenshot.png" alt="trikedb HTML workbench — 600 Freebase facts as force-directed clusters, with a node detail panel open" />
  </a>
</p>

<p align="center">
  <b>Live demos</b> —
  <a href="https://ryutoyoda.github.io/trikedb/">a company as five graphs</a>
  &nbsp;·&nbsp; <a href="https://ryutoyoda.github.io/trikedb/pipeline.html">a data platform with an action log</a>
  &nbsp;·&nbsp; <a href="https://ryutoyoda.github.io/trikedb/workspace.html">600 real facts, filterable, with an in-browser SPARQL console</a>
</p>

## Install

```bash
pip install trikedb          # library + CLI
pip install 'trikedb[mcp]'   # + MCP server, so an agent can use it
pip install 'trikedb[all]'   # + serve, OAuth, SHACL, OWL, semantic search, S3/warehouse graphs
```

Every optional feature is an extra, so the core stays PyYAML + rdflib + pyoxigraph.
The full list is in [the reference](https://github.com/RyutoYoda/trikedb/blob/main/docs/REFERENCE.md#extras).

## Start with three facts

No schema, no modelling session. Write facts, look at them:

```python
from trikedb import TrikeDB

db = TrikeDB("graph.yaml")               # the file is created on first write
db.add("salesflow-crm", "PROVIDES", "crm-sync-job")
db.add("crm-sync-job", "INGESTS_TO", "RAW_CRM_CONTACTS", schedule="hourly")
db.set_node("RAW_CRM_CONTACTS", type="table", pii=True)

db.query(["?vendor PROVIDES ?job", "?job INGESTS_TO ?table"])
db.to_html("graph.html")                 # a clickable page for your teammates
```

Or from a blank repo, without writing any Python:

```bash
trikedb init graph.yaml --template agent-memory   # a starting graph with a real shape
trikedb add graph.yaml salesflow-crm PROVIDES crm-sync-job
trikedb query graph.yaml -w "?vendor PROVIDES ?job"
trikedb ui graph.yaml                             # open it in a browser
```

## The four you actually need

There are more, but a graph that earns its keep is usually built out of these:

| | |
|---|---|
| `db.add(s, p, o, **attrs)` | state a fact. Any keyword becomes an edge attribute — `prov=` is the one worth standardizing on, so every fact can be traced back to its source |
| `db.act(s, p, o, by=…, state=…)` | record something that *happened*: it is stamped with a time, appended to the node's history, and moves the node to the state it left behind |
| `db.find(question, where=…)` | the retrieval an agent wants: search by meaning, then filter on exact properties |
| `db.sparql(query)` | the full query language, when patterns are not enough |

Everything else — inference, SHACL, workspaces, S3 and warehouse storage, the
HTTP server — is there when you need it and costs nothing until then.
See [the reference](https://github.com/RyutoYoda/trikedb/blob/main/docs/REFERENCE.md).

## Then lock it down

A graph is only worth reading if it cannot fill up with junk. Declare what may
be said, and every write path — yours, the CLI's, an agent's — is held to it.
A shape is checked wherever the node's type is known, in either direction:

```python
db = TrikeDB("graph.yaml", ontology={
    "PROVIDES":   "SaaS vendor -> ingestion job",
    "INGESTS_TO": {"description": "ingestion job -> warehouse table",
                   "domain": "job", "range": "table"},
})

db.set_node("crm-sync-job", type="job")
db.set_node("RAW_CRM_CONTACTS", type="table")

db.add("crm-sync-job", "OWNS", "anything")                # OntologyError: undeclared predicate
db.add("RAW_CRM_CONTACTS", "INGESTS_TO", "crm-sync-job")  # OntologyError: written backwards
```

Actions can declare *when* they may run and *who* may sign them — the half a
type check cannot reach. An order delivered before it ever shipped breaks no
type; a price change approved by nobody is type-correct. Both are refused here:

```python
db.declare_link("DELIVERED_TO", domain="order", range="region",
                requires="SHIPPED_FROM",   # this has to have happened first
                by="courier")              # and this is who may do it

db.act("ORD-25101", "DELIVERED_TO", "Riverside", by="Kai")   # OntologyError: never shipped
```

## Hand it to an agent

Register the graph as an MCP server and the agent gets sixteen tools —
`sparql`, `match`, `search`, `find`, `get_node`, `history`, `ontology`, `stats`
to read, `add_triple`, `act`, `set_node`, `remove_triples`, `import_source` to
write, and `extraction_prompt`, `preview_triples`, `add_triples` to turn a
document into facts without guessing at the vocabulary:

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

Writes autosave to the YAML, so an agent's contribution arrives as a reviewable
git diff, and the ontology rejects any predicate it tries to invent. That is the
answer to "just throw the docs at it": **the agent is the extractor, trikedb is
the validated write path.** Extraction stays flexible; the vocabulary does not.

No MCP client? Then the whole integration is one line in your agent's project
instructions — *"before any task touching the pipeline, read `graph.yaml`"* —
and the file does the rest.

## Point it at a document

trikedb holds no model. It writes the prompt and judges the answer; who makes
the one call in between is up to you, and there are three ways to do it. The
prompt is built **from the graph being written into** — its declared predicates,
its existing node names — which is why whoever answers does not invent
`EMPLOYED_BY` beside `WORKS_AT`, or open a second node for a company already in
the file.

**The route that needs least is the shell, split in two.** No key, no SDK. What
stands in the middle is a person and whichever chat window is already open:

```bash
trikedb extract graph.yaml report.docx > prompt.txt # paste it anywhere
trikedb import graph.yaml answer.md --dry-run       # what it would do
trikedb import graph.yaml answer.md                 # what it did
```

**If you work through an agent, you don't even paste.**
[Register the graph as an MCP server](#hand-it-to-an-agent) and
`extraction_prompt` → `preview_triples` → `add_triples` walk the same path. The
model is already sitting in front of you; there is nothing to set up.

**If you already pay for a model and want this inside a script**, make that one
call yourself. `llm` is any callable taking the prompt and returning text —
three lines around whichever SDK you use, and five of them are written out in
[examples/extract_providers.py](https://github.com/RyutoYoda/trikedb/blob/main/examples/extract_providers.py):

```python
from extract_providers import anthropic      # examples/extract_providers.py

rows = db.extract(open("press-release.md").read(), llm=anthropic())
```

Whichever route you take, the last gate is the same one — `--dry-run`,
`preview_triples` and `db.preview` return the same verdicts. Before anything is
written, one row at a time:

```python
for f in db.preview(rows):          # nothing is written yet
    print(f["verdict"], f["triple"], f["detail"])

# new       Acme BASED_IN Osaka
# new       Sato WORKS_AT Acme
# conflict  Tanaka WORKS_AT Globex
#           └ WORKS_AT is declared functional and Tanaka already holds 'Acme'
```

A Word file goes in as it is: a `.docx` is a zip with an XML document inside,
so reading one costs no dependency. Google Docs exports Markdown directly
(File → Download → Markdown), which trikedb already reads.

`--dry-run` is worth having on its own, and works on any source — CSV, Markdown,
another graph. Every row comes back as `new`, `same`, `update`, `rejected` or
`conflict`, with the reason, and nothing is written until you have read them.
A `conflict` is not a guess: a predicate declared `functional` may hold one
object per subject, so a second one is a contradiction the graph can prove.

How well does the constrained prompt actually do? Run it and see — the cases,
the answer sheets and the scorer are in
[evals/](https://github.com/RyutoYoda/trikedb/tree/main/evals), along with the
unconstrained baseline to compare against. No scores are committed there,
because a committed score is one model on one day.

## What people put in it

- **An agent's memory of your systems.** Which warehouse role can read what,
  which ingestion job is the live one, which repo a change belongs in. None of
  it is in the code, all of it is what an agent gets wrong.
- **A service and ownership map.** Who calls whom, who is on call, which of the
  three similarly named services is deprecated.
- **A decision and incident log with preconditions.** `act()` plus `requires`
  means "deployed" cannot be recorded for something that was never approved —
  enforced on write, not in a review checklist.
- **A data governance ledger.** PII tables, who may access them, retention.
  `by:` and `requires:` are an authorization model that diffs in a pull request.

The common thread: a few hundred to a few thousand facts that somebody curates
on purpose. That is the size where a graph is both possible and worth trusting.

## Why not just a Markdown file?

Because a Markdown file cannot refuse a bad write, and neither can the agent
writing to it. Every fact here passes the same guard — predicate declared,
direction right, precondition met — whoever writes it. And once the facts are
structured you can ask questions no grep answers: everything two hops from this
table, every PII column with no owner, what changed since March.

It also measurably helps the model. On [WebQSP](https://aclanthology.org/P16-2033/)
(knowledge-graph QA), the same local model answers **42.7% alone vs 77.7% with a
trikedb graph as context** — Hits@1 over 300 questions, paired McNemar p = 9e-20,
0.59 s per question. Method, caveats, and an honest scoring-sensitivity analysis:
[`benchmarks/`](https://github.com/RyutoYoda/trikedb/tree/main/benchmarks).

## What trikedb is not

- **Not an extraction pipeline.** It will not call a language model, hold your
  key, or parse your PDFs. It writes the prompt from your ontology and judges
  every row against it before the write — the model and the decision stay
  yours. Extracted graphs inherit hallucinations; this is the part that makes
  them visible before they land. The only model trikedb ever runs itself is
  the small embedding one behind the optional `[semantic]` search, fetched
  once and then run locally.
- **Not for millions of triples.** Everything is in memory and scans are linear.
  Hundreds to thousands is the range where a curated graph is even possible.
- **Not its own SPARQL engine.** Reads run on Oxigraph, updates and OWL/SHACL on
  rdflib. Graduating to a full triple store later is an export, not a rewrite.
- **Not a replacement for Obsidian** if what you want is human notes. This is
  for facts a machine has to be right about.

## Where to go next

- [docs/REFERENCE.md](https://github.com/RyutoYoda/trikedb/blob/main/docs/REFERENCE.md) — every feature, the file format, and the compatibility and safety contract · [日本語](https://github.com/RyutoYoda/trikedb/blob/main/docs/REFERENCE_jp.md) · [简体中文](https://github.com/RyutoYoda/trikedb/blob/main/docs/REFERENCE_zh.md)
- [docs/ARCHITECTURE.md](https://github.com/RyutoYoda/trikedb/blob/main/docs/ARCHITECTURE.md) — the layering, and where new code goes
- [docs/SCALING.md](https://github.com/RyutoYoda/trikedb/blob/main/docs/SCALING.md) — measured limits at 1k / 10k / 100k triples
- [examples/](https://github.com/RyutoYoda/trikedb/tree/main/examples) — the graphs behind the demos, plus a [runnable notebook](https://github.com/RyutoYoda/trikedb/blob/main/examples/trikedb_quickstart.ipynb)
- [evals/](https://github.com/RyutoYoda/trikedb/tree/main/evals) — extraction cases, the scorer, and the baseline to measure against
- [CONTRIBUTING.md](https://github.com/RyutoYoda/trikedb/blob/main/CONTRIBUTING.md) — how to run the tests and what a good pull request looks like

## License

MIT. Copyright (c) 2026 Ryuto Yoda.

### Bundled data

One third-party dataset is shipped, and one is not:

- **Freebase** — the `examples/freebase_*.yaml` graphs are a small extract of the
  Freebase dump, licensed [CC BY 2.5](https://creativecommons.org/licenses/by/2.5/).
  They are in the repository so the demo pages can be rebuilt from their source.
- **WebQSP** — the benchmark questions and gold answers come from
  [The Value of Semantic Parse Labeling for KBQA](https://aclanthology.org/P16-2033/)
  (Yih et al., 2016), via the `rmanluo/RoG-webqsp` repack. No dataset content is
  committed here: `benchmarks/webqsp_bench.py prepare` downloads the test split at
  run time. What is tracked is `benchmarks/*_data.json` — the scored results the
  charts and the number above are read from.

Neither is required to use trikedb.
