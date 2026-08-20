"""Storage backends that keep the graph in a SQL table.

One graph is one row: ``name`` identifies it, ``doc`` holds the YAML that
every other layer already speaks, and ``version`` is the token that makes a
save conditional. One table holds many graphs, so adopting trikedb costs a
company a single table rather than a table per graph.

URLs name the table and the graph::

    snowflake://MYDB.PUBLIC.TRIKE_GRAPHS/sales/crm
    snowflake://TRIKE_GRAPHS/sales/crm     # database + schema from the connection

The netloc is the table, the rest of the path is the graph name — slashes and
all, it is only ever a string key.

Everything a warehouse needs to differ about lives in a :class:`_Dialect`,
which is data: SQL templates and a connect function. The read/write logic
above it is shared, so the next backend (BigQuery, Postgres, DuckDB) is a
dialect and nothing else.

Why a SQL table can do this at all: the layer above storage only ever asks
for a whole document, and a warehouse can express "replace this row only if
it is still the one I read" as ``UPDATE ... WHERE version = <token>`` and
then look at the affected-row count. That is a real compare-and-swap, and a
cleaner one than the ETag preconditions :mod:`trikedb.storage` has to drive
on S3 — the answer is a row count rather than an error message to pattern
match.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlsplit

__all__ = ["ddl_for", "is_sql_url", "open_url"]


class TableMissing(RuntimeError):
    """The table behind a ``<scheme>://`` URL does not exist (or isn't visible).

    Distinct from "the graph isn't in it yet", which is an ordinary empty
    graph. Creating tables in a company-wide warehouse is not trikedb's call
    to make, so this asks rather than does.
    """


# --------------------------------------------------------------------- dialects

@dataclass(frozen=True)
class _Dialect:
    """How one warehouse spells the four statements this module needs."""

    name: str
    #: env -> connect kwargs, so a deployment configures the warehouse the
    #: way its own tooling already does
    config_from_env: Callable[[], dict]
    connect: Callable[[dict], object]
    #: each template takes {table}; parameter placeholders are the dialect's own
    ddl: str
    select: str
    update: str
    insert_if_absent: str
    upsert: str


def _snowflake_config_from_env() -> dict:
    """Connect kwargs from the environment.

    A named connection in ``connections.toml`` wins if it is set — that is
    where a company that already standardised its Snowflake access keeps it,
    and duplicating those values into env vars just to be overridden here
    would be worse than deferring.
    """
    named = os.environ.get("SNOWFLAKE_CONNECTION_NAME")
    if named:
        return {"connection_name": named}

    cfg: dict = {}
    for key, env in (
        ("account", "SNOWFLAKE_ACCOUNT"),
        ("user", "SNOWFLAKE_USER"),
        ("password", "SNOWFLAKE_PASSWORD"),
        ("role", "SNOWFLAKE_ROLE"),
        ("warehouse", "SNOWFLAKE_WAREHOUSE"),
        ("database", "SNOWFLAKE_DATABASE"),
        ("schema", "SNOWFLAKE_SCHEMA"),
        ("authenticator", "SNOWFLAKE_AUTHENTICATOR"),
        # Key-pair auth: hand the connector the PKCS#8 PEM path directly
        # rather than parsing it here. Fewer ways to get it wrong, and the
        # connector already depends on cryptography to do it.
        ("private_key_file", "SNOWFLAKE_PRIVATE_KEY_PATH"),
        ("private_key_file_pwd", "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"),
    ):
        value = os.environ.get(env)
        if value:
            cfg[key] = value
    if not cfg.get("account"):
        raise ValueError(
            "snowflake:// needs connection settings in the environment - set "
            "SNOWFLAKE_ACCOUNT and SNOWFLAKE_USER plus one of "
            "SNOWFLAKE_PRIVATE_KEY_PATH (PKCS#8 PEM) or SNOWFLAKE_PASSWORD, or "
            "point SNOWFLAKE_CONNECTION_NAME at an entry in connections.toml"
        )
    return cfg


def _snowflake_connect(config: dict):
    try:
        import snowflake.connector
    except ImportError as exc:  # pragma: no cover - exercised via the message
        raise ImportError(
            "snowflake:// graph URLs require the Snowflake connector - "
            "pip install 'trikedb[snowflake]'"
        ) from exc
    return snowflake.connector.connect(**config)


#: Snowflake serialises UPDATE/MERGE on a table, so the affected-row count is
#: a trustworthy compare-and-swap result: two writers cannot both see 1.
SNOWFLAKE = _Dialect(
    name="snowflake",
    config_from_env=_snowflake_config_from_env,
    connect=_snowflake_connect,
    ddl=(
        "CREATE TABLE IF NOT EXISTS {table} (\n"
        "    name       STRING NOT NULL,\n"
        "    doc        STRING,\n"
        "    version    STRING NOT NULL,\n"
        "    updated_at TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()\n"
        ")"
    ),
    select="SELECT doc, version FROM {table} WHERE name = %s",
    update=(
        "UPDATE {table} SET doc = %s, version = %s, "
        "updated_at = CURRENT_TIMESTAMP() "
        "WHERE name = %s AND version = %s"
    ),
    # MERGE rather than INSERT ... WHERE NOT EXISTS: the row count then says
    # whether we were the one who created it, which is the whole point.
    insert_if_absent=(
        "MERGE INTO {table} AS t "
        "USING (SELECT %s AS name, %s AS doc, %s AS version) AS s "
        "ON t.name = s.name "
        "WHEN NOT MATCHED THEN INSERT (name, doc, version, updated_at) "
        "VALUES (s.name, s.doc, s.version, CURRENT_TIMESTAMP())"
    ),
    upsert=(
        "MERGE INTO {table} AS t "
        "USING (SELECT %s AS name, %s AS doc, %s AS version) AS s "
        "ON t.name = s.name "
        "WHEN MATCHED THEN UPDATE SET doc = s.doc, version = s.version, "
        "updated_at = CURRENT_TIMESTAMP() "
        "WHEN NOT MATCHED THEN INSERT (name, doc, version, updated_at) "
        "VALUES (s.name, s.doc, s.version, CURRENT_TIMESTAMP())"
    ),
)

#: scheme -> dialect. A new warehouse lands here and nowhere else.
DIALECTS = {"snowflake": SNOWFLAKE}


# -------------------------------------------------------------------- url parsing

#: The table name is interpolated into SQL — parameters cannot carry an
#: identifier — so it is checked against what an identifier may contain
#: rather than quoted. Unquoted also keeps Snowflake's own case folding,
#: which is what someone writing `mydb.public.t` expects.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def is_sql_url(path) -> bool:
    return isinstance(path, str) and path.split("://", 1)[0] in DIALECTS


def _split(url: str):
    """(dialect, validated table reference, graph name)."""
    parts = urlsplit(url)
    dialect = DIALECTS.get(parts.scheme)
    if dialect is None:
        raise ValueError(f"not a SQL graph URL: {url}")

    table = parts.netloc
    segments = table.split(".") if table else []
    if not 1 <= len(segments) <= 3 or not all(_IDENTIFIER.match(s) for s in segments):
        raise ValueError(
            f"{url}: expected {parts.scheme}://TABLE/graph-name, where TABLE is "
            "TABLE, SCHEMA.TABLE or DATABASE.SCHEMA.TABLE"
        )

    name = parts.path.lstrip("/")
    if not name:
        raise ValueError(
            f"{url}: no graph name - the path after the table names the row, "
            f"e.g. {parts.scheme}://{table}/sales/crm"
        )
    return dialect, ".".join(segments), name


def ddl_for(url: str) -> str:
    """The CREATE TABLE this URL's table needs, for review before running."""
    dialect, table, _ = _split(url)
    return dialect.ddl.format(table=table)


