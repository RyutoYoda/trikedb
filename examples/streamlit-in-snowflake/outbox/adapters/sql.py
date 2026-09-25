"""One statement at a time. The only SQL knowledge in the adapter layer.

Streamlit in Snowflake hands you a Snowpark session; running the same code
from a laptop gives you a DB-API connection. Which one it is gets decided by
what the object can do rather than by an isinstance check, because there is
no guarantee that snowflake.connector is even installed inside the app.

Placeholders are `?` everywhere. Snowpark's `session.sql(sql, params=[...])`
**binds server-side**, so the query history keeps the `?`. DB-API's default
(pyformat) interpolates the values into the SQL text on the client before
sending it, so any statement carrying a secret must go through
`execute_bound` instead.
"""
from __future__ import annotations

from typing import Optional, Sequence


def execute(session, sql: str, params: Optional[Sequence] = None) -> list[tuple]:
    if hasattr(session, "cursor"):          # DB-API
        cur = session.cursor()
        try:
            cur.execute(sql.replace("?", "%s"), tuple(params or ()))
            return list(cur.fetchall())
        finally:
            cur.close()
    return [tuple(r) for r in session.sql(sql, params=list(params or [])).collect()]


def execute_bound(session, sql: str, params: Sequence) -> list[tuple]:
    """A statement carrying a secret. Server-side binding or nothing.

    If the connection cannot bind, refuse here rather than quietly sending
    the secret as literal text.
    """
    if not hasattr(session, "sql"):
        raise RuntimeError(
            "this connection cannot bind server-side, so the statement was "
            "not run (it would leave the value in the query history)")
    return [tuple(r) for r in session.sql(sql, params=list(params)).collect()]
