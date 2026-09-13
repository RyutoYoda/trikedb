"""Deprecated name for :mod:`trikedb.reasoning`.

See the note in :mod:`trikedb.semantic`: the two names were one letter
apart and meant unrelated things. Kept because `from trikedb import
semantics` is in released code.
"""

from __future__ import annotations

from .reasoning import *           # noqa: F401,F403
from .reasoning import (           # noqa: F401
    OWL_CHARACTERISTICS,
    OWL_INVERSE_OF,
    RDF_TYPE,
    RDFS,
    declare,
    infer,
    validate,
)
