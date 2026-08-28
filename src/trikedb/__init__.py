"""trikedb — the single-file graph database.

A knowledge graph that lives in one YAML file, queried and
updated with full SPARQL 1.1. Built for LLM agents.
"""

from .db import OntologyError, Triple, TrikeDB

__version__ = "0.31.0"
__all__ = ["TrikeDB", "Triple", "OntologyError", "__version__"]
