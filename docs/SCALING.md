# Scaling: where does one YAML file stop being comfortable?

Measured with `benchmarks/scale_bench.py` (synthetic pipeline-shaped
graphs — vendors → jobs → tables, a third of the edges carrying
note/prov attributes) on an Apple-silicon laptop, trikedb 0.13.0:

| triples | file size | load | save | `query()` 2-hop join | `sparql()` | `search()` | `to_html()` | HTML size |
|---|---|---|---|---|---|---|---|---|
| 733 | 34 KB | 0.07s | 0.03s | 0.002s | 0.10s | 0.02s | 0.02s | 0.2 MB |
| 7,333 | 352 KB | 0.72s | 0.31s | 0.02s | 0.09s | 0.14s | 0.15s | 1.6 MB |
| 73,333 | 3.6 MB | 7.8s | 3.3s | 0.22s | 1.1s | 13.5s | 2.3s | 15.8 MB |

## How to read this

**Up to ~1k triples** (a curated ops graph — the sweet spot this tool
was built for): everything is instant. Agents can read the whole file
into context; humans can read the YAML diff in a PR.

**Up to ~10k triples**: still comfortable. Sub-second everything except
load (0.7s). The whole-file-in-agent-context pattern stops working
around here — switch agents to `query`/`sparql`/`search` (CLI or MCP)
instead of reading the file.

**~100k triples**: queries stay fast (`query()` 0.2s, `sparql()` 1.1s)
but the file-shaped costs show:

- **load is ~8s** — YAML parsing is the wall. Fine for a long-lived
  process (`trikedb serve`, MCP server: pay it once), painful for
  one-shot CLI calls.
- **autosave costs 3.3s per mutation** — open with
  `TrikeDB(path, autosave=False)`, batch, `save()` once.
- **semantic `search()` is 13.5s** — it re-embeds the whole graph per
  query (the no-index design). Cheap to 10k; beyond that an embedding
  cache is the fix (roadmap).
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
