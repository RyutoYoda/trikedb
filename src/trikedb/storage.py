"""Storage backends: where a graph's bytes live.

Everything above this layer talks in terms of read_text/write_text/exists
on a path-or-URL. Adding a new file backend (a new URL scheme, caching, ...)
happens here and nowhere else.

This layer carries the storage concurrency checks. A save rewrites the whole
document, so local files compare a content hash under a stable lock; S3 and
S3 uses native conditional writes. A lost race surfaces as
``ConcurrentWriteError`` instead of disappearing silently.
"""

from __future__ import annotations

from pathlib import Path
from contextlib import contextmanager
import hashlib
import os
import stat
import tempfile

REMOTE_PREFIXES = (
    "s3://", "gs://", "gcs://", "http://", "https://",
    "az://", "abfs://", "memory://",
)

#: Backends whose conditional writes we know how to drive.
_CONDITIONAL_PROTOCOLS = ("s3", "s3a")

_UNCHECKED = object()


class ConcurrentWriteError(RuntimeError):
    """The stored graph changed between reading it and writing it back.

    Nothing has been written. Re-read the graph, re-apply the change, and
    save again — the copy in memory is built on bytes that no longer exist.
    """


def is_remote(path) -> bool:
    return isinstance(path, str) and path.startswith(REMOTE_PREFIXES)


def check_scheme(path) -> None:
    """Reject a URL whose scheme no backend answers to.

    Without this, ``s2://bucket/kg.yaml`` is not an error: nothing claims
    it, so it falls through to the local-file branch and becomes a new,
    empty graph in a file literally named ``s2://bucket/kg.yaml``. The typo
    reads as "the graph is empty", which is the worst way to learn about it.
    A path with no ``://`` is a filename and is left alone.
    """
    if not isinstance(path, str) or "://" not in path:
        return
    scheme = path.split("://", 1)[0]
    if scheme + "://" not in REMOTE_PREFIXES:
        raise ValueError(
            f"{path}: no backend handles '{scheme}://' — supported schemes are "
            + ", ".join(REMOTE_PREFIXES)
            + " (a local path is written without a scheme)"
        )


def _scheme(path) -> str:
    if not isinstance(path, str) or "://" not in path:
        return ""
    return path.split("://", 1)[0]


def serialization(path) -> str:
    """"yaml" or "json" — how a graph should be written down for this target.

    YAML is the default reviewable file format.
    A path ending in ``.json`` gets JSON too, which is the escape hatch for
    a graph that is read far more often than it is reviewed: the loader is
    around 30x faster on JSON than on the same graph as YAML, because
    ``json.loads`` is C and the YAML parser is not. The cost is the thing
    YAML was chosen for — nobody enjoys reading a diff of it.
    """
    return "json" if str(path).lower().endswith(".json") else "yaml"


def _fsspec():
    try:
        import fsspec
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "remote graph URLs require fsspec - pip install 'trikedb[remote]' "
            "(installs fsspec + s3fs; other backends: gcsfs, adlfs)"
        ) from exc
    return fsspec


def _conditional_fs(path):
    """(fs, key) when this backend supports conditional writes, else None."""
    if not is_remote(path):
        return None
    fs, key = _fsspec().core.url_to_fs(path)
    protocols = fs.protocol if isinstance(fs.protocol, tuple) else (fs.protocol,)
    if not any(p in _CONDITIONAL_PROTOCOLS for p in protocols):
        return None
    return fs, key


_PRECONDITION_MARKERS = (
    "PreconditionFailed",
    "ConditionalRequestConflict",
    # s3fs translates the ClientError into an OSError and keeps only the text
    "pre-conditions you specified did not hold",
)


def _is_precondition_failure(exc: BaseException) -> bool:
    """Did the store refuse because the object is not what we expected?

    412 is the documented answer to a failed If-Match/If-None-Match and 409
    comes back when two conditional writes race. Neither is necessarily what
    reaches us: s3fs re-raises botocore's ClientError as a plain OSError and
    turns a failed create into FileExistsError, so walk the chain and accept
    either the structured code or the wording.
    """
    seen = []
    while exc is not None and exc not in seen:
        seen.append(exc)
        if isinstance(exc, FileExistsError):
            return True
        response = getattr(exc, "response", None)
        if isinstance(response, dict):
            meta = response.get("ResponseMetadata") or {}
            if meta.get("HTTPStatusCode") in (409, 412):
                return True
            if response.get("Error", {}).get("Code") in _PRECONDITION_MARKERS:
                return True
        if any(marker in str(exc) for marker in _PRECONDITION_MARKERS):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def exists(path) -> bool:
    check_scheme(path)
    if is_remote(path):
        fs, p = _fsspec().core.url_to_fs(path)
        return fs.exists(p)
    return Path(path).exists()


