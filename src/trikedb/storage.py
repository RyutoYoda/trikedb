"""Storage backends: where a graph's bytes live.

Everything above this layer talks in terms of read_text/write_text/exists
on a path-or-URL. Adding a new backend (a new URL scheme, caching, ...)
happens here and nowhere else.

This layer also carries the only concurrency control trikedb has. A save
rewrites the whole file, so two writers that both read version N produce
two different N+1s and one of them disappears. Where the backend can say
"only if it is still what I read" — S3 conditional PUT — ``write_text``
says it, and a lost write surfaces as ``ConcurrentWriteError`` instead of
as missing data nobody notices.
"""

from __future__ import annotations

from pathlib import Path

REMOTE_PREFIXES = (
    "s3://", "gs://", "gcs://", "http://", "https://",
    "az://", "abfs://", "memory://",
    "snowflake://",
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


#: Schemes handled by :mod:`trikedb.storage_sql`. Named here, deliberately
#: duplicating what that module knows, so that a plain path or an ``s3://``
#: URL never imports it: the SQL backend pulls in a warehouse driver, and
#: trikedb also gets vendored as a subset of its files into places that
#: cannot install one — Streamlit in Snowflake among them. Importing it
#: unconditionally turned "open a local YAML file" into an ImportError there.
#: ``test_sql_schemes_match_the_dialects`` keeps the two lists honest.
_SQL_SCHEMES = ("snowflake",)


def _scheme(path) -> str:
    if not isinstance(path, str) or "://" not in path:
        return ""
    return path.split("://", 1)[0]


def serialization(path) -> str:
    """"yaml" or "json" — how a graph should be written down for this target.

    YAML everywhere a person might open the file, which is the whole point of
    the format. JSON for a warehouse row, because SQL can crack JSON open
    (`TRY_PARSE_JSON(doc):triples`) and there is no YAML parser in SQL to do
    the same — a YAML string in a column is a graph nothing but trikedb can
    read.

    Nothing is lost by the switch: JSON is a subset of YAML, so the loader
    reads either without knowing which it got. The reader stays oblivious;
    only the writer needs to ask.

    A path ending in ``.json`` gets JSON too, which is the escape hatch for
    a graph that is read far more often than it is reviewed: the loader is
    around 30x faster on JSON than on the same graph as YAML, because
    ``json.loads`` is C and the YAML parser is not. The cost is the thing
    YAML was chosen for — nobody enjoys reading a diff of it.
    """
    if _scheme(path) in _SQL_SCHEMES:
        return "json"
    return "json" if str(path).lower().endswith(".json") else "yaml"


def _sql_store(path, connection=None):
    """The SQL-table store for this URL, or None if it isn't one.

    Warehouses are not filesystems, so they do not reach fsspec: a graph
    there is a row, addressed by table and name. The split happens here so
    that everything above still only knows read_text/write_text.

    ``connection`` is an already-open connection or session to run through
    instead of building one. The import stays inside the scheme check so an
    install without the SQL backend is only a problem for someone actually
    asking for a warehouse URL — and then it is a real ImportError naming
    the missing module, not a silent fallback to the wrong backend.
    """
    if _scheme(path) not in _SQL_SCHEMES:
        return None
    from . import storage_sql

    return storage_sql.open_url(path, connection=connection)


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


def exists(path, connection=None) -> bool:
    store = _sql_store(path, connection)
    if store is not None:
        return store.exists()
    if is_remote(path):
        fs, p = _fsspec().core.url_to_fs(path)
        return fs.exists(p)
    return Path(path).exists()


def version(path, connection=None):
    """An opaque token for the bytes currently stored, or None.

    None means either "nothing is stored there" or "this backend has no
    version to give" — both are handled the same way by ``write_text``.

    Read this *before* reading the content. The other order is the unsafe
    one: a writer landing in between would leave you holding their version
    token for someone else's bytes, and your next write would silently
    overwrite them. This way round the worst case is a conflict you didn't
    strictly need.
    """
    store = _sql_store(path, connection)
    if store is not None:
        return store.version()
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


def read_text(path, attempts: int = 3, connection=None) -> str:
    store = _sql_store(path, connection)
    if store is not None:
        return store.read_text()
    if not is_remote(path):
        return Path(path).read_text(encoding="utf-8")
    for remaining in range(attempts - 1, -1, -1):
        try:
            with _fsspec().open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as exc:
            if not remaining or not _is_stale_read(exc):
                raise


def write_text(path, text: str, expect=_UNCHECKED, connection=None) -> None:
    """Write the graph out, optionally only if it hasn't moved under us.

    ``expect`` is a token from a previous ``version()`` call: pass the one
    you read the content at and the write is refused — with
    ``ConcurrentWriteError`` and nothing written — if anyone else has saved
    since. ``expect=None`` means "there was nothing there", so the write is
    refused if the object now exists. Omit ``expect`` for the old
    last-write-wins behaviour.

    Backends that cannot express the condition fall back to an ordinary
    write; the guarantee is only as good as the storage underneath.
    """
    store = _sql_store(path, connection)
    if store is not None:
        # A SQL backend answers with a row count rather than an error, so the
        # conflict is a plain False and needs no message-matching.
        if not store.write_text(text, expect, _UNCHECKED):
            raise ConcurrentWriteError(
                f"{path} changed since it was read - "
                "re-read the graph and re-apply the change"
            )
        return

    target = None if expect is _UNCHECKED else _conditional_fs(path)
    if target is not None:
        fs, key = target
        data = text.encode("utf-8")
        try:
            if expect is None:
                fs.pipe_file(key, data, mode="create")
            else:
                fs.pipe_file(key, data, IfMatch=expect)
        except Exception as exc:
            if _is_precondition_failure(exc):
                raise ConcurrentWriteError(
                    f"{path} changed since it was read - "
                    "re-read the graph and re-apply the change"
                ) from exc
            raise
        return

    if is_remote(path):
        with _fsspec().open(path, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        Path(path).write_text(text, encoding="utf-8")
