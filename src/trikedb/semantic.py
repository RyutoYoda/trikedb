"""Deprecated name for :mod:`trikedb.embeddings`.

``semantic`` (embedding search) and ``semantics`` (OWL and SHACL) were one
letter apart and meant unrelated things, which is a coin flip every time
somebody reads an import line. They are now ``embeddings`` and
``reasoning``. This module is kept because `from trikedb import semantic`
is in released code.
"""

from __future__ import annotations

from .embeddings import *          # noqa: F401,F403
from .embeddings import (          # noqa: F401
    DEFAULT_MODEL,
    MAX_CHUNK_CHARS,
    _cache_path,
    _cache_root,
    _embeddings,
    _key,
    _load_model,
    _payload,
    _write_cache,
    preview,
    search,
    sentences,
)
