"""Where "whose credentials do we write to GitHub with" gets answered.

Each person registers their own GitHub personal access token from the
screen; it lands in one row of KG_OUTBOX_TOKEN. There are **two** layers of
protection here, and they have clearly separate jobs:

    outer   two policies   whoever queries, from anywhere in Snowflake,
                           only ever sees their own row
    inner   this module    inside the app, never look up anyone but the
                           person currently looking at the screen

The outer layer is a row access policy and a masking policy, both testing
`CURRENT_USER() = SF_USER`:

    rows    KG_OUTBOX_TOKEN_ROWS  CURRENT_USER() = SF_USER
    column  KG_OUTBOX_TOKEN_MASK  pass through when that holds, else '***'

**A policy expression is evaluated with the real user name, even inside the
app.** This is worth stating because it is easy to get backwards: run
`SELECT CURRENT_USER()` from inside a Streamlit in Snowflake app and you get
NULL, but `CURRENT_USER()` as seen from inside a policy expression is the
real name (and QUERY_HISTORY records that same real name for the query).
So **`CURRENT_USER()` cannot tell you "inside the app" from "in a
worksheet"** — it looks the same from both. Assuming otherwise once cost a
day: both policies were rewritten to `CURRENT_USER() IS NULL`, which is not
true inside the app either, and the result was another crop of rows that
could be written but never read.

The actual bug was never the condition. It was **the name**:
`str(CURRENT_USER())` became the string `"None"` and rows were stored under
that name. `CURRENT_USER() = 'None'` is of course never true. A row access
policy does not restrict INSERT, so writing kept succeeding all the way
through. The fix was to take the name from `st.user` instead (see
`curation.current_user`); the policies had been right the whole time.

The inner layer is this file. Even though the policy only returns the
caller's own row, **this class holds exactly one identity and returns None
for any other name without querying at all.** If somebody else's proposals
are queued against the same graph file, their token is never used — the
service simply defers those as "no linked account". It overlaps with what
the SQL already does, and it is deliberate for two reasons: policy work has
been gotten wrong here once already (above), and an attempt to write back
to another person's row should raise `OtherPersonsToken` rather than
quietly doing nothing. Locked down by
`tests/test_outbox.py::TestTokensOnlyServeTheViewer`.

Why not a Snowflake SECRET object:

* `CREATE SECRET ... SECRET_STRING='...'` **leaves the value unmasked in
  QUERY_HISTORY** (verified with a canary string). Since the screen is what
  creates it, that rules it out.
* A SECRET's value cannot be read back from SQL.

Never log the value. This module returns a token and does nothing else with
it — no printing, and nothing embedded in an exception message.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .sql import execute

#: What the masking policy returns to anyone but the owner. Putting that in
#: a Bearer header would send "***" to GitHub, so treat it as no credential
#: at all. It should never appear on your own row; it stays here so that a
#: future change to the policy condition cannot leak outward in silence.
_MASKED = "***"


@dataclass(frozen=True)
class Credential:
    """One person's GitHub credential."""

    token: str
    #: The GitHub account name to put in the commit's author field. Without
    #: one, the Snowflake user name shows up instead.
    gh_login: Optional[str] = None

    def __repr__(self) -> str:      # so a stray print cannot reveal it
        return f"Credential(gh_login={self.gh_login!r}, token=***)"


class OtherPersonsToken(Exception):
    """Something reached for a row belonging to somebody else.

    Raised rather than swallowed because the only way to get here is a
    wiring mistake. Returning None instead would disguise it as "no linked
    account" and let the mistake keep running.
    """


class SnowflakeTokens:
    """Reads KG_OUTBOX_TOKEN, using the screen's own session.

    `viewer` is **the person currently looking at the screen** (the name
    `curation.current_user` returns). Asked about anybody else, this returns
    None without querying. The service reads that as "no linked account" and
    defers; nothing else in the system decides whose token exists.

    The policy would not return another person's row either, but leaving it
    entirely to the policy makes "tried to read someone else's row"
    indistinguishable from **zero rows = no linked account**, and a wiring
    mistake would pass silently. Refusing here produces `OtherPersonsToken`.
    """

    def __init__(self, session, table: str, viewer: str) -> None:
        if not viewer:
            # Building this without a name means reaching for the row of
            # "nobody". That is how a real token once ended up in a row no
            # one could read.
            raise ValueError("viewer is empty")
        self._session = session
        self._table = table
        self._viewer = viewer
        self._cache: dict[str, Optional[Credential]] = {}

    def for_author(self, author: str) -> Optional[Credential]:
        if author != self._viewer:
            return None
        if author not in self._cache:
            self._cache[author] = self._load(author)
        return self._cache[author]

    def mark_used(self, author: str, error: Optional[str] = None) -> None:
        """Stamp the row with the time, and the reason if it failed.

        The screen shows both columns, so an expired or under-scoped token
        becomes visible to the person who owns it. The error string never
        contains the token — GitHub only hands back a 401 or 403.
        """
        if author != self._viewer:
            raise OtherPersonsToken("will not write to another person's row")
        execute(
            self._session,
            f"UPDATE {self._table} SET LAST_USED_AT = CURRENT_TIMESTAMP(), "
            f"LAST_ERROR = ? WHERE SF_USER = ?",
            [(error or "")[:4000] or None, author],
        )

    def _load(self, author: str) -> Optional[Credential]:
        # No filtering on an expiry date. GitHub tokens are created with a
        # lifetime in days, and a date typed into the screen is self-
        # reported — it drifts from the real one. Filtering on the drifted
        # value produces "still valid on GitHub, unusable from the screen",
        # with the reason visible nowhere. GitHub reports expiry as a 401,
        # so that goes into LAST_ERROR where the owner can see it.
        rows = execute(
            self._session,
            f"SELECT TOKEN, GH_LOGIN FROM {self._table} WHERE SF_USER = ?",
            [author],
        )
        if not rows:
            return None
        token, gh_login = rows[0][0], rows[0][1]
        if not token or token == _MASKED:
            return None
        return Credential(token=token, gh_login=gh_login)
