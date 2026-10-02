# Serving a graph as a remote MCP server

A trikedb graph is a file, and the usual way to put it in front of a model
is to point a local MCP client at it — `trikedb serve graph.yaml`, or the
MCP entry in your client's config. Nothing in here is needed for that.

These are the two shapes that come up when the graph has to be reachable
from somewhere else: a hosted endpoint over HTTPS, for a browser-based
client, a shared team setup, or a graph you want to hand to someone who
will never clone the repository.

| | [`ecs/`](ecs/) | [`cloudflare-worker/`](cloudflare-worker/) |
|---|---|---|
| Graph lives in | a private S3 object | the deployed bundle |
| Writable | yes — agents can add triples | no, read-only |
| Runs | `trikedb serve` in a container | ~400 lines of Python on Pyodide |
| Auth | bearer token or OAuth issuer | bearer token out of the box; OAuth 2.1 via [`AUTH.md`](cloudflare-worker/AUTH.md) |
| Costs | ECS + S3 | nothing, on the free plan |
| Use it when | a team curates one graph together | you are publishing a graph that is already settled |

Both are complete and both have been deployed; neither is a sketch. Copy
the one whose row you recognise and change the names.

Neither bearer token survives contact with a browser-based client:
ChatGPT's custom connectors require OAuth 2.1 with dynamic client
registration and have no field for a static token.
[`cloudflare-worker/AUTH.md`](cloudflare-worker/AUTH.md) covers putting a
real authorization server in front of the Worker without writing one.

They are distributed on GitHub only — `MANIFEST.in` prunes this directory,
so none of it is in the PyPI package. `pip install trikedb` does not need
any of it.
