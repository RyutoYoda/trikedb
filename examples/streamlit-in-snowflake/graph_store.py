"""Open the knowledge graph from inside Streamlit in Snowflake.

trikedb is a self-contained graph database: given pyyaml and rdflib -- both
of which are in Snowflake's Anaconda channel -- it runs real SPARQL and
pattern queries with **zero egress**. trikedb itself is not in that channel,
so the app stages a copy of the package next to itself and puts it on
`sys.path` (see `_VENDOR` below and the README section on deployment).

There are two ways to open the graph, and the app tries them in that order:

  1. `open_snowflake()` -- read the rows of a table that holds the graphs.
     Whatever regenerates that table from the YAML in git is the thing that
     keeps it current; this side only reads.
  2. `open_local()` -- open the YAML checkout directly, for running the app
     on your laptop.

Either way the result is a read-only union: several graphs stacked into one
view, which is what the screens query.
"""
from __future__ import annotations

import glob
import os
import sys

import yaml

# Make the staged copy of trikedb importable. Keep this shim above the
# `import trikedb` below -- and if you add a module to the vendored package,
# stage the whole directory with a wildcard rather than listing files. A
# listed file that someone forgets to add deploys "successfully" as an app
# that raises ImportError halfway through a write.
_VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")
if os.path.isdir(_VENDOR) and _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

import trikedb  # noqa: E402

# --------------------------------------------------------------- change these
#: One row per graph. The source of truth is the YAML in git; these rows are
#: a derived copy that something pushes in. Do not write to them from the
#: app -- the next deploy overwrites whatever you wrote, silently.
SNOWFLAKE_TABLE = "DEMO_DB.KG.TRIKE_GRAPHS"
#: Rows are named `<prefix>/<graph>`, so one table can hold several graphs.
GRAPH_PREFIX = "demo"
# -----------------------------------------------------------------------------


def open_local(base_dir: str):
    """Open the YAML checkout: `workspace.yaml` if present, else the directory."""
    ws = os.path.join(base_dir, "workspace.yaml")
    return trikedb.TrikeDB(ws if os.path.exists(ws) else base_dir)


def _rows(session, sql: str) -> list:
    """Run one statement against either a DB-API connection or a Snowpark
    session. Decided by what the object can do, not by what type it is --
    Streamlit in Snowflake hands you Snowpark, your laptop hands you DB-API."""
    if hasattr(session, "cursor"):
        cur = session.cursor()
        try:
            cur.execute(sql)
            return list(cur.fetchall())
        finally:
            cur.close()
    return [tuple(r) for r in session.sql(sql).collect()]


def graph_names(session, table: str = SNOWFLAKE_TABLE,
                prefix: str = GRAPH_PREFIX) -> list:
    """Discover the graph names from the rows. Never hardcode the list.

    A hardcoded list of file or graph names rots the moment someone adds
    one, and it rots quietly: the new graph simply isn't there. The rows are
    authoritative, so ask the rows.
    """
    names = [r[0].split("/", 1)[1] for r in
             _rows(session, f"SELECT name FROM {table} "
                            f"WHERE name LIKE '{prefix}/%' ORDER BY name")
             if "/" in r[0]]
    return [n for n in names if n != "workspace"]  # no row for the union


def open_snowflake(session, table: str = SNOWFLAKE_TABLE,
                   prefix: str = GRAPH_PREFIX,
                   workspace: str = "kg/workspace.yaml"):
    """Open the rows as a trikedb workspace union.

    The union semantics -- the `graph` attribute on a triple is the
    workspace key, node attributes are first-wins *per key*, identical
    triples are not deduplicated -- are defined by trikedb's implementation.
    Hand-rolling a union here produces something subtly different: the first
    attempt at this merged node attributes dict-at-a-time, which dropped the
    `description` of a node declared in two graphs. It surfaced only as a
    `content_hash` mismatch against the YAML path.

    So the union is not hand-rolled. The members are rewritten as
    `snowflake://` URLs into a temporary workspace file and trikedb opens
    that (members of a union inherit the connection). No union row is
    written back to the table -- one would double-count every node and edge,
    so a naive `COUNT(*)` would return twice the real number.

    The staged `workspace.yaml` decides the membership and its order. If a
    row is missing, raise: a graph silently missing makes answers quietly
    incomplete, which is worse than an error.
    """
    import tempfile

    members = (workspace_members(workspace)
               or {n: n for n in graph_names(session, table, prefix)})
    if not members:
        raise RuntimeError(f"no {prefix}/* rows in {table}")
    found = set(graph_names(session, table, prefix))
    missing = [g for g in members.values() if g not in found]
    if missing:
        raise RuntimeError(
            f"graphs missing from {table}: {missing} "
            "(they are in the staged workspace.yaml)")

    doc = {"graphs": {key: f"snowflake://{table}/{prefix}/{name}"
                      for key, name in members.items()}}
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False,
                                     encoding="utf-8") as fh:
        yaml.dump(doc, fh, allow_unicode=True, sort_keys=False)
        ws_path = fh.name
    return trikedb.TrikeDB(ws_path, connection=session, read_only=True)


def workspace_members(path: str) -> dict:
    """Return `workspace.yaml`'s `graphs:` as `{key: graph name}`, in order.

    `curation.py` also uses this for the list of YAML files that accept
    proposals. Enumerating them separately over there would produce a file
    that is in `workspace.yaml` but invisible from the screen -- a drift
    nobody would notice.

    The key becomes the `graph` attribute on triples, and the order decides
    first-wins for node attributes, so use what `workspace.yaml` says rather
    than deriving keys mechanically from file names.
    """
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    return {str(k): os.path.splitext(os.path.basename(str(v)))[0]
            for k, v in (doc.get("graphs") or {}).items()}


def predicate_defs(base_dir: str) -> dict:
    """Collect predicate definitions (`USES_ROLE` -> "bot user -> role") from
    the YAML files. Used as a fallback when the opened graph carries none.

    Read the `ontology:` section directly: trikedb does not return the
    definition strings through its query API.
    """
    defs: dict = {}
    for f in sorted(glob.glob(os.path.join(base_dir, "*.yaml"))):
        if os.path.basename(f) == "workspace.yaml":
            continue
        with open(f, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh) or {}
        for name, d in ((doc.get("ontology") or {}).get("predicates", {}) or {}).items():
            defs.setdefault(name, d)  # first wins
    return defs


def schema(db, base_dir: str | None = None) -> dict:
    """The predicate definitions and node names the curation screen offers.

    Nodes are narrowed to things you can actually query: declared nodes
    (those with attributes) plus anything that appears as a subject. A
    predicate like `AFFECTED_BY` often has a long free-text object, and
    offering those as node names fills the dropdown with sentences.
    """
    queryable = {n for n in db.nodes() if db.node(n)} | set(db.subjects())
    defs = dict(db.ontology) or (predicate_defs(base_dir) if base_dir else {})
    return {"predicate_defs": defs, "nodes": sorted(queryable)}
