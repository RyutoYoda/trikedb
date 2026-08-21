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
from dataclasses import dataclass, field
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
    #: {view name: SELECT body} — the projection, see _SNOWFLAKE_VIEWS. Empty
    #: is legitimate: a backend can store graphs without exposing them to SQL.
    views: dict = field(default_factory=dict)
    #: True when this engine binds by name (pyformat, ``%(doc)s``) rather
    #: than by position (``%s``). The names themselves are read off each
    #: template — see :func:`_named` — because they differ per statement and
    #: a single declared order silently mismapped them: the update takes
    #: (doc, version, name, expect) while the insert takes (name, doc,
    #: version), so every write compared the wrong column and reported a
    #: conflict that had not happened.
    named_params: bool = False
    #: What one dot-separated part of a table reference may contain. The table
    #: is interpolated into SQL — a parameter cannot carry an identifier — so
    #: this is a whitelist, not a quoting rule, and it has to be per-dialect:
    #: a GCP project id contains hyphens, which no Snowflake identifier may.
    identifier: str = r"^[A-Za-z_][A-Za-z0-9_$]*$"
    #: How a qualified name is written into SQL once its parts are validated.
    #: Applied at the point of use, never stored: quoting the stored name meant
    #: deriving a schema from it produced `proj.dataset — an unclosed literal.
    quote_table: Callable[[str], str] = staticmethod(lambda name: name)


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


# ------------------------------------------------------------------- projection

#: Views that make the stored document queryable as ordinary tables.
#:
#: The graph is one JSON document in ``doc``; on its own that is a string SQL
#: cannot see into, which would leave the graph readable only by trikedb.
#: These views crack it open, so the same graph answers SPARQL from memory and
#: SQL from the warehouse — and Cortex, dbt, BI and a SQL-speaking MCP all see
#: plain tables with no extra copy to keep in step.
#:
#: ``TRY_PARSE_JSON`` rather than ``PARSE_JSON``: a graph saved by an older
#: trikedb still holds YAML, and plain PARSE_JSON raises on it — which would
#: take down the view for *every* graph in the table, not just the one that
#: has not been re-saved yet. TRY_ yields NULL instead, so an un-migrated row
#: contributes no rows and everyone else keeps working. Re-saving the graph
#: migrates it.
#:
#: Views rather than tables on purpose: nothing is stored twice, nothing can
#: drift, and the cost is zero. Snowflake pushes ``AT(TIMESTAMP => ...)`` down
#: to the base table, so a view reads the past as happily as the present. The
#: trade is that a view cannot prune; materialize (``CLUSTER BY NODE_TYPE`` on
#: nodes, ``EDGE_TYPE, SRC_ID, DST_ID`` on edges) if a graph ever grows big
#: enough for that to matter.
#:
#: KG_NODE and KG_EDGE follow the node/edge column shape conventionally used
#: for property graphs on Snowflake, so a semantic model or query written
#: against that shape works here too. The SQL is generated from trikedb's own
#: model; the projection is the one ``to_networkx()`` already performs, pointed
#: at SQL instead of networkx. KG_PREDICATE has no counterpart there — a
#: property graph's edge type is a bare label, while a predicate here is a
#: first-class name that the ontology describes, and dropping it would change
#: what the graph means.
_SNOWFLAKE_VIEWS = {
    "KG_NODE": (
        "SELECT g.name AS GRAPH,\n"
        "       n.key AS NODE_ID,\n"
        "       n.value:type::string  AS NODE_TYPE,\n"
        "       n.value:label::string AS NAME,\n"
        "       OBJECT_DELETE(n.value, 'type', 'label') AS PROPS,\n"
        "       g.updated_at AS TS_UPDATED\n"
        "FROM {table} g,\n"
        "     LATERAL FLATTEN(input => TRY_PARSE_JSON(g.doc):nodes) n"
    ),
    "KG_EDGE": (
        # A triple is unique on (s, p, o), so hashing those three gives a
        # stable id without storing one — re-running the view never renames
        # an edge that did not change.
        "SELECT g.name AS GRAPH,\n"
        "       MD5(t.value:s::string || '|' || t.value:p::string || '|' ||"
        " t.value:o::string) AS EDGE_ID,\n"
        "       t.value:s::string AS SRC_ID,\n"
        "       t.value:o::string AS DST_ID,\n"
        "       t.value:p::string AS EDGE_TYPE,\n"
        "       OBJECT_DELETE(t.value, 's', 'p', 'o') AS PROPS,\n"
        "       g.updated_at AS TS_UPDATED\n"
        "FROM {table} g,\n"
        "     LATERAL FLATTEN(input => TRY_PARSE_JSON(g.doc):triples) t"
    ),
    "KG_PREDICATE": (
        "SELECT g.name AS GRAPH,\n"
        "       p.key AS PREDICATE,\n"
        "       p.value::string AS DESCRIPTION\n"
        "FROM {table} g,\n"
        "     LATERAL FLATTEN(input => TRY_PARSE_JSON(g.doc):ontology:predicates) p"
    ),
    # The RDF view of the same rows, for anyone who thinks in triples.
    "KG_TRIPLE": (
        "SELECT g.name AS GRAPH,\n"
        "       t.value:s::string AS S,\n"
        "       t.value:p::string AS P,\n"
        "       t.value:o::string AS O,\n"
        "       OBJECT_DELETE(t.value, 's', 'p', 'o') AS ATTRS\n"
        "FROM {table} g,\n"
        "     LATERAL FLATTEN(input => TRY_PARSE_JSON(g.doc):triples) t"
    ),
}


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
    views=_SNOWFLAKE_VIEWS,
)

