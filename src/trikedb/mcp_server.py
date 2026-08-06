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

from .db import TrikeDB


def build_server(path: Union[str, Path]):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:  # pragma: no cover
        raise ImportError(
            "MCP support requires the mcp package — pip install 'trikedb[mcp]'"
        ) from None

    p = Path(path)
    if p.exists() and not p.stat().st_mode & 0o200:
        raise PermissionError(f"{path} is read-only; MCP server needs write access")
    db = TrikeDB(path, autosave=True)
    server = FastMCP(
        "trikedb",
        instructions=(
            f"Knowledge graph stored in {path}. Read with sparql/match/get_node, "
            "write with add_triple/set_node/import_source. Call ontology() before "
            "adding facts: predicates outside the declared ontology are rejected. "
            "When extracting facts from documents, add each as a triple and put "
            "supporting detail (URLs, dates, notes) in attrs/props."
        ),
    )

    @server.tool()
    def sparql(query: str) -> Any:
        """Run SPARQL 1.1 against the graph. Prefix t: is pre-bound (write t:PROVIDES).

        SELECT returns rows, ASK returns a bool. Update forms (INSERT DATA,
        DELETE WHERE, ...) mutate the graph, persist to the YAML file, and
        return the net change in triple count."""
        return db.sparql(query)

    @server.tool()
    def search(query: str, k: int = 10) -> list:
        """Semantic search: rank facts by meaning, not spelling.

        Use this for fuzzy questions ("認証まわりの注意点", "what feeds the
        cost dashboard?") where you don't know the exact node names to
        match or SPARQL over. Returns scored triples and nodes. Requires
        the [semantic] extra on the server side."""
        return db.search(query, k=k)

    @server.tool()
    def match(
        s: Optional[str] = None, p: Optional[str] = None, o: Optional[str] = None
    ) -> list:
        """Pattern-match triples. Omitted terms are wildcards; '*' globs.

        Returns each triple with its attributes."""
        return [t.to_dict() for t in db.triples(s=s, p=p, o=o)]

    @server.tool()
    def add_triple(s: str, p: str, o: str, attrs: Optional[dict] = None) -> dict:
        """Add (or upsert) one fact. Rejected if p is outside the ontology.

        Same (s, p, o) merges attrs. Use attrs for provenance and detail:
        source URL, date, schedule, deprecated, note..."""
        return db.add(s, p, o, **(attrs or {})).to_dict()

    @server.tool()
    def remove_triples(
        s: Optional[str] = None, p: Optional[str] = None, o: Optional[str] = None
    ) -> int:
        """Remove all triples matching the pattern (at least one term required).

        Returns how many were removed."""
        if s is None and p is None and o is None:
            raise ValueError("refusing to remove everything: give at least one of s/p/o")
        return db.remove(s=s, p=p, o=o)

    @server.tool()
    def set_node(name: str, props: dict) -> dict:
        """Attach (merge) free-form properties onto a node.

        Conventional keys: type (color grouping), label, url, description.
        Properties are queryable in SPARQL, e.g. ?x t:type "table"."""
        return db.set_node(name, **props)

    @server.tool()
    def get_node(name: str) -> dict:
        """Everything known about a node: properties plus its outgoing and incoming triples."""
        return {
            "name": name,
            "properties": db.node(name),
            "outgoing": [t.to_dict() for t in db.triples(s=name)],
            "incoming": [t.to_dict() for t in db.triples(o=name)],
        }

    @server.tool()
    def ontology() -> dict:
        """The allowed predicates with their descriptions. Empty means free-form."""
        return dict(db.ontology)

    @server.tool()
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
    def import_source(file_path: str) -> int:
        """Merge triples from a CSV/TSV file, Markdown document (s/p/o tables), or another YAML graph.

        Deterministic parsing, ontology enforced. Returns how many triples were added."""
        return db.import_file(file_path)

    return server


def serve(path: Union[str, Path]) -> None:
    """Blocking entry point: serve the graph over stdio."""
    build_server(path).run()
