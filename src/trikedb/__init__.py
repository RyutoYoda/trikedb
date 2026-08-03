"""trikedb — the DuckDB of graph databases.

A knowledge graph that lives in a single YAML file, queried and
updated with full SPARQL 1.1. Built for LLM agents.
"""

from .db import OntologyError, Triple, TrikeDB

__version__ = "0.8.1"
__all__ = ["TrikeDB", "Triple", "OntologyError", "__version__"]
