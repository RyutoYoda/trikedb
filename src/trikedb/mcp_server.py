"""MCP server: expose a trikedb graph as an ontology layer for AI agents.

Run with `trikedb mcp graph.yaml` (stdio transport). The graph opens
with autosave, so every write an agent makes lands in the YAML file
immediately — reviewable as a plain git diff. The ontology, if the
file declares one, is enforced on every write, which is what makes
this safe as a shared context layer: agents can extract facts from
documents and push them here, but they cannot invent predicates.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Union

from . import rules
from .db import TrikeDB
from .storage import ConcurrentWriteError, is_remote


def _transport_security(public_url):
    """Trust the public hostname too, on top of the SDK's localhost defaults."""
    if not public_url:
        return None
    from urllib.parse import urlparse

    from mcp.server.transport_security import TransportSecuritySettings

    netloc = urlparse(str(public_url)).netloc
    host = netloc.split(":")[0]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        # Exact entry covers the default-port case (Host: example.com), the
        # ":*" pattern covers an explicit port (Host: example.com:8443).
        allowed_hosts=[netloc, f"{host}:*", "127.0.0.1:*", "localhost:*", "[::1]:*"],
        allowed_origins=[
            f"https://{netloc}", f"https://{host}:*",
            "http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*",
        ],
    )


def _identity(actor_claim=None):
    """Who is calling, as the token says — or None if nothing says.

    The MCP SDK puts the verified token in a context variable for the
    duration of the request, which is the only place the tool functions
    can reach it from: FastMCP calls them with the arguments the client
    sent and nothing else.

    None is the honest answer for every transport that has no user behind
    it — stdio (authenticated by the OS), a static ``--token`` (a shared
    secret names nobody), and library use. The write path then leaves
    ``by`` alone, exactly as it always has.

    A configured ``actor_claim`` that the token does not carry raises
    rather than quietly falling back to ``sub``: the fallback would sign
    actions with a different kind of name than the graph was set up for,
    and only some of the time. A misconfiguration should fail on the
    first request, not on the first token that happens to be thin.
    """
    try:
        from mcp.server.auth.middleware.auth_context import get_access_token
    except ImportError:  # pragma: no cover - older SDKs carry no auth context
        return None
    token = get_access_token()
    if token is None:
        return None
    if not actor_claim:
        return getattr(token, "subject", None) or None
    value = (getattr(token, "claims", None) or {}).get(actor_claim)
    if value in (None, ""):
        raise ValueError(
            f"this token carries no {actor_claim!r} claim, so there is "
            f"nobody to sign an action as — check --actor-claim against "
            f"what your IdP actually issues"
        )
    return str(value)