# ------------------------------------------------------------------- bigquery

def _bigquery_config_from_env() -> dict:
    """Connect kwargs for BigQuery.

    Credentials are Google's problem, not ours: the client picks up
    Application Default Credentials, a service-account key via
    ``GOOGLE_APPLICATION_CREDENTIALS``, or a workload identity, exactly as
    every other Google tool on the machine does. All we need is which
    project to bill.
    """
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("BIGQUERY_PROJECT")
    cfg: dict = {}
    if project:
        cfg["project"] = project
    location = os.environ.get("BIGQUERY_LOCATION")
    if location:
        cfg["location"] = location
    return cfg


def _bigquery_connect(config: dict):
    try:
        from google.cloud import bigquery
        from google.cloud.bigquery import dbapi
    except ImportError as exc:  # pragma: no cover - exercised via the message
        raise ImportError(
            "bigquery:// graph URLs require the BigQuery client - "
            "pip install 'trikedb[bigquery]'"
        ) from exc
    return dbapi.connect(bigquery.Client(**config))


#: BigQuery reaches the same compare-and-swap as Snowflake by a different
#: route, verified against a real dataset: a stale ``UPDATE`` reports 0
#: affected rows, a matching one reports 1, and a ``MERGE`` that finds the row
#: already there reports 0. What differs is spelling.
#:
#: - Parameters are named (``@name``), not positional, so the templates carry
#:   names and :func:`_execute` binds by them.
#: - JSON is opened with ``SAFE.PARSE_JSON`` + ``JSON_QUERY_ARRAY`` and
#:   ``UNNEST`` rather than ``LATERAL FLATTEN``. ``SAFE.`` is the same choice
#:   ``TRY_PARSE_JSON`` was: one row left in the old YAML format must not take
#:   the view down for every other graph in the table.
#: - There is no ``VARIANT``; a JSON subtree comes back as ``JSON``, and
#:   ``TO_JSON_STRING`` keeps the attribute bag readable.
#: - ``MD5`` returns bytes, so ``TO_HEX`` wraps it to match the hex EDGE_ID
#:   the other dialect produces.
_BIGQUERY_VIEWS = {
    "KG_NODE": (
        "SELECT g.name AS GRAPH,\n"
        "       n.name AS NODE_ID,\n"
        "       JSON_VALUE(n.props, '$.type')  AS NODE_TYPE,\n"
        "       JSON_VALUE(n.props, '$.label') AS NAME,\n"
        "       TO_JSON_STRING(n.props) AS PROPS,\n"
        "       g.updated_at AS TS_UPDATED\n"
        "FROM {table} g,\n"
        "     UNNEST([STRUCT(SAFE.PARSE_JSON(g.doc) AS parsed)]) d,\n"
        "     UNNEST(\n"
        "       ARRAY(SELECT AS STRUCT k AS name, d.parsed.nodes[k] AS props\n"
        "             FROM UNNEST(JSON_KEYS(d.parsed.nodes, 1)) AS k)\n"
        "     ) n"
    ),
    "KG_EDGE": (
        "SELECT g.name AS GRAPH,\n"
        "       TO_HEX(MD5(CONCAT(JSON_VALUE(t, '$.s'), '|',"
        " JSON_VALUE(t, '$.p'), '|', JSON_VALUE(t, '$.o')))) AS EDGE_ID,\n"
        "       JSON_VALUE(t, '$.s') AS SRC_ID,\n"
        "       JSON_VALUE(t, '$.o') AS DST_ID,\n"
        "       JSON_VALUE(t, '$.p') AS EDGE_TYPE,\n"
        "       TO_JSON_STRING(t) AS PROPS,\n"
        "       g.updated_at AS TS_UPDATED\n"
        "FROM {table} g,\n"
        "     UNNEST(JSON_QUERY_ARRAY(SAFE.PARSE_JSON(g.doc), '$.triples')) AS t"
    ),
    "KG_PREDICATE": (
        "SELECT g.name AS GRAPH,\n"
        "       k AS PREDICATE,\n"
        "       JSON_VALUE(d.parsed.ontology.predicates[k]) AS DESCRIPTION\n"
        "FROM {table} g,\n"
        "     UNNEST([STRUCT(SAFE.PARSE_JSON(g.doc) AS parsed)]) d,\n"
        "     UNNEST(JSON_KEYS(d.parsed.ontology.predicates, 1)) AS k"
    ),
    "KG_TRIPLE": (
        "SELECT g.name AS GRAPH,\n"
        "       JSON_VALUE(t, '$.s') AS S,\n"
        "       JSON_VALUE(t, '$.p') AS P,\n"
        "       JSON_VALUE(t, '$.o') AS O,\n"
        "       TO_JSON_STRING(t) AS ATTRS\n"
        "FROM {table} g,\n"
        "     UNNEST(JSON_QUERY_ARRAY(SAFE.PARSE_JSON(g.doc), '$.triples')) AS t"
    ),
}

