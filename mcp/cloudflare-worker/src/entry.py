"""Serve a trikedb graph as a remote MCP server on Cloudflare Workers.

This is the whole deployment: one Python file, a free Workers account, no
database, no container, no object store. The graph travels inside the
bundle, so there is nothing to provision and nothing to pay for.

Three things about this host shape the file, and all three are worth
understanding before you adapt it.

**Workers run Pyodide, so native extensions are out.** trikedb's faster
query backend, pyoxigraph, is a Rust extension and cannot load here. It
does not have to: trikedb catches the ImportError and falls back to
rdflib, which is pure Python. Dropping pyoxigraph from dependency
resolution (see pyproject.toml) leaves PyYAML, rdflib and pyparsing --
pure Python all the way down.

**The MCP Python SDK is out too.** It reaches for uvicorn and starlette,
which open sockets, and Workers has no sockets to open; the import fails
before any of your code runs. That sounds fatal and is not. Streamable
HTTP is a single POST carrying JSON-RPC, so `handle()` below answers
`initialize`, `tools/list` and `tools/call` directly. It is about a
hundred lines.

**Work done at import time is free.** Cloudflare executes the entry
module when you deploy and snapshots the WASM linear memory, so unpacking
the graph and building the RDF projection here costs nothing per request.
The catch is in `_warm_up()`.

To serve your own graph, replace the YAML files and re-run
tools/embed_graph.py. Nothing else here needs to change.
"""

import json
import os
import traceback

from workers import Response, WorkerEntrypoint

import graphdata
from trikedb import TrikeDB

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "trikedb"
GRAPH_DIR = "/graph"
# The entry file among the embedded ones. The sample is a workspace: a
# read-only union naming five member graphs, each of which is a normal
# trikedb file on its own. A single-file graph works the same way -- name
# that file here.
GRAPH_FILE = "trike_workspace.yaml"

# --------------------------------------------------------------- import time

# Workers has no filesystem, but Pyodide gives us an in-memory one. The
# YAML is embedded as Python strings (tools/embed_graph.py builds that
# module); write it out, then open it the way you would anywhere else.
os.makedirs(GRAPH_DIR, exist_ok=True)
for _name, _text in graphdata.FILES.items():
    with open(os.path.join(GRAPH_DIR, _name), "w", encoding="utf-8") as _f:
        _f.write(_text)

DB = TrikeDB(os.path.join(GRAPH_DIR, GRAPH_FILE), read_only=True)


def _warm_up():
    """Build the RDF projection now, so no request has to pay for it.

    One query is enough: trikedb caches the graph it builds, and a
    read-only store never invalidates that cache.

    The guard around it is the awkward part. Workers forbids randomness
    while a Worker is starting -- the startup snapshot is shared by every
    instance, so a random value drawn here would be the *same* value
    everywhere, which is worse than no randomness at all. rdflib's SPARQL
    parser builds a throwaway Graph for its namespace manager, and an
    unnamed rdflib Graph takes a uuid4 for its identifier. That call
    reaches os.urandom and the runtime refuses it.

    So swap in a counter for the duration. Nothing generated here leaves
    the process or carries a secret: these identifiers name in-memory
    graph objects and appear in no output. Skipping the warm-up entirely
    is the alternative, and it is a legitimate choice -- it costs the
    first request after each cold start roughly a tenth of a second on a
    graph this size, and grows from there.
    """
    import itertools

    guarded = os.urandom
    counter = itertools.count(1)
    os.urandom = lambda n: next(counter).to_bytes(n, "big")
    try:
        DB.sparql("SELECT ?s WHERE { ?s ?p ?o } LIMIT 1")
    finally:
        os.urandom = guarded


_warm_up()

# ------------------------------------------------------------------- tools

