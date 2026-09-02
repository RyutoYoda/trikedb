# Changelog

Notable changes, newest first. Versions before 0.30.0 are in the
[commit history](https://github.com/RyutoYoda/trikedb/commits/main).

## 0.35.0

- **`ASK` was not answered by the engine it reported.** pyoxigraph returns
  `QueryBoolean`, not `bool`, so the `isinstance` check missed every `ASK`
  and fell through to rdflib — which also evicted the oxigraph store from
  the one-entry graph cache, so the next read rebuilt it. One `ASK` cost
  ~100 ms instead of ~0.1 ms. The answers were always right, which is why
  it went unnoticed.
- **`CONSTRUCT` and `DESCRIBE` raised `TypeError`.** They answer with a
  graph, so rdflib's `result.vars` is `None` and the binding loop failed on
  it — on both engines. They now return `{s, p, o}` rows, the shape a triple
  has everywhere else.
- **Added `trike find`.** `find` existed in the Python API and in MCP but
  had no CLI subcommand, so the project's own parity rule was documented
  and broken at the same time.
- Docs: the layer diagram paired each projection with one interface, which
  read as "oxigraph is only for MCP". Oxigraph answers every read query,
  whichever interface asked.
- Docs: the `6–40x` speed claim had no source. Replaced with a measurement
  (7–47x on 8,000 triples, by query shape).

## 0.34.0 — input validation

Malformed input used to become an empty graph without a word. Now refused,
with a message that names the file and the key:

- a workspace member that does not exist (a typo dropped a whole graph out
  of the union and every query just returned less)
- `graphs:` with no members
- a URL whose scheme no backend handles (`s2://…` became a local file by
  that name)
- `triples:` / `nodes:` / `graphs:` / `ontology:` of the wrong type
- YAML syntax errors now name the file — PyYAML only says
  `<unicode string>`, which is no help in a workspace of five members
- a triple term that is `None` or empty. `str(None)` is `"None"`, so a graph
  grew a node by that name and every missing value joined through it
- `query([])` — a join over nothing returns one empty row, a true answer to
  a question nobody meant to ask
- an unknown `sparql_engine` name
- `get_node` / `trike node` now report `exists`, so "no such node" and "a
  node with nothing on it" stop looking identical

The CLI turns `SyntaxError` and `OSError` into `error: …` instead of a
traceback.

## 0.33.2, 0.33.3 — the workbench page

- **Every node label was invisible.** vis rewrites any `scaling` object
  passed to it and leaves the label with a NaN font size, so every box drew
  with 0 px of text at every zoom. Shipped that way from 0.31.2; the
  published demo pages were blank boxes too.
- Labels now keep drawing when you zoom out far enough to see the whole
  graph, and appear without needing a click first.

## 0.33.0, 0.33.1

- `trike ui generate` writes the page; `trike ui` opens it. `trikedb html`
  still works for pipelines that spell it out.
- Removed the setuptools license warning at build time.

## 0.32.0, 0.32.1

- `trike ui` opens the graph in a browser, and picks up the graph in the
  current directory without being told.
- Fixed `trike ui` stopping in a directory that contains a workspace.

## 0.31.0 – 0.31.2

- Japanese node names work in SPARQL: names are percent-escaped into IRIs,
  so `SELECT ?s WHERE { ?s t:担当 t:担当A }` runs.
- Force-directed layout no longer settles nodes on top of each other.

## 0.30.0 – 0.30.2

Fixes from running a real 28,000-triple graph:

- `search()` re-embedded the whole graph on every call — vectors are now
  cached per sentence, in a cache directory rather than beside the graph.
- `add()` with autosave rewrote the file per triple, making bulk import
  quadratic. `with db.batch():` writes once.
- `set_node` silently overwrote a node's `type`; it now refuses unless
  `replace=True`.
- Long node properties came back whole through `search`/`find`/MCP (one hit
  returned 540,557 characters). They are previewed; `get_node` still returns
  the full value.
- Flow layout no longer stretches to 13,920 px on a graph with rework loops.
