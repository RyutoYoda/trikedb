"""triplite — the DuckDB of graph databases.

A knowledge graph that lives in a single YAML file, queried and
updated with full SPARQL 1.1. Built for LLM agents.
"""

from .db import OntologyError, Triple, TripLite

__version__ = "0.6.0"
__all__ = ["TripLite", "Triple", "OntologyError", "__version__"]
