# Remote MCP on Cloudflare Workers

A trikedb graph served as a remote MCP endpoint from a free Cloudflare
Workers account. No database, no container, no object store, no bill: the
graph ships inside the bundle and the whole server is one Python file.

Compare this with [`mcp/ecs/`](../ecs/), which runs the real
`trikedb serve` against a graph in S3. That one is for a graph several
people write to. This one is for a graph you publish — read-only, small
enough to embed, and in front of whatever model you point at it.

```
src/entry.py          the server: unpack the graph, build it, answer JSON-RPC
src/graphdata.py      the graph, embedded as Python strings (generated)
tools/embed_graph.py  generates the above from a directory of YAML
pyproject.toml        dependencies, minus the one that cannot load here
wrangler.toml         Worker name and entry point
```

## Deploy it

Needs a Cloudflare account, [`uv`](https://docs.astral.sh/uv/), and
`npx`. From this directory:

```bash
python3 tools/embed_graph.py     # bundles examples/graphs/trike by default
uv run pywrangler deploy
```

That publishes the demo graph — a fictional homeware retailer, 567
triples across five member graphs — at
`https://trikedb-mcp.<your-subdomain>.workers.dev`. `GET /` returns a
health check with the triple count; MCP itself is the `POST`.

Then put a token on it, because the deployed default is open:

```bash
npx wrangler secret put AUTH_TOKEN     # reads from stdin
```

To serve your own graph instead, point the embed script at it and
redeploy. If your entry file is not named `trike_workspace.yaml`, change
`GRAPH_FILE` in `src/entry.py` to match, and replace the `instructions`
string in `initialize` — that text is the first thing a model reads about
your graph.

```bash
python3 tools/embed_graph.py path/to/your/graphs
uv run pywrangler deploy
```

## Connecting a client

```bash
claude mcp add --transport http my-graph \
  https://trikedb-mcp.<your-subdomain>.workers.dev/ \
  --header "Authorization: Bearer $AUTH_TOKEN"
```

Some connector UIs cannot attach a header. For those, `_authorized()`
also accepts the token inside the path
(`https://.../<AUTH_TOKEN>/mcp`). It is a real downgrade — the secret
ends up in URL bars, history and logs — so prefer the header, treat a
path token as rotatable, and delete that branch if no client you use
needs it.

## Why it works at all

trikedb's fast query backend, pyoxigraph, is a Rust extension, and
Workers runs Pyodide, which has no place to put one. It loads anyway
because trikedb never required it: `_oxigraph_available()` catches the
`ImportError` and reads fall back to rdflib. pyoxigraph is declared as a
core dependency, though, so resolution has to be told to skip it —
that's the `override-dependencies` line in `pyproject.toml`. What's left
(PyYAML, rdflib, pyparsing) is pure Python.

Three more decisions follow from the host:

**No MCP SDK.** It pulls in uvicorn and starlette, which want sockets
Workers does not have; the import fails before your code runs. Streamable
HTTP is one POST carrying JSON-RPC, so `handle()` answers `initialize`,
`tools/list` and `tools/call` itself, in about a hundred lines. The cost
is that the tool table is written out by hand instead of derived from
decorated functions.

**The graph is a Python module, not a file.** Workers ships code, not
files. Pyodide does provide an in-memory filesystem, so `entry.py` writes
the embedded strings out at import time and opens them normally. Every
YAML in the directory is embedded together, which is what a workspace
needs — the entry file names its members by relative path.

**`search` is not semantic here.** trikedb's real `search` tokenizes
through model2vec, another Rust extension. This one is substring
matching over node names, properties, predicates and objects. The tool
description says so outright, so a model does not assume it got fuzzy
matching and trust a near-miss.

## Things that will bite you

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'workers'` | `npx wrangler deploy` reads neither `requirements.txt` nor `pyproject.toml`, so nothing is bundled | Use `uv run pywrangler deploy`, which resolves dependencies into `python_modules/` and attaches them. Needs `workers-py >= 1.9` |
| `OSError: Randomness is not allowed while a Worker is starting` | Cloudflare executes the entry module at deploy time and snapshots WASM memory, so a random value drawn at startup would be identical across every instance. rdflib's SPARQL parser builds a throwaway `Graph` for its namespace manager, and an unnamed rdflib `Graph` takes a `uuid4` for its identifier | `_warm_up()` swaps `os.urandom` for a counter while it runs the first query, then puts it back. Nothing generated there leaves the process. Dropping the warm-up entirely also works, at the cost of building the graph on the first request after each cold start |
| `pyoxigraph` will not resolve | It is a core dependency, not an extra | The `override-dependencies` line above |
| Empty answers from `search` | It is substring matching, not semantic | Confirm with `match` or `sparql`; see above |

## Measurements

From the deployment this example was derived from, on 2026-10-02, on the
Free plan with a 234-triple graph. Your numbers will differ — this
sample's graph is larger — and these are a snapshot, not a contract.

| | Measured | Documented free limit |
|---|---|---|
| Upload | 10.0 MB (2.3 MB gzipped, 855 modules) | 64 MiB |
| Worker startup | 2,712 ms | 1 s — exceeded, still deployed |
| CPU per request | 3–55 ms (15 of 15 ok) | 10 ms — exceeded, still served |
| Round trip from Japan | 60–110 ms warm, 1.4–1.7 s cold | — |

Startup time and CPU both ran over the published free-tier limits
without being throttled. Do not read that as headroom you are entitled
to: it is what one account saw on one day. If error 1102 (CPU exceeded)
starts appearing, the first thing to cut is large `SELECT` results.

## What this server does not do

It is read-only. trikedb's own MCP server exposes `add_triple`, `act`,
`set_node` and the rest; none of them are here, because a Worker bundle
is immutable — a write would land in the in-memory filesystem and vanish
at the end of the request. A graph that people write to wants
[`mcp/ecs/`](../ecs/) or a local `trikedb serve`.
