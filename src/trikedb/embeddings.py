"""Semantic (embedding) search over the graph — the optional [semantic] extra.

Keyword search finds what you can spell; semantic search finds what you
mean ("認証まわりの注意点" hits keypair/MFA/token facts without sharing a
single word). Embeddings are static (model2vec) — no torch, no GPU, and
nothing to build ahead of time: the vectors are a cache keyed by sentence,
so a graph that grew by one fact costs one sentence to re-encode, and a
graph that did not change costs none.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

#: multilingual by default — graphs mix English identifiers and Japanese notes
DEFAULT_MODEL = "minishlab/potion-multilingual-128M"
MAX_CHUNK_CHARS = 2000

_MODELS: dict = {}


def _load_model(name: str):
    try:
        from model2vec import StaticModel
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "semantic search requires model2vec - pip install 'trikedb[semantic]'"
        ) from exc
    if name not in _MODELS:
        _MODELS[name] = StaticModel.from_pretrained(name)
    return _MODELS[name]


#: Keys the payload owns. An edge attribute or node property with one of
#: these names would otherwise replace the field callers dispatch on — a
#: fact annotated `score=0.99` came back claiming that was its similarity,
#: and one annotated `kind="mine"` was skipped by every caller checking for
#: `kind == "triple"`. Reserved keys win, and the colliding attribute is kept
#: under `attr_<name>` so nothing is silently dropped either.
_RESERVED = ("score", "kind", "node", "chunk", "chunk_text")

#: A hit inlines the node's properties, and one of those can be a whole
#: document — 540k characters of it came back from a single `search(k=5)`,
#: straight into the context of the agent that asked a one-line question.
#: Longer values arrive as a self-describing preview instead; the passage
#: that actually matched rides along as `chunk_text`, and `node()` /
#: `get_node` still hand over the untouched value to anyone who wants it.
MAX_VALUE_CHARS = 400


def preview(fields: dict) -> dict:
    """`fields` with over-long values cut down to a labelled preview."""
    out = {}
    for key, value in fields.items():
        if isinstance(value, str) and len(value) > MAX_VALUE_CHARS:
            value = (f"{value[:MAX_VALUE_CHARS]}… (+{len(value) - MAX_VALUE_CHARS} "
                     f"chars — read the whole value with get_node)")
        out[key] = value
    return out


def _payload(fields: dict, **reserved) -> dict:
    out = {}
    for key, value in preview(fields).items():
        out[f"attr_{key}" if key in _RESERVED else key] = value
    out.update(reserved)
    return out


def sentences(db) -> list:
    """One searchable sentence per triple (attrs inlined) and per node
    with properties. Returns [(text, payload), ...]."""
    items = []
    for t in db:
        parts = [t.s, t.p, t.o] + [f"{k}: {v}" for k, v in t.attrs.items()]
        # kind last: an edge attribute genuinely called "kind" would
        # otherwise overwrite the field callers branch on, and a caller
        # checking `kind == "triple"` would silently skip the row.
        items.append((" ".join(str(x) for x in parts),
                      _payload(t.to_dict(), kind="triple")))
    for name, props in db.nodes_meta.items():
        if props:
            text = name + " " + " ".join(f"{k}: {v}" for k, v in props.items())
            payload = _payload(props, kind="node", node=name)
            if len(text) <= MAX_CHUNK_CHARS:
                items.append((text, payload))
            else:
                # Long document properties must not collapse into one vector.
                # Keep the node payload so callers can still resolve the hit,
                # and hand back the passage that matched rather than the
                # document it came from.
                for start in range(0, len(text), MAX_CHUNK_CHARS):
                    chunk = text[start:start + MAX_CHUNK_CHARS]
                    items.append((chunk, {**payload,
                                          "chunk": start // MAX_CHUNK_CHARS,
                                          "chunk_text": chunk}))
    return items


def _cache_root():
    """The directory vectors are cached in: `TRIKEDB_CACHE_DIR` if set, else
    the XDG cache directory, else `~/.cache`. None when none of them is an
    absolute path — a runtime with no home just re-encodes."""
    explicit = os.environ.get("TRIKEDB_CACHE_DIR")
    if explicit:
        return Path(explicit) if os.path.isabs(explicit) else None
    root = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(root) / "trikedb" if os.path.isabs(root) else None


def _cache_path(db, model: str):
    """Where this graph's vectors live for this model, or None if nowhere.

    In a cache directory, not beside the graph. A sidecar file was tidy
    right up until `git add -A` staged a 28MB binary next to a YAML whose
    whole point is being a reviewable diff.

    One entry per (graph, model), never one per revision: a name that
    included the corpus would leave the old one behind as a dead file every
    time a fact was added.
    """
    path = getattr(db, "path", None)
    if not path or "://" in str(path):
        return None  # a graph in a bucket or a warehouse has no local cache
    root = _cache_root()
    if root is None:
        return None
    p = Path(path)
    where = hashlib.sha256(str(p.resolve()).encode("utf-8")).hexdigest()[:16]
    model_digest = hashlib.sha256(model.encode("utf-8")).hexdigest()[:12]
    return root / f"{p.stem or 'graph'}-{where}-{model_digest}.npz"


def _key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _embeddings(db, items: list, model: str, m):
    """Vectors for `items`, encoding only the sentences not already cached.

    Keyed per sentence rather than per corpus because the loop an agent
    actually runs is add-a-fact-then-search: keying on the whole graph
    would hand the cache back on every write and re-encode all of it.
    """
    import numpy as np

    texts = [text for text, _ in items]
    keys = [_key(text) for text in texts]
    cache = _cache_path(db, model)
    known: dict = {}
    if cache and cache.exists():
        try:
            with np.load(cache) as data:
                cached_keys, cached_embs = data["keys"], data["embs"]
            if len(cached_keys) == len(cached_embs):
                known = dict(zip((str(x) for x in cached_keys), cached_embs))
        except (OSError, ValueError, KeyError):
            known = {}  # a truncated or foreign cache just costs one re-encode
    # dict.fromkeys: two identical sentences are one vector, encoded once
    missing = list(dict.fromkeys(t for t, key in zip(texts, keys) if key not in known))
    if missing:
        for text, vec in zip(missing, np.asarray(m.encode(missing), dtype="float32")):
            known[_key(text)] = vec
    embs = np.asarray([known[key] for key in keys], dtype="float32")
    if cache and missing:
        _write_cache(cache, keys, embs)
    return embs


def _write_cache(cache, keys: list, embs) -> None:
    """Replace the sidecar with the vectors for the current corpus.

    Only what the graph says now: keeping retired sentences would make the
    cache outgrow the graph it belongs to. Uncompressed on purpose — this
    runs on the write path, where a second of zlib costs more than the disk
    it saves. The pid in the temp name keeps two searching processes from
    writing the same partial file.
    """
    import numpy as np

    tmp = cache.with_name(f"{cache.name}.{os.getpid()}.tmp")
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "wb") as fh:
            np.savez(fh, keys=np.array(keys), embs=embs)
        tmp.replace(cache)
    except OSError:  # a read-only directory is not a reason to fail a search
        try:
            tmp.unlink()
        except OSError:
            pass


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
    embs = _embeddings(db, items, model, m)
    q = np.asarray(m.encode([query]))[0]
    embs = embs / (np.linalg.norm(embs, axis=1, keepdims=True) + 1e-9)
    q = q / (np.linalg.norm(q) + 1e-9)
    scores = embs @ q
    hits, seen_chunked = [], set()
    for i in scores.argsort()[::-1]:
        payload = items[i][1]
        # One long property is many chunks of one node. Without this the
        # best-matching document takes every slot, and the triples that
        # answer the other half of the question never make the list.
        if "chunk" in payload:
            if payload["node"] in seen_chunked:
                continue
            seen_chunked.add(payload["node"])
        hits.append({**payload, "score": round(float(scores[i]), 4)})
        if len(hits) >= max(1, int(k)):
            break
    return hits
