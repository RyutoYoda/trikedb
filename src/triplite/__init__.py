"""triplite — the SQLite of triple stores.

A knowledge graph that lives in a single YAML file, with a
graph-database interface. Built for LLM agents.
"""

from .db import OntologyError, Triple, TripLite

__version__ = "0.1.0"
__all__ = ["TripLite", "Triple", "OntologyError", "__version__"]
