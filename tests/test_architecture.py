"""The layering, declared — and enforced the way trikedb enforces an ontology.

A dependency diagram in a document is a wish. This file is the diagram,
and it fails the build when the code stops matching it: a module may only
import from a layer strictly below its own, and every module has to be
placed in a layer on purpose. Adding a file without a layer is the same
mistake as adding a predicate without a declaration — the thing this
project exists to argue against.

Only *import-time* dependencies count. An import inside a function is how
an optional adapter stays optional and how the core avoids carrying its
own presentation around, so `db.to_html()` importing `html` when it is
called is the fix, not the violation.
"""
import ast
import os

import pytest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "src", "trikedb")

#: Bottom to top. A module sees only what is strictly beneath it.
LAYERS = {
    # 0 — data, and infrastructure with nothing under it.
    "model": 0,          # Triple and the shared helpers: what a fact *is*
    "storage_sql": 0,    # bytes in a warehouse row
    "oauth": 0,          # tokens; knows nothing about graphs
    "templates": 0,      # starting graphs, as text; imports nothing
    # 1 — what the document means, and where the bytes live.
    "storage": 1,        # bytes, wherever they live
    "rules": 1,          # domain / range / requires / by
    "rdf": 1,            # the RDF projection
    "reasoning": 1,      # OWL-RL and SHACL over that projection
    # 2 — read the whole document and say something about it.
    "audit": 2,
    "persistence": 2,
    # 3 — the store itself. Everything above is someone using it.
    "db": 3,
    # 4 — presentation and adapters. Deliberately *above* the core: the
    #     graph must not depend on the page that draws it, on the file
    #     formats it can be built from, or on an embedding model.
    "html": 4,
    "importers": 4,
    "embeddings": 4,
    # 5 — entry points.
    "cli": 5,
    "mcp_server": 5,
    "serve": 5,
    # 6 — compatibility shims that only re-export.
    "semantic": 6,
    "semantics": 6,
}


def modules():
    return sorted(f[:-3] for f in os.listdir(SRC)
                  if f.endswith(".py") and f != "__init__.py")


def import_time_deps(module):
    """Sibling modules imported at module level — not inside a function."""
    tree = ast.parse(open(os.path.join(SRC, module + ".py")).read())
    known, found = set(modules()), set()
    for node in tree.body:                       # top level only, on purpose
        if isinstance(node, ast.ImportFrom):
            base = (node.module or "").split(".")[-1]
            if base in known:
                found.add(base)
            found |= {a.name for a in node.names if a.name in known}
        elif isinstance(node, ast.Import):
            found |= {a.name.split(".")[-1] for a in node.names
                      if a.name.startswith("trikedb")
                      and a.name.split(".")[-1] in known}
    return found - {module}


def test_every_module_is_placed_in_a_layer():
    missing = sorted(set(modules()) - set(LAYERS))
    assert not missing, (
        f"{missing} has no layer. Decide where it sits before it is imported "
        "from somewhere it should not be — that decision is the architecture."
    )
    stale = sorted(set(LAYERS) - set(modules()))
    assert not stale, f"{stale} is in LAYERS but no longer exists"


@pytest.mark.parametrize("module", modules())
def test_a_module_imports_only_from_below(module):
    here = LAYERS[module]
    for dep in sorted(import_time_deps(module)):
        assert LAYERS[dep] < here, (
            f"{module} (layer {here}) imports {dep} (layer {LAYERS[dep]}) at "
            f"import time. Move it inside the function that needs it, or the "
            f"dependency is pointing the wrong way."
        )


def test_the_core_does_not_import_its_own_presentation():
    """The specific edge that was there, named so it cannot come back quietly.

    `db.py` imported `html` at the top: the graph could not be loaded
    without loading the page that draws it. It is `db.to_html()` that needs
    it, and that is where it is imported now.
    """
    assert "html" not in import_time_deps("db")
    assert "embeddings" not in import_time_deps("db")
    assert "importers" not in import_time_deps("db")


def test_there_are_no_import_cycles():
    graph = {m: import_time_deps(m) for m in modules()}
    state, cycle = {}, []

    def walk(node, path):
        if state.get(node) == "done":
            return
        if state.get(node) == "open":
            cycle.append(path[path.index(node):] + [node])
            return
        state[node] = "open"
        for nxt in sorted(graph[node]):
            walk(nxt, path + [nxt])
        state[node] = "done"

    for module in modules():
        walk(module, [module])
    assert not cycle, "import cycle: " + " -> ".join(cycle[0])