def build_server(
    path: Union[str, Path], auth=None, public_url=None, stateless: bool = False,
    graph=None, actor_claim=None,
):
    """The MCP server. ``auth`` is an (AuthSettings, TokenVerifier) pair from
    ``trikedb.oauth.build_auth`` — pass it to require OAuth 2.1 on HTTP
    transports, leave it None for stdio (which authenticates via the OS).

    ``public_url`` is the address clients actually reach this server at. The
    SDK's DNS-rebinding guard only trusts localhost by default, so a server
    behind a proxy or tunnel must declare its public hostname or every
    request arrives with an untrusted Host header and is refused with 421.

    ``actor_claim`` names the JWT claim to take the acting identity from
    (default: ``sub``). Under OAuth the actor is the token's, not the
    caller's to choose — see ``rules.signed_by`` — so ``by`` on a write
    is filled in from here and a borrowed one is refused.

    ``stateless`` drops session tracking: each request is served on its own
    transport, so clients need not echo the ``Mcp-Session-Id`` header back and
    any replica can answer any request. Required for clients that don't carry
    the session forward, and for running more than one replica behind a load
    balancer — a session lives in one process's memory, so a second replica
    would reject it. Nothing these tools do needs the session, so SSE
    resumability is the only thing given up.

    Note that the graph is opened once, here, and the tools share that one
    instance for the life of the server — they do not re-read the file per
    request. Two processes serving the same file each hold their own copy and
    will not see each other's writes."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "MCP support requires the mcp package - pip install 'trikedb[mcp]'"
        ) from exc

    # Only a local file has a mode to check. Path() on a URL yields a
    # nonsense relative path whose exists() is False, so this guard used to
    # be silently inert for every remote graph rather than skipped on purpose.
    if not is_remote(path):
        p = Path(path)
        if p.exists() and not p.stat().st_mode & 0o200:
            raise PermissionError(f"{path} is read-only; MCP server needs write access")
    db = graph if graph is not None else TrikeDB(path, autosave=True)

    from functools import wraps

    def caller():
        """The acting identity as a node in *this* graph, or None."""
        who = _identity(actor_claim)
        return rules.actor_of(db, who) if who else None

    def serialized(fn):
        """One call at a time, and each one knowing who made it.

        The actor is bound here rather than on the four write tools
        because this is the wrapper none of them can be written without.
        A guard you have to remember to apply is one that eventually
        gets left off a new tool, and the tool that forgets it is the
        hole. Under the lock, so the one shared instance never carries
        another caller's identity into this one's write.
        """
        @wraps(fn)
        def call(*args, **kwargs):
            with db._lock:
                db._actor = caller()
                try:
                    return fn(*args, **kwargs)
                finally:
                    db._actor = None
        return call
    settings, verifier = auth if auth else (None, None)

    #: Longest a single retry will sleep. The delay doubles up to here and
    #: then stops: uncapped, the tries that actually matter get pushed out to
    #: minutes, which is why raising the attempt count alone does not help.
    BACKOFF_CAP = 1.0

    def write(mutate, attempts: int = 14):
        """Apply one mutation, losing the race gracefully.

        With the graph on shared storage, another writer can land between our
        read and our save; the save then refuses rather than overwriting them.
        Every write tool is a single self-contained mutation, so recovery is
        just: take their version, do ours again on top. Without this the agent
        sees a storage error it has no way to act on.

        Retries back off with jitter. Contended writers all wake at the same
        moment otherwise, and collide again for the same reason they collided
        the first time.

        The budget is generous because a warehouse needs it to be. On S3 the
        contention is per object, so writers to different graphs never meet;
        a warehouse serialises DML per *table*, and one table holds many
        graphs, so they queue behind each other by design. Measured with ten
        concurrent writers on one row, eight attempts was exactly enough and
        sometimes one short — no margin at all. Capped backoff buys many more
        tries for less total waiting than doubling ever could.
        """
        import random
        import time

        for attempt in range(attempts):
            try:
                return mutate()
            except ConcurrentWriteError:
                if attempt == attempts - 1:
                    raise
                time.sleep(random.uniform(0, min(0.05 * 2**attempt, BACKOFF_CAP)))
                db.reload()  # their save won; re-apply ours on top of it

    server = FastMCP(
        "trikedb",
        auth=settings,
        token_verifier=verifier,
        transport_security=_transport_security(public_url),
        stateless_http=stateless,
        instructions=(
            f"Knowledge graph stored in {path}. Read with sparql/match/get_node, "
            "write with add_triple/set_node/import_source. Call ontology() before "
            "adding facts: predicates outside the declared ontology are rejected. "
            "When extracting facts from documents, add each as a triple and put "
            "supporting detail (URLs, dates, notes) in attrs/props."
        ),
    )

    @server.tool()
    @serialized
    def sparql(query: str) -> Any:
        """Run SPARQL 1.1 against the graph. Prefix t: is pre-bound (write t:PROVIDES).

        SELECT returns rows, ASK returns a bool. Update forms (INSERT DATA,
        DELETE WHERE, ...) mutate the graph, persist to the YAML file, and
        return the net change in triple count."""
        return write(lambda: db.sparql(query))

    @server.tool()
    @serialized
    def search(query: str, k: int = 10, model: Optional[str] = None) -> list:
        """Semantic search: rank facts by meaning, not spelling.

        Use this for fuzzy questions ("認証まわりの注意点", "what feeds the
        cost dashboard?") where you don't know the exact node names to
        match or SPARQL over. Returns scored triples and nodes. Requires
        the [semantic] extra on the server side.

        `model` names a model2vec model to use instead of the default
        multilingual one — a Transformer encoder cannot be passed here,
        because the embedding path is deliberately torch-free."""
        return db.search(query, k=k, model=model)

    @server.tool()
    @serialized
    def find(question: str, where: Optional[dict] = None, k: int = 10,
             model: Optional[str] = None) -> list:
        """Hybrid retrieval: semantic recall + a hard structured filter.

        The one-call version of "search, then narrow": recall candidate
        nodes by meaning, then keep only those whose properties match
        `where` (e.g. {"type": "table", "pii": true}). Returns each match
        with its properties and outgoing facts — a ready-to-use payload.
        Prefer this over search when you can name the hard constraints.
        Requires the [semantic] extra on the server side. `model` overrides
        the embedding model, as on `search`."""
        return db.find(question, where=where, k=k, model=model)

    @server.tool()
    @serialized
    def match(
        s: Optional[str] = None, p: Optional[str] = None, o: Optional[str] = None
    ) -> list:
        """Pattern-match triples. Omitted terms are wildcards; '*' globs.

        Returns each triple with its attributes."""
        return [t.to_dict() for t in db.triples(s=s, p=p, o=o)]

    @server.tool()
    @serialized
    def add_triple(s: str, p: str, o: str, attrs: Optional[dict] = None) -> dict:
        """Add (or upsert) one fact. Rejected if p is outside the ontology.

        Same (s, p, o) merges attrs. Use attrs for provenance and detail:
        source URL, date, schedule, deprecated, note...

        For something that *happened* — you changed a table, ran a job,
        deprecated a feed — call `act` instead, so the node ends up in its
        new state and the record of the change cannot go missing."""
        return write(lambda: db.add(s, p, o, **(attrs or {})).to_dict())

    @server.tool()
    @serialized
    def act(s: str, p: str, o: str, state: Optional[str] = None,
            by: Optional[str] = None, at: Optional[str] = None,
            attrs: Optional[dict] = None) -> dict:
        """Record that you did something to node `s`, and move it to its new state.

        `o` is what happened in words, `state` the state it leaves `s` in,
        `by` who did it, `at` when (omit it and now is stamped). On a
        server that authenticates you, `by` is your own identity whether
        you pass it or not, and passing somebody else's is refused — so
        leave it out unless you are recording what a third party did on
        an unauthenticated transport. The event
        is appended, never merged: doing the same thing twice leaves two
        records. Use this whenever you change something the graph
        describes — reading back `get_node(s)` then shows the new state
        and `history(s)` shows how it got there."""
        return write(lambda: db.act(s, p, o, state=state, by=by, at=at,
                                    **(attrs or {})).to_dict())

    @server.tool()
    @serialized
    def history(name: str) -> dict:
        """What has happened to a node, newest first, and the state it is in now."""
        return {
            "name": name,
            "state": db.state(name),
            "events": [t.to_dict() for t in db.history(name)],
        }

    @server.tool()
    @serialized
    def remove_triples(
        s: Optional[str] = None, p: Optional[str] = None, o: Optional[str] = None
    ) -> int:
        """Remove all triples matching the pattern (at least one term required).

        Returns how many were removed."""
        if s is None and p is None and o is None:
            raise ValueError("refusing to remove everything: give at least one of s/p/o")
        return write(lambda: db.remove(s=s, p=p, o=o))

    @server.tool()
    @serialized
    def set_node(name: str, props: dict, replace: bool = False) -> dict:
        """Attach (merge) free-form properties onto a node.

        Conventional keys: type (color grouping), label, url, description.
        Properties are queryable in SPARQL, e.g. ?x t:type "table".
        Changing the type of a node that already has one is refused unless
        replace=true: two different things sharing a name would otherwise
        silently overwrite each other."""
        return write(lambda: db.set_node(name, replace=replace, **props))

    @server.tool()
    @serialized
    def get_node(name: str) -> dict:
        """Everything known about a node: properties plus its outgoing and incoming triples."""
        return {
            "name": name,
            # Without this an agent cannot tell "no node by that name" from
            # "a node with nothing attached", and both read as an answer.
            "exists": name in db.nodes(),
            "properties": db.node(name),
            "outgoing": [t.to_dict() for t in db.triples(s=name)],
            "incoming": [t.to_dict() for t in db.triples(o=name)],
        }

    @server.tool()
    @serialized
    def ontology() -> dict:
        """The allowed predicates. Empty means free-form.

        A predicate with `domain`/`range` is enforced, not documented: an
        edge written between the wrong node types is refused, so read this
        before writing rather than after being rejected."""
        return {
            p: ({"description": desc,
                 **{k: list(v) for k, v in db.predicate_rules[p].items()}}
                if p in db.predicate_rules else desc)
            for p, desc in db.ontology.items()
        }

    @server.tool()
    @serialized
    def stats() -> dict:
        """Graph summary: triple/node counts and triples per predicate."""
        return {
            "path": str(db.path),
            "triples": len(db),
            "nodes": len(db.nodes()),
            "predicates": {
                p: sum(1 for _ in db.triples(p=p)) for p in db.predicates()
            },
        }

    @server.tool()
    @serialized
    def import_source(file_path: str) -> int:
        """Merge triples from a CSV/TSV file, Markdown document (s/p/o tables), or another YAML graph.

        Deterministic parsing, ontology enforced. Returns how many triples were added."""
        return write(lambda: db.import_file(file_path))

    return server


def serve(path: Union[str, Path]) -> None:
    """Blocking entry point: serve the graph over stdio."""
    build_server(path).run()