# The SDK would derive this table from decorated functions. Written out by
# hand it is also the honest description of what this server offers, which
# is not the same set trikedb's own MCP server offers: the write tools are
# absent because the store is read-only, and `search` means something
# different here (see below).
TOOLS = [
    {
        "name": "sparql",
        "description": (
            "Run read-only SPARQL 1.1. The prefix t: is already bound, so "
            "predicates are written t:SHIPPED_FROM. SELECT returns rows, "
            "ASK returns a boolean."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "match",
        "description": (
            "Match triples by pattern. An omitted term is a wildcard and "
            "'*' globs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "s": {"type": "string"},
                "p": {"type": "string"},
                "o": {"type": "string"},
            },
        },
    },
    {
        "name": "get_node",
        "description": (
            "Everything known about one node: its properties and the "
            "triples pointing in and out of it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "search",
        "description": (
            "Substring search over node names, predicates and objects. Use "
            "it to find a name you do not know yet. This is NOT semantic "
            "search -- treat every hit as a guess and confirm it with "
            "match or sparql."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "k": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "ontology",
        "description": (
            "The predicates this graph allows. domain and range are "
            "constraints, not documentation."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "stats",
        "description": "Triple count, node count, and a count per predicate.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _sparql(query):
    result = DB.sparql(query)
    # Update forms return an int and ASK returns a bool. The store is
    # read-only, so only the latter can actually arrive.
    if isinstance(result, (bool, int)):
        return result
    return [{k: (None if v is None else str(v)) for k, v in row.items()}
            for row in result]


def _get_node(name):
    return {
        "name": name,
        # Without this flag, "no such node" and "a node with nothing
        # attached" come back as the same empty answer, and a model will
        # read either one as a fact about the world.
        "exists": name in DB.nodes(),
        "properties": DB.node(name),
        "outgoing": [t.to_dict() for t in DB.triples(s=name)],
        "incoming": [t.to_dict() for t in DB.triples(o=name)],
    }


def _search(query, k=10):
    # trikedb's real search is semantic, via model2vec -- which tokenizes
    # through a Rust extension and so cannot load on Pyodide. Substring
    # matching is what is left. The tool description says so plainly
    # rather than letting a model assume it got the usual behaviour.
    needle = str(query).casefold()
    hits = []
    for node in DB.nodes():
        props = DB.node(node)
        # Match properties as well as the name. Half the obvious first
        # questions about a graph are asked in the vocabulary of its
        # types -- "warehouse", "supplier" -- which live in properties,
        # not in node names. Matching names alone answers those with an
        # empty list, and an empty list reads as "there are none".
        haystack = " ".join([str(node), *map(str, props.keys()),
                             *map(str, props.values())]).casefold()
        if needle in haystack:
            hits.append({"kind": "node", "name": node, "properties": props})
    for t in DB.triples():
        if needle in f"{t.s} {t.p} {t.o}".casefold():
            hits.append({"kind": "triple", **t.to_dict()})
    return hits[: int(k)]


def _ontology():
    return {
        p: ({"description": desc,
             **{k: list(v) for k, v in DB.predicate_rules[p].items()}}
            if p in DB.predicate_rules else desc)
        for p, desc in DB.ontology.items()
    }


def _stats():
    return {
        "triples": len(DB),
        "nodes": len(DB.nodes()),
        "predicates": {p: sum(1 for _ in DB.triples(p=p)) for p in DB.predicates()},
    }


def call_tool(name, args):
    if name == "sparql":
        return _sparql(args["query"])
    if name == "match":
        return [t.to_dict() for t in
                DB.triples(s=args.get("s"), p=args.get("p"), o=args.get("o"))]
    if name == "get_node":
        return _get_node(args["name"])
    if name == "search":
        return _search(args["query"], args.get("k", 10))
    if name == "ontology":
        return _ontology()
    if name == "stats":
        return _stats()
    raise KeyError(f"unknown tool: {name}")


# --------------------------------------------------------------- JSON-RPC

def _result(rpc_id, payload):
    return {"jsonrpc": "2.0", "id": rpc_id, "result": payload}


def _error(rpc_id, code, message):
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


def handle(message):
    """Answer one JSON-RPC message. None means a notification: no body."""
    method = message.get("method")
    rpc_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        # Echo the version the client asked for. Clients in the wild span
        # several revisions of the spec and this server uses nothing that
        # differs between them.
        asked = params.get("protocolVersion")
        return _result(rpc_id, {
            "protocolVersion": asked if isinstance(asked, str) else PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": "0.1.0"},
            # Instructions reach the model before any tool call. Say what
            # the graph covers and how to approach it; the sample text
            # below is about the demo graph, so replace it with yours.
            "instructions": (
                "A read-only knowledge graph about a fictional homeware "
                "and pantry retailer: its catalogue, orders, warehouses, "
                "staff and incidents. Call match or sparql directly when "
                "you know the node name; otherwise start with search to "
                "find candidates and confirm them. If the graph does not "
                "say something, say that it does not -- do not fill the "
                "gap with a guess."
            ),
        })

    if method in ("notifications/initialized", "notifications/cancelled"):
        return None

    if method == "ping":
        return _result(rpc_id, {})

    if method == "tools/list":
        return _result(rpc_id, {"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            payload = call_tool(name, args)
        except Exception as exc:
            # A tool that failed is a result, not a transport error: the
            # model should see the message and get a chance to fix its
            # query rather than watch the connection break.
            return _result(rpc_id, {
                "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
                "isError": True,
            })
        return _result(rpc_id, {
            "content": [{"type": "text",
                         "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
            "structuredContent": payload if isinstance(payload, dict) else {"result": payload},
        })

    if method in ("resources/list", "prompts/list"):
        # Clients probe for these at startup. An empty list is a cleaner
        # answer than "method not found".
        return _result(rpc_id, {method.split("/")[0]: []})

    return _error(rpc_id, -32601, f"method not found: {method}")


JSON_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
}


class Default(WorkerEntrypoint):
    def _authorized(self, request):
        # Open only when you say so, out loud. An earlier version treated
        # an unset AUTH_TOKEN as "open", which is convenient in dev and
        # fails open in the one situation that matters: the moment you put
        # a proxy in front and delete the token, the graph is public until
        # the next deploy. Requiring an explicit flag turns that same
        # mistake into an outage instead.
        if getattr(self.env, "DEV_OPEN", None) == "1":
            return True

        # Cloudflare Access, if it is in front, strips this header from the
        # client and sets it itself on requests it admitted -- so its
        # presence means someone passed the policy. See AUTH.md. Trusting
        # it is sound only while no route reaches this Worker without
        # passing the proxy, which is what workers_dev = false buys.
        email = request.headers.get("cf-access-authenticated-user-email")
        if email:
            allowed = getattr(self.env, "ALLOWED_EMAIL", None)
            return not allowed or email.strip().lower() == allowed.strip().lower()

        token = getattr(self.env, "AUTH_TOKEN", None)
        if not token:
            return False
        header = request.headers.get("authorization") or ""
        if header.strip() == f"Bearer {token}":
            return True
        # Some connector UIs cannot add a header at all. Accepting the
        # token in the path keeps those usable, at the cost of a secret
        # that lands in URLs and logs. Drop this line if every client you
        # care about can send a header.
        return f"/{token}" in request.url

    async def fetch(self, request):
        if request.method == "OPTIONS":
            return Response("", status=204, headers=JSON_HEADERS)

        # Authorize before answering anything, the health check included.
        # A triple count is small, but it is exactly the thing that leaks
        # first when the proxy comes off -- so it should not be the one
        # response that skips the check.
        if not self._authorized(request):
            return Response(json.dumps({"error": "unauthorized"}),
                            status=401, headers=JSON_HEADERS)

        if request.method == "GET":
            # A health check: enough to see the Worker is alive and the
            # graph loaded, and nothing about what is in it.
            return Response(
                json.dumps({"server": SERVER_NAME,
                            "triples": len(DB),
                            "nodes": len(DB.nodes()),
                            "transport": "mcp streamable http (POST)"},
                           ensure_ascii=False),
                headers=JSON_HEADERS,
            )

        try:
            message = json.loads(await request.text())
        except Exception:
            return Response(json.dumps(_error(None, -32700, "parse error")),
                            status=400, headers=JSON_HEADERS)

        try:
            if isinstance(message, list):  # a batch
                out = [r for r in (handle(m) for m in message) if r is not None]
                if not out:
                    return Response("", status=202, headers=JSON_HEADERS)
                body = json.dumps(out, ensure_ascii=False)
            else:
                response = handle(message)
                if response is None:
                    return Response("", status=202, headers=JSON_HEADERS)
                body = json.dumps(response, ensure_ascii=False)
        except Exception:
            # Truncated: a traceback is the fastest way to debug a Worker
            # you cannot attach to, but it should not become the response
            # body in full.
            return Response(
                json.dumps(_error(None, -32603, traceback.format_exc()[-800:])),
                status=500, headers=JSON_HEADERS)

        return Response(body, headers=JSON_HEADERS)
