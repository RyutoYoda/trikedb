"""YAML string <-> TrikeDB.

trikedb reads from a path, so this goes through a temporary file. That is
exactly why it is not in `domain`: turning a string into a graph is a
library detail, not a rule of the business, and it belongs on this side of
the boundary.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from trikedb import TrikeDB


def load(text: str) -> TrikeDB:
    """Read a YAML string into a graph with nowhere to save itself.

    `autosave=False` guards against accidents: this graph's file is a
    temporary one, so a stray save accomplishes nothing — and a save that
    accomplishes nothing is a save nobody notices.
    """
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "graph.yaml"
        path.write_text(text, encoding="utf-8")
        return TrikeDB(path, autosave=False)


def dump(db: TrikeDB) -> str:
    """Render the graph as YAML fit to commit.

    trikedb rewrites the file, so comments and ordering from the original
    are lost. The first time a hand-written YAML goes through this path the
    diff is large; that happens once, and every diff after it is honest.
    """
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "graph.yaml"
        db.save(path)
        return path.read_text(encoding="utf-8")