def version(path):
    """An opaque token for the bytes currently stored, or None.

    None means either "nothing is stored there" or "this backend has no
    version to give" — both are handled the same way by ``write_text``.

    Read this *before* reading the content. The other order is the unsafe
    one: a writer landing in between would leave you holding their version
    token for someone else's bytes, and your next write would silently
    overwrite them. This way round the worst case is a conflict you didn't
    strictly need.
    """
    check_scheme(path)
    if not is_remote(path):
        try:
            return hashlib.sha256(Path(path).read_bytes()).hexdigest()
        except FileNotFoundError:
            return None
    target = _conditional_fs(path)
    if target is None:
        return None
    fs, key = target
    try:
        info = fs.info(key)
    except FileNotFoundError:
        return None
    etag = info.get("ETag") or info.get("etag")
    return str(etag).strip('"') if etag else None


def _is_stale_read(exc: BaseException) -> bool:
    """Did the object get replaced while we were reading it?

    s3fs reads through a conditional GET pinned to the ETag it saw, so a
    writer landing mid-read invalidates the rest of the transfer. Nothing is
    wrong — the bytes simply moved on — so the read should just start over.
    """
    while exc is not None:
        if type(exc).__name__ == "FileExpired" or "no longer exists" in str(exc):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def read_text(path, attempts: int = 3) -> str:
    check_scheme(path)
    if not is_remote(path):
        return Path(path).read_text(encoding="utf-8")
    for remaining in range(attempts - 1, -1, -1):
        try:
            with _fsspec().open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as exc:
            if not remaining or not _is_stale_read(exc):
                raise


def write_text(path, text: str, expect=_UNCHECKED):
    """Write the graph out, optionally only if it hasn't moved under us.

    ``expect`` is a token from a previous ``version()`` call: pass the one
    you read the content at and the write is refused — with
    ``ConcurrentWriteError`` and nothing written — if anyone else has saved
    since. ``expect=None`` means "there was nothing there", so the write is
    refused if the object now exists. Omit ``expect`` for the old
    last-write-wins behaviour.

    Other remote backends that cannot express the condition fall back to an ordinary
    write; the guarantee is only as good as the storage underneath.
    """
    check_scheme(path)

    target = _conditional_fs(path)
    if target is not None:
        fs, key = target
        data = text.encode("utf-8")
        if len(data) >= 5 * 2**30:
            raise ValueError("graph exceeds the single-PUT limit; conditional multipart writes are unsupported")
        # s3fs multipart completion does not forward IfMatch. Force one PUT.
        put_options = {"chunksize": max(50 * 2**20, len(data))}
        try:
            if expect is _UNCHECKED:
                response = fs.pipe_file(key, data, **put_options)
            elif expect is None:
                response = fs.pipe_file(key, data, mode="create", **put_options)
            else:
                response = fs.pipe_file(key, data, IfMatch=expect, **put_options)
        except Exception as exc:
            if _is_precondition_failure(exc):
                raise ConcurrentWriteError(
                    f"{path} changed since it was read - "
                    "re-read the graph and re-apply the change"
                ) from exc
            raise
        # Never HEAD after PUT: that token could belong to another writer.
        # Missing tokens fail closed on the next save (expect=None requires
        # absence), rather than granting permission to overwrite newer bytes.
        etag = response.get("ETag") if isinstance(response, dict) else None
        return str(etag).strip('"') if etag else None

    if is_remote(path):
        with _fsspec().open(path, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        path = Path(path).resolve()
        with _local_lock(path):
            if expect is not _UNCHECKED and version(path) != expect:
                raise ConcurrentWriteError(
                    f"{path} changed since it was read - "
                    "re-read the graph and re-apply the change"
                )
            _atomic_write(path, text)
            # Return the bytes *we* committed. A later stat/read could pick
            # up an external editor's version and grant a stale writer its
            # token, the same mistake avoided by S3's returned ETag.
            return hashlib.sha256(text.encode("utf-8")).hexdigest()


@contextmanager
def _local_lock(path: Path):
    """Keep compare-and-replace together across TrikeDB processes.

    The lock has its own stable inode: locking the graph would fail after
    atomic replacement, because the next writer would lock a new inode.
    Keep it in the user's cache, so a graph remains a single reviewable file.
    Never delete a lock while a process could still be holding its inode.
    """
    root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    lock_dir = root / "trikedb" / "locks"
    lock_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = lock_dir / hashlib.sha256(os.fsencode(path)).hexdigest()
    with open(lock_path, "a+b") as lock:
        if os.name == "nt":
            import msvcrt
            if lock.tell() == 0:
                lock.write(b"\0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _atomic_write(path: Path, text: str) -> None:
    """Replace complete bytes on the same filesystem; preserve existing mode.

    Resolve symlinks so a save updates their target as ordinary open() did.
    A failed write/flush/replace leaves the old file intact. The caller's
    lock and version check coordinate same-host TrikeDB processes; this
    function alone is not a transaction against an external editor.
    """
    path = path.resolve()
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    if mode is not None and not mode & 0o222:
        raise PermissionError(f"{path} is read-only")
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
            if mode is not None:
                os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