BIGQUERY = _Dialect(
    name="bigquery",
    config_from_env=_bigquery_config_from_env,
    connect=_bigquery_connect,
    ddl=(
        "CREATE TABLE IF NOT EXISTS {table} (\n"
        "    name       STRING NOT NULL,\n"
        "    doc        STRING,\n"
        "    version    STRING NOT NULL,\n"
        "    updated_at TIMESTAMP\n"
        ")"
    ),
    select="SELECT doc, version FROM {table} WHERE name = %(name)s",
    update=(
        "UPDATE {table} SET doc = %(doc)s, version = %(version)s, "
        "updated_at = CURRENT_TIMESTAMP() "
        "WHERE name = %(name)s AND version = %(expect)s"
    ),
    insert_if_absent=(
        "MERGE {table} AS t "
        "USING (SELECT %(name)s AS name, %(doc)s AS doc, %(version)s AS version) AS s "
        "ON t.name = s.name "
        "WHEN NOT MATCHED THEN INSERT (name, doc, version, updated_at) "
        "VALUES (s.name, s.doc, s.version, CURRENT_TIMESTAMP())"
    ),
    upsert=(
        "MERGE {table} AS t "
        "USING (SELECT %(name)s AS name, %(doc)s AS doc, %(version)s AS version) AS s "
        "ON t.name = s.name "
        "WHEN MATCHED THEN UPDATE SET doc = s.doc, version = s.version, "
        "updated_at = CURRENT_TIMESTAMP() "
        "WHEN NOT MATCHED THEN INSERT (name, doc, version, updated_at) "
        "VALUES (s.name, s.doc, s.version, CURRENT_TIMESTAMP())"
    ),
    views=_BIGQUERY_VIEWS,
    # A GCP project id allows hyphens (and commonly has them), which is why
    # the pattern cannot be shared with Snowflake.
    identifier=r"^[A-Za-z0-9_-]+$",
    # Hyphens also mean the reference must be backtick-quoted, or the parser
    # reads `my-project-1234` as three names being subtracted.
    quote_table=staticmethod(lambda table: f"`{table}`"),
    # The BigQuery DB-API is pyformat, so the templates carry %(name)s and the
    # executor hands it a dict. `@name` is the *native* client's syntax; the
    # DB-API layer rejects it as "no placeholders".
    named_params=True,
)


#: scheme -> dialect. A new warehouse lands here and nowhere else: everything
#: it does differently — types, upsert syntax, how JSON is opened, how the
#: projection is spelled — is inside its _Dialect. Nothing above this line
#: mentions a warehouse by name.
DIALECTS = {"snowflake": SNOWFLAKE, "bigquery": BIGQUERY}




# -------------------------------------------------------------------- url parsing

#: The table name is interpolated into SQL — parameters cannot carry an
#: identifier — so it is checked against what an identifier may contain
#: rather than quoted. Unquoted also keeps Snowflake's own case folding,
#: which is what someone writing `mydb.public.t` expects.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")   # the default


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
    allowed = re.compile(dialect.identifier)
    if not 1 <= len(segments) <= 3 or not all(allowed.match(s) for s in segments):
        raise ValueError(
            f"{url}: expected {parts.scheme}://TABLE/graph-name, where TABLE is "
            "TABLE, SCHEMA.TABLE or DATABASE.SCHEMA.TABLE, and each part "
            f"matches {dialect.identifier}"
        )

    name = parts.path.lstrip("/")
    if not name:
        raise ValueError(
            f"{url}: no graph name - the path after the table names the row, "
            f"e.g. {parts.scheme}://{table}/sales/crm"
        )
    return dialect, ".".join(segments), name


