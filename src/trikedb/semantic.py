"""Semantic (embedding) search over the graph — the optional [semantic] extra.

Keyword search finds what you can spell; semantic search finds what you
mean ("認証まわりの注意点" hits keypair/MFA/token facts without sharing a
single word). Embeddings are static (model2vec) — no torch, no GPU, and
encoding is fast enough to embed the whole graph per query, so there is
no index to build or invalidate.
"""

from __future__ import annotations

from typing import Any

#: multilingual by default — graphs mix English identifiers and Japanese notes
DEFAULT_MODEL = "minishlab/potion-multilingual-128M"

_MODELS: dict = {}


def _load_model(name: str):
    try:
        from model2vec import StaticModel
    except ImportError:  # pragma: no cover
        raise ImportError(
            "semantic search requires model2vec — pip install 'trikedb[semantic]'"
        ) from None
    if name not in _MODELS:
        _MODELS[name] = StaticModel.from_pretrained(name)
    return _MODELS[name]


def sentences(db) -> list:
    """One searchable sentence per triple (attrs inlined) and per node
    with properties. Returns [(text, payload), ...]."""
    items = []
    for t in db:
        parts = [t.s, t.p, t.o] + [f"{k}: {v}" for k, v in t.attrs.items()]
        items.append((" ".join(str(x) for x in parts), {"kind": "triple", **t.to_dict()}))
    for name, props in db.nodes_meta.items():
        if props:
            text = name + " " + " ".join(f"{k}: {v}" for k, v in props.items())
            items.append((text, {"kind": "node", "node": name, **props}))
    return items


def search(db, query: str, k: int = 10, model: str = DEFAULT_MODEL) -> list:
    """Rank triples and nodes by cosine similarity to `query`.

    Returns up to k dicts sorted by score: {"score": 0.63, "kind":
    "triple", "s": ..., "p": ..., "o": ..., <attrs>} or {"score": ...,
    "kind": "node", "node": ..., <props>}.
    """
    import numpy as np

    m = _load_model(model)
    items = sentences(db)
    if not items:
        return []
    embs = np.asarray(m.encode([text for text, _ in items]))
    q = np.asarray(m.encode([query]))[0]
    embs = embs / (np.linalg.norm(embs, axis=1, keepdims=True) + 1e-9)
    q = q / (np.linalg.norm(q) + 1e-9)
    scores = embs @ q
    order = scores.argsort()[::-1][: max(1, int(k))]
    return [
        {"score": round(float(scores[i]), 4), **items[i][1]} for i in order
    ]
