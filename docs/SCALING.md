# Scaling: where does one document stop being comfortable?

Per-feature ceilings, and how many triples fit before git objects, live in
[benchmarks/README.md](../benchmarks/README.md#where-is-the-ceiling) with a
plot. This page covers the backends.

Measured with `benchmarks/backend_bench.py` (synthetic pipeline-shaped
graphs — vendors → jobs → tables, a third of the edges carrying note/prov
attributes) on an Apple-silicon laptop, trikedb 0.26.0. Medians of three.

| triples | backend | open | 1-hop | 2-hop join | count all | write 1 fact |
|---|---|---|---|---|---|---|
| 408 | local `.yaml` | 5 ms | 0.05 ms | 0.5 ms | 0.1 ms | 11 ms |
| 408 | local `.json` | **0.3 ms** | 0.04 ms | 0.5 ms | 0.1 ms | **1 ms** |
| 408 | `snowflake://` row | 189 ms | 0.04 ms | 0.5 ms | 0.1 ms | 761 ms |
| 40,800 | local `.yaml` | 992 ms | 0.04 ms | 55 ms | 11 ms | 1,957 ms |
| 40,800 | local `.json` | **57 ms** | 0.04 ms | 55 ms | 11 ms | **148 ms** |
| 40,800 | `snowflake://` row | 507 ms | 0.04 ms | 56 ms | 11 ms | 2,889 ms |

Three things fall out of this, and they are the whole story:

**Queries do not care where the graph lives.** 0.04 ms and 55 ms, identical
across all three backends. The graph is answered from memory, so the backend
only decides what opening and saving cost. That is the architecture working
as intended, and it is why "which backend" is an operations question rather
than a performance one.

**The format matters far more than the medium.** At 40,800 triples, a local
`.json` file opens in 57 ms and a local `.yaml` in 992 ms — 17x, for the same
graph, because `json.loads` is C and a YAML parser is not. A warehouse row
sits between them at 507 ms: its document is already JSON, so it beats local
YAML despite crossing a network.

**Warehouse writes are the expensive operation.** 2.9 s to add one fact to a
40,800-triple row — read the document, rewrite it, and land a conditional
update over the network. Fine at the rate a human or an agent edits a graph;
not something to put in a loop. Batch with `autosave=False` and one `save()`.

Older releases were much slower to open: 0.13.0 took 7.8 s where 0.26.0 takes
992 ms for the same YAML, and warehouse rows were parsed as YAML rather than
JSON, which cost about 400x on its own.

## The SPARQL engine

| | 1-hop | 2-hop join | count all |
|---|---|---|---|
| rdflib | 0.90 ms | 342 ms | 432 ms |
| oxigraph (default) | **0.04 ms** | **52 ms** | **11 ms** |

40,800 triples, graph already built. `pyoxigraph` is a core dependency, so
this is what you get; `TrikeDB(..., sparql_engine="rdflib")` pins the old
engine. Aggregates gain the most (40x) and single lookups the most in
relative terms (23x); a wide join gains least (6.4x) because most of its time
goes into materialising rows either way.

## How to read this

**Up to ~1k triples** (a curated ops graph — the sweet spot this tool
was built for): everything is instant. Agents can read the whole file
into context; humans can read the YAML diff in a PR.

**Up to ~10k triples**: still comfortable. Everything is sub-second,
loading included. The whole-file-in-agent-context pattern stops working
around here — switch agents to `query`/`sparql`/`search` (CLI or MCP)
instead of reading the file.

**~100k triples**: queries stay fast (`query()` 0.2s, `sparql()` 1.1s)
but the file-shaped costs show:

- **load is ~1s as YAML, ~60ms as JSON** — parsing is the wall, and
  choosing the format moves it. Fine either way for a long-lived process
  (`trikedb serve`, MCP server: pay it once); for one-shot CLI calls over a
  big graph, name the file `.json`.
- **autosave costs ~2s per mutation on YAML, ~150ms on JSON** — open with
  `TrikeDB(path, autosave=False)`, batch, `save()` once.
- **semantic `search()` re-embeds the whole graph per query** (the
  no-index design), so it is the one operation still measured in seconds at
  this size. Cheap to 10k; beyond that an embedding cache is the fix
  (roadmap).
- **the HTML renders, but don't** — 15.8 MB with ~29k nodes will hurt
  in a browser. Split into a workspace and filter, or serve the graph
  and query it instead of looking at it.

## The practical ladder

1. **One file, whole-file reads** (≤ ~1k): fetch + read, PR review,
   HTML workbench. No infrastructure.
2. **One file, query access** (~1k–10k): agents use `trikedb query /
   sparql / search` or the stdio MCP server. Same file, no migration.
3. **Served graph** (10k+, or many consumers): `trikedb serve` on the
   file (local, `s3://`, or a `snowflake://` row) — load is paid once,
   everyone queries over REST/MCP. Still the same YAML underneath;
   still diffable, still one document.

The point of the design is that moving up a rung changes *how you
read*, never *what you store* — there is no migration, only a different
door into the same file.

## A finding worth keeping

The first run of this benchmark caught `query()` at O(bindings ×
triples) — a nested-loop join that took 7.3s for a 2-hop join at 7k
triples and effectively hung at 73k. It now pre-filters candidates by
the pattern's constant terms and hash-joins on shared variables:
0.02s at 7k (330×), 0.22s at 73k. Benchmarks are not decoration.