def open_url(url: str) -> "SqlGraphStore":
    return SqlGraphStore(*_split(url), url=url)


# ------------------------------------------------------------------- connections

#: Opening a warehouse connection costs auth, TLS and possibly a warehouse
#: resume, and storage.py calls in here several times to open one graph. One
#: connection per distinct config, reused for the life of the process.
_CONNECTIONS: dict = {}


def _cache_key(dialect: _Dialect, config: dict):
    return (dialect.name, tuple(sorted(config.items())))


def _connection(dialect: _Dialect, config: dict):
    key = _cache_key(dialect, config)
    conn = _CONNECTIONS.get(key)
    if conn is not None:
        closed = getattr(conn, "is_closed", None)
        if closed is None or not closed():
            return conn
        _CONNECTIONS.pop(key, None)
    conn = dialect.connect(config)
    _CONNECTIONS[key] = conn
    return conn


def _forget(dialect: _Dialect, config: dict) -> None:
    conn = _CONNECTIONS.pop(_cache_key(dialect, config), None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


_LOST_CONNECTION_MARKERS = (
    "connection is closed",
    "connection already closed",
    "authentication token has expired",
    "session no longer exists",
    "session does not exist",
)

_MISSING_TABLE_MARKERS = (
    "does not exist or not authorized",
    "no such table",
    "undefined_table",
)


def _matches(exc: BaseException, markers) -> bool:
    while exc is not None:
        text = str(exc).lower()
        if any(m in text for m in markers):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


# ------------------------------------------------------------------------ store

class SqlGraphStore:
    """One graph, stored as one row. Mirrors the storage.py function set."""

    def __init__(self, dialect: _Dialect, table: str, name: str, url: str = ""):
        self._dialect = dialect
        self._table = table
        self._name = name
        self._url = url or f"{dialect.name}://{table}/{name}"
        self._config: Optional[dict] = None

    # -- plumbing

    def _settings(self) -> dict:
        if self._config is None:
            self._config = self._dialect.config_from_env()
        return self._config

    def _run(self, template: str, params: tuple, want_rows: bool):
        """Run one statement, reconnecting once if the session went away.

        Warehouse sessions expire on their own schedule, and a cached
        connection that has quietly died would otherwise turn the next save
        into a failure the caller cannot act on.
        """
        sql = template.format(table=self._table)
        config = self._settings()
        for remaining in (1, 0):
            conn = _connection(self._dialect, config)
            try:
                cursor = conn.cursor()
                try:
                    # None rather than () for parameterless SQL: a driver is
                    # entitled to still look for placeholders when given a
                    # sequence, and the DDL has none.
                    cursor.execute(sql, params or None)
                    if want_rows:
                        return cursor.fetchall()
                    return cursor.rowcount
                finally:
                    cursor.close()
            except Exception as exc:
                if _matches(exc, _MISSING_TABLE_MARKERS):
                    raise TableMissing(
                        f"{self._url}: table {self._table} does not exist or is "
                        f"not visible to this role. Create it with "
                        f"'trikedb sql-init {self._url}' (add --print to review "
                        f"the DDL first)"
                    ) from exc
                _forget(self._dialect, config)
                if not remaining or not _matches(exc, _LOST_CONNECTION_MARKERS):
                    raise

    def _row(self):
        rows = self._run(self._dialect.select, (self._name,), want_rows=True)
        if not rows:
            return None
        doc, version = rows[0][0], rows[0][1]
        return ("" if doc is None else str(doc)), str(version)

    # -- the storage.py surface

    def exists(self) -> bool:
        return self._row() is not None

    def version(self):
        row = self._row()
        return row[1] if row else None

    def read_text(self) -> str:
        row = self._row()
        if row is None:
            raise FileNotFoundError(self._url)
        return row[0]

    def write_text(self, text: str, expect, unchecked) -> bool:
        """Write the row, conditionally unless ``expect`` is ``unchecked``.

        True when the write landed, False when the condition did not hold and
        nothing was written. The caller turns False into its own
        ConcurrentWriteError, so the error type stays owned by storage.py and
        this module needs no import from it.
        """
        token = uuid.uuid4().hex
        if expect is unchecked:
            self._run(
                self._dialect.upsert, (self._name, text, token), want_rows=False
            )
            return True
        if expect is None:
            affected = self._run(
                self._dialect.insert_if_absent,
                (self._name, text, token),
                want_rows=False,
            )
        else:
            affected = self._run(
                self._dialect.update,
                (text, token, self._name, expect),
                want_rows=False,
            )
        return bool(affected)

    def create_table(self) -> None:
        self._run(self._dialect.ddl, (), want_rows=False)
