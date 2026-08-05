"""Storage backends: where a graph's bytes live.

Everything above this layer talks in terms of read_text/write_text/exists
on a path-or-URL. Adding a new backend (a new URL scheme, conditional
PUT for optimistic locking, caching, ...) happens here and nowhere else.
"""

from __future__ import annotations

from pathlib import Path

REMOTE_PREFIXES = (
    "s3://", "gs://", "gcs://", "http://", "https://",
    "az://", "abfs://", "memory://",
)


def is_remote(path) -> bool:
    return isinstance(path, str) and path.startswith(REMOTE_PREFIXES)


def _fsspec():
    try:
        import fsspec
    except ImportError:  # pragma: no cover
        raise ImportError(
            "remote graph URLs require fsspec — pip install 'trikedb[remote]' "
            "(installs fsspec + s3fs; other backends: gcsfs, adlfs)"
        ) from None
    return fsspec


def exists(path) -> bool:
    if is_remote(path):
        fs, p = _fsspec().core.url_to_fs(path)
        return fs.exists(p)
    return Path(path).exists()


def read_text(path) -> str:
    if is_remote(path):
        with _fsspec().open(path, "r", encoding="utf-8") as f:
            return f.read()
    return Path(path).read_text(encoding="utf-8")


def write_text(path, text: str) -> None:
    if is_remote(path):
        with _fsspec().open(path, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        Path(path).write_text(text, encoding="utf-8")