def ddl_for(url: str, views: bool = True) -> str:
    """Every statement this URL's table needs, for review before running.

    The table, then the projection views beside it. Views cost nothing to
    keep and are what makes the graph readable from SQL at all, so they are
    part of setting the table up rather than an extra step to remember.
    """
    dialect, table, _ = _split(url)
    ref = dialect.quote_table(table)
    statements = [dialect.ddl.format(table=ref)]
    if views:
        schema = table.rsplit(".", 1)[0] if "." in table else ""
        for name, body in dialect.views.items():
            qualified = dialect.quote_table(f"{schema}.{name}" if schema else name)
            statements.append(
                f"CREATE OR REPLACE VIEW {qualified} AS\n"
                + body.format(table=ref)
            )
    return ";\n\n".join(statements)


def open_url(url: str, connection=None) -> "SqlGraphStore":
    return SqlGraphStore(*_split(url), url=url, connection=connection)


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


# --------------------------------------------------------------------- execute

def _named(dialect: _Dialect, sql: str, params: tuple):
    """Positional params as {name: value} for an engine that binds by name.

    The names come from the statement, in the order its placeholders appear,
    which is by construction the order the call site passes them in. Declaring
    them on the dialect instead meant one order had to serve four statements
    that take their arguments differently — and being wrong there does not
    raise, it compares the wrong column and reports a conflict.
    """
    if not dialect.named_params or not params:
        return params
    ordered = list(dict.fromkeys(re.findall(r"%\((\w+)\)s", sql)))
    if len(ordered) != len(params):
        raise ValueError(
            f"{dialect.name}: statement binds {ordered} but {len(params)} "
            "values were passed"
        )
    return dict(zip(ordered, params))


def _execute(conn, sql: str, params, want_rows: bool):
    """Run one statement on a DB-API connection or a Snowpark session.

    Two shapes reach us. A DB-API connection has ``cursor()`` and reports
    affected rows as ``cursor.rowcount``. A Snowpark ``Session`` has neither:
    ``session.sql(...).collect()`` returns rows either way, and for DML
    Snowflake's own answer *is* a row — ``number of rows updated`` — so the
    count is the first cell of the first row. Dispatch on the capability
    rather than on an imported type, so neither driver has to be installed
    for the other path to work.
    """
    if hasattr(conn, "cursor"):
        cursor = conn.cursor()
        try:
            cursor.execute(sql, params or None)
            return cursor.fetchall() if want_rows else cursor.rowcount
        finally:
            cursor.close()

    if hasattr(conn, "sql"):
        # Snowpark binds with ? where the connector binds with %s. Every
        # template here is ours and contains no other percent sign;
        # test_dialect_templates_only_use_percent_s holds that true.
        bound = list(params.values()) if isinstance(params, dict) else list(params or ())
        rows = conn.sql(sql.replace("%s", "?"), params=bound).collect()
        if want_rows:
            return [tuple(r) for r in rows]
        return int(rows[0][0]) if rows and len(rows[0]) else 0

    raise TypeError(
        f"{type(conn).__name__} is neither a DB-API connection (no cursor()) "
        "nor a Snowpark session (no sql()); pass one of those as connection="
    )


# ------------------------------------------------------------------------ store

class SqlGraphStore:
    """One graph, stored as one row. Mirrors the storage.py function set."""

    def __init__(self, dialect: _Dialect, table: str, name: str, url: str = "",
                 connection=None):
        self._dialect = dialect
        self._table = table
        self._name = name
        self._url = url or f"{dialect.name}://{table}/{name}"
        self._config: Optional[dict] = None
        #: an already-open connection or session to use instead of building
        #: one. Some hosts cannot build one at all: inside Streamlit in
        #: Snowflake there are no credentials to find and no outbound
        #: connection to make, only the session the host already holds.
        self._injected = connection

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
        sql = template.format(table=self._dialect.quote_table(self._table))
        params = _named(self._dialect, sql, params)
        if self._injected is not None:
            # Someone else owns this connection's lifetime, so there is
            # nothing to cache, drop or reconnect: hand the statement over
            # and let their errors surface as they are.
            return _execute(self._injected, sql, params, want_rows)
        config = self._settings()
        for remaining in (1, 0):
            conn = _connection(self._dialect, config)
            try:
                return _execute(conn, sql, params, want_rows)
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

    def create_table(self, views: bool = True) -> list:
        """Create the table, and the projection views beside it.

        One statement at a time: a warehouse driver runs one per call, and
        naming the statement that failed beats reporting that "the setup"
        did.
        """
        done = []
        self._run(self._dialect.ddl, (), want_rows=False)
        done.append(self._table)
        if not views:
            return done
        schema = self._table.rsplit(".", 1)[0] if "." in self._table else ""
        for name, body in self._dialect.views.items():
            plain = f"{schema}.{name}" if schema else name
            self._run(
                f"CREATE OR REPLACE VIEW {self._dialect.quote_table(plain)} AS\n"
                + body,
                (),
                want_rows=False,
            )
            done.append(plain)
        return done
