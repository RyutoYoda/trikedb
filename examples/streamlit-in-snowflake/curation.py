"""Propose facts from a screen. This writes to KG_OUTBOX, not to the graph.

Until this screen existed, the only people who could add a fact to the graph
were the people who could write YAML and open a pull request. The person who
*knows* a fact and the person who can *write* it are usually not the same
person, so the knower had to tell someone -- and if that someone forgot, the
fact never landed. Nobody could see what failed to land.

This is the entrance. **The source of truth is still git.** This screen does
not rewrite the graph it reads. It writes rows into a proposal table
(`KG_OUTBOX`), and from there `outbox/` stacks them onto one branch per day
and opens a pull request:

    type it in  ->  queued as a proposal  ->  PR  ->  review  ->  lands in YAML

Why not write the graph directly? The Snowflake copy of the graph is a
derived artifact -- something regenerates it from the YAML. Writing to it
would be silently erased by the next deploy, and nobody would notice the
erasure.

The PR is opened **by the session of the person who pressed the button**,
using the token *they* registered. An earlier design had a scheduled job
batch everything up once a day with one shared token; that meant one shared
role could read everyone's credentials, and it added a moving part between
the person and their PR. Now there is exactly one hole out of Snowflake,
`api.github.com:443` (see `outbox/wire.py`).

This screen runs proposals through the ontology guard too, but that is a
**courtesy, not a defence**. The defence is in `outbox/domain.py`, which runs
them through again just before building the PR -- because `KG_OUTBOX` is a
table, and tables can be written to from somewhere that isn't this screen.
"""
from __future__ import annotations

import json
import os
from typing import NamedTuple

import streamlit as st

import graph_store
from i18n import t
from outbox import domain, wire
from outbox.adapters import sql as _sql

# --------------------------------------------------------------- change these
TABLE = "DEMO_DB.KG.KG_OUTBOX"

#: GitHub personal access tokens, one row per proposer. The table carries a
#: row access policy and a masking policy, both of which test
#: `CURRENT_USER() = SF_USER` (see outbox/adapters/tokens.py for what those
#: do and, more importantly, for why they are not enough on their own).
#: Do not lean on the policies: always add `WHERE SF_USER = ?` here too.
TOKEN_TABLE = "DEMO_DB.KG.KG_OUTBOX_TOKEN"

#: Where the pull requests go. Ask people to scope their token to this one
#: repository and nothing else.
REPO = "your-org/your-graph-repo"

#: Timezone for every timestamp this screen prints. Snowflake stores these
#: columns as TIMESTAMP_LTZ, which renders in the *session* timezone -- and
#: the session default is whatever the account was created with, not where
#: your colleagues are sitting. See `_localtime`.
DISPLAY_TIMEZONE = "Asia/Tokyo"
# -----------------------------------------------------------------------------

#: Where the union view lives. In Streamlit in Snowflake it is the copy
#: staged with the app; when you run the app locally it is the repository
#: checkout. Same order `streamlit_app.py` uses to find the graph itself.
WORKSPACES = ("kg/workspace.yaml",
              os.path.join("..", "..", "ontology", "workspace.yaml"))


def targets(path: str = "") -> list[str]:
    """The YAML files that accept proposals.

    Deliberately not a hardcoded list. The moment you write one, you create
    the possibility of a YAML that is in `workspace.yaml` but cannot be
    picked on screen -- and that failure is invisible. The staged copy is a
    snapshot from app build time, so a file added yesterday may not appear;
    when that happens the person types the name into "create new" and the
    service treats it as existing (it reads the branch and only calls it new
    if the file is genuinely empty).

    `workspace.yaml` itself is a read-only union, so it is never listed.
    """
    for candidate in ([path] if path else WORKSPACES):
        members = graph_store.workspace_members(candidate)
        if members:
            return [f"{stem}.yaml" for stem in members.values()
                    if stem != "workspace"]
    return []


# ------------------------------------------------------------------ Snowflake

def _exec(session, sql: str, params: list | None = None) -> list:
    """Run one statement. The implementation is `outbox/adapters/sql.py`.

    The screen goes through the same function as the PR path so that the
    meaning of `?` is decided in exactly one place. Streamlit in Snowflake
    hands you a Snowpark session; running the same code from your laptop
    hands you a DB-API connection, and they bind differently.
    """
    return _sql.execute(session, sql, params or [])


def _localtime(column: str) -> str:
    """A SQL fragment that renders a timestamp column in DISPLAY_TIMEZONE.

    The timestamp columns are `TIMESTAMP_LTZ`, which means a bare SELECT
    returns them in the **session** timezone. The session default is the
    account default, which is very likely not where the people using the
    screen are: ours was `America/Los_Angeles`, so every time on the screen
    was 16 hours off, and it looked plausible enough that nobody questioned
    it for a while.

    `ALTER SESSION SET TIMEZONE` would fix the display, but it would also
    change what `CURRENT_TIMESTAMP()` means on the *write* side. Only the
    display is wrong, so only the display is converted -- here, per SELECT.
    """
    return f"CONVERT_TIMEZONE('{DISPLAY_TIMEZONE}', {column})"


#: Values that are not names. Inside a Streamlit in Snowflake app,
#: `SELECT CURRENT_USER()` returns **NULL**, so passing the result straight
#: to `str()` turns the string `"None"` into somebody's identity. That
#: happened: both the AUTHOR of proposals and the SF_USER on stored tokens
#: became the literal string "None".
_NOT_A_NAME = frozenset({"", "none", "null", "unknown", "nan"})


def _viewer_name() -> str:
    """Who Streamlit thinks is looking at this page.

    A `SELECT CURRENT_USER()` issued from inside the app returns NULL. The
    only component that knows the name is Streamlit, which is serving the
    page. (Confusingly, `CURRENT_USER()` *inside a policy expression* is the
    real name -- see `outbox/adapters/tokens.py`, because that distinction
    is the whole reason the token table is safe.)

    `st.user` is the current spelling; older releases have
    `st.experimental_user`. Some releases have neither, and some raise on
    attribute access, so try each and take the first that answers.
    """
    for holder in ("user", "experimental_user"):
        obj = getattr(st, holder, None)
        for attr in ("user_name", "username", "login", "email"):
            try:
                value = getattr(obj, attr, None)
            except Exception:  # noqa: BLE001 - older builds raise on access
                continue
            if isinstance(value, str) and value.strip().lower() not in _NOT_A_NAME:
                return value.strip()
    return ""


def current_user(session) -> str | None:
    """Whose name to queue under, and whose credential to publish with.
    **Returns None when it cannot tell.**

    This used to be `str(CURRENT_USER())`. Inside the app that is NULL, so
    the string `"None"` was stored as an identity. The row access policy
    evaluates `CURRENT_USER() = SF_USER`, i.e. `'real name' = 'None'`, which
    is never true -- so the write created **a row its own author could not
    read**. INSERT is not restricted by a row access policy, so the write
    side kept succeeding all the way through. The screen just said "not
    registered", and registering again only produced another unreadable row.

    That is what returning *something* when you don't know costs. If you
    don't know, return None and let the caller stop.
    """
    name = _viewer_name()
    if name:
        return name
    # Running locally over DB-API, this path returns the real name.
    try:
        value = _exec(session, "SELECT CURRENT_USER()")[0][0]
    except Exception:  # noqa: BLE001 - there may be no session at all
        return None
    if value is None or str(value).strip().lower() in _NOT_A_NAME:
        return None
    return str(value).strip()


def insert(session, *, author: str, target_yaml: str, op: str,
           payload: dict, note: str, prov: str) -> None:
    _exec(
        session,
        f"INSERT INTO {TABLE} (AUTHOR, TARGET_YAML, OP, PAYLOAD, NOTE, PROV) "
        f"SELECT ?, ?, ?, PARSE_JSON(?), ?, ?",
        [author, target_yaml, op, json.dumps(payload, ensure_ascii=False),
         note, prov],
    )


def insert_many(session, *, author: str, target_yaml: str,
                ops: list[tuple[str, dict]], note: str, prov: str) -> None:
    """Queue everything one submission produced, **in order**.

    One form can produce several proposals because adding a single edge may
    also require declaring the predicate and writing attributes on both
    endpoints. The order carries meaning (you cannot use a predicate you
    have not declared), so they are queued as separate proposals rather than
    collapsed into one row. The other benefit of that shape: each one can be
    refused independently, so a rejected attribute doesn't take the edge
    down with it.
    """
    for op, payload in ops:
        insert(session, author=author, target_yaml=target_yaml, op=op,
               payload=payload, note=note, prov=prov)


def _exec_secret(session, sql: str, params: list) -> None:
    """A statement containing a secret. **Server-side binding only.**

    The implementation is `outbox/adapters/sql.execute_bound`. The reason is
    measured, not theoretical: DB-API's default paramstyle interpolates
    values into the SQL text on the client before sending it, so the token
    ends up verbatim in `QUERY_HISTORY.QUERY_TEXT`. Snowpark's
    `session.sql(sql, params=[...])` binds server-side and the history keeps
    the literal `?`.

    The same measurement is why this does not use Snowflake SECRET objects:
    `CREATE SECRET ... SECRET_STRING='...'` puts the value **unmasked** into
    query history (verified by storing a canary string and then reading it
    back out of history). A SECRET's value also cannot be read back from
    SQL, which this path needs to do.
    """
    _sql.execute_bound(session, sql, params)


def token_status(session, author: str) -> tuple | None:
    """`(GH_LOGIN, LAST4, LAST_USED_AT, LAST_ERROR)` if registered.

    The TOKEN column is never selected. Inside the app it would come back in
    the clear, and the most reliable way not to leak a value is not to ask
    for it.

    There is no expiry column. GitHub issues fine-grained tokens in terms of
    "N days", not a date you pick, so asking the person to type an expiry
    date gets you a number that **may not be the real expiry**. Expiry shows
    up on its own as a 401 from GitHub in LAST_ERROR, which is more truthful
    than self-reporting -- so the self-reporting was removed.
    """
    rows = _exec(
        session,
        f"SELECT GH_LOGIN, LAST4, {_localtime('LAST_USED_AT')}, LAST_ERROR "
        f"FROM {TOKEN_TABLE} WHERE SF_USER = ?",
        [author],
    )
    return rows[0] if rows else None


def save_token(session, *, author: str, token: str, gh_login: str) -> None:
    """Replace this person's row.

    DELETE + INSERT rather than MERGE because TOKEN carries a masking
    policy. Statements that both read and write a masked column can be
    rejected depending on the policy, so this is shaped to never read the
    column: the value only ever arrives through a bind. It is one row
    belonging to one person, so there is nothing to contend with.

    `author` is whatever `current_user` returned. It is never None here --
    `render` stops before this point.
    """
    _exec(session, f"DELETE FROM {TOKEN_TABLE} WHERE SF_USER = ?", [author])
    _exec_secret(
        session,
        f"INSERT INTO {TOKEN_TABLE} "
        f"(SF_USER, TOKEN, GH_LOGIN, LAST4) SELECT ?, ?, ?, ?",
        [author, token, gh_login or None, token[-4:]],
    )


def revoke_token(session, author: str) -> None:
    _exec(session, f"DELETE FROM {TOKEN_TABLE} WHERE SF_USER = ?", [author])


def mine(session, author: str, limit: int = 20) -> list:
    """This person's proposals, newest first, timestamps localised."""
    return _exec(
        session,
        f"SELECT {_localtime('CREATED_AT')}, TARGET_YAML, OP, TO_JSON(PAYLOAD), "
        f"STATUS, PR_URL, ERROR FROM {TABLE} WHERE AUTHOR = ? "
        f"ORDER BY CREATED_AT DESC LIMIT {int(limit)}",
        [author],
    )


def _when(value) -> str:
    """Format a timestamp for display (already localised by `_localtime`)."""
    return value.strftime("%m/%d %H:%M") if hasattr(value, "strftime") \
        else str(value)


# --------------------------------------------------------------- guard rehearsal

def _member_path(db, target: str) -> str | None:
    """Where, inside the union, the graph for this one YAML actually lives.

    A union holds `{key: location}` -- `snowflake://.../<name>` when running
    in Snowflake, `ontology/<name>.yaml` when running locally. The key is a
    short name chosen by `workspace.yaml` and is **not** the file name
    (`cost` vs `cost_ops.yaml`), so match on the tail of the location,
    not on the key.

    Relative paths resolve against the location of the union file, the same
    way trikedb resolves them when it opens a member. Resolving against the
    process working directory instead would, locally, point at a different
    file -- usually one that does not exist.
    """
    stem = os.path.splitext(target)[0]
    for path in (db.workspace or {}).values():
        path = str(path)
        if os.path.splitext(path.rsplit("/", 1)[-1])[0] != stem:
            continue
        if (not graph_store.trikedb.storage.is_remote(path)
                and not os.path.isabs(path) and db.path):
            path = os.path.join(os.path.dirname(str(db.path)), path)
        return path
    return None


def _trial_graph(db, session, target: str, *, fresh: bool):
    """A writable graph to rehearse the proposals against.

    The rehearsal happens against **the one target YAML**, not the union.
    Two reasons.

    First, a union cannot be written to. `db` is a read-only view stacking
    every member graph, and even taking a copy of it (`db.save()`) is
    refused by the guard.

    Second, rehearsing against the union would test the wrong thing. A PR
    lands in one YAML file, so rehearsing against the union lets a proposal
    pass here on the strength of a predicate that some *other* YAML
    declared, and then get refused for real just before the PR is built. All
    the proposer sees is "it didn't make it into the PR", with no reason.

    The trial graph has no save target. The source of truth is git and this
    screen does not rewrite the Snowflake copy (see the module docstring);
    there is no reason to leave it in a state where an accidental save could
    succeed.
    """
    # A fresh (not-yet-existing) YAML, or one the union doesn't know about,
    # starts from an empty graph. Either way its vocabulary is empty, so
    # even a predicate picked from the dropdown is unusable here.
    path = None if fresh else _member_path(db, target)
    copy = graph_store.trikedb.TrikeDB(path, connection=session, autosave=False)
    copy.path = None
    return copy


def _brief(exc: Exception) -> str:
    """One line to show when the rehearsal blows up.

    Pasted verbatim, an exception like a ValueError listing a dozen graph
    locations fills the screen with something the reader cannot act on. Not
    hidden, but cut to one line.
    """
    text = " ".join(str(exc).split())
    return f"{text[:200]}…" if len(text) > 200 else text


def dry_run(db, ops: list[tuple[str, dict]], *, session, author: str,
            target: str, note: str, prov: str, fresh: bool = False) -> str | None:
    """Apply the proposals **in order** to a copy of the target YAML and
    return the reason if the guard refuses one.

    In order, not one at a time, because the order carries meaning: declare
    the new predicate, then connect two nodes with it. Looking at the first
    one alone tells you nothing about whether the second will pass.

    The rehearsal goes through `domain.apply` specifically so it uses **the
    same implementation that builds the PR**. An earlier version re-handled
    the ops here by hand, and the result was that the screen would accept
    proposals that could never actually be built (an `add_triple` into a
    YAML with no vocabulary).

    Something that passes here can still be refused at PR time: this sees
    the copy in Snowflake, while the PR applies to the YAML on today's
    branch, which has already moved forward by whatever landed earlier the
    same day. That is why the defence lives on the other side, and this
    exists only to tell people sooner.
    """
    proposals = [
        domain.Proposal(id=f"dry-{i}", author=author, target_yaml=target,
                        op=op, payload=payload, note=note, prov=prov)
        for i, (op, payload) in enumerate(ops)
    ]
    try:
        outcome = domain.apply(_trial_graph(db, session, target, fresh=fresh),
                               proposals)
    except Exception as exc:  # noqa: BLE001 - show the reason whatever it is
        return _brief(exc)
    return outcome.refused[0][1] if outcome.refused else None


# ------------------------------------------------------------------------ UI

class Problem(NamedTuple):
    """A refusal, plus **which field it belongs under**.

    `field` is a tag, not a sentence: "predicate", "yaml", "event",
    "attribute", or "" for "no particular field". It exists because
    `_show_problem` used to work out where to print a refusal by looking for
    the word "predicate" or "yaml" *inside the message* -- which worked
    exactly as long as there was one language. Translate the message and
    every refusal silently falls through to the bottom of the page, which is
    the failure this screen was built to stop.

    Messages from `outbox.domain` stay plain strings and stay English: they
    are also written into PR bodies and into the `ERROR` column, where one
    language is the right answer and the reader is not necessarily the
    person who pressed the button. `_show_problem` keeps the old substring
    routing for those.
    """
    field: str
    text: str

    def __str__(self) -> str:        # so it can be printed like a message
        return self.text


def _props_from_rows(rows, where: str = "") -> tuple[dict, Problem | None]:
    """Turn the attribute inputs into a dict, ignoring blank rows.

    This used to be a free-text box that wanted `name: value` on each line.
    It looked exactly like the plain name field next to it but demanded a
    format, so people believed the look rather than the format, typed a
    single word, and got rejected. The fix was to stop demanding a format:
    name and value are now two ordinary fields.

    A half-filled row is an error. Both blank means it wasn't typed, so skip
    it silently; one side filled means it was being typed, and dropping that
    silently produces "the attribute I entered isn't there".
    """
    where = where or t("field.attrs_generic")
    props: dict[str, str] = {}
    for i, row in enumerate(rows or [], 1):
        name = str(row.get("name") or "").strip()
        value = str(row.get("value") or "").strip()
        if not name and not value:
            continue
        if not name:
            return {}, Problem("attribute", t(
                "err.attr_no_name", where=where, row=i, value=repr(value)))
        if not value:
            return {}, Problem("attribute", t(
                "err.attr_no_value", where=where, row=i, name=repr(name)))
        props[name] = value
    return props, None


def _pick_or_type(widget, label: str, options: list, key: str,
                  placeholder: str, **kw) -> str:
    """One field that accepts either an existing choice or a new name.

    This used to be **two fields** ("pick one" with "or type a new name"
    underneath), because inside a form the page does not redraw when you
    change a selection, so "grow a field once 'new' is selected" was not
    possible. In other words the two fields existed for our convenience and
    explained nothing to the person using them -- and sure enough, the
    feedback was "I have no idea why there are two of these."

    Streamlit 1.47's `accept_new_options` collapses it into one field: type
    something and an "add" entry appears. That is why `environment.yml`
    pins a minimum version.
    """
    return (widget.selectbox(label, options, index=None, key=key,
                             placeholder=placeholder,
                             accept_new_options=True, **kw) or "").strip()


def _node_field(col, label: str, nodes: list, key: str) -> str:
    """Either end of the relationship. Being able to type a name that is not
    in the list is the entire point of this screen, so it must stay."""
    return _pick_or_type(col, label, nodes, f"pick_{key}",
                         t("ph.pick_or_new_name"))


#: How many attribute rows to draw. One or two labels on a node is typical,
#: and if you need a third the proposal is probably easier to review split
#: in two. Inside a form, an "add row" button would not redraw until submit,
#: so the count is fixed.
_PROP_ROWS = 2


def _props_field(col, label: str, key: str) -> list[dict]:
    """Labels to attach to a node. Only ever shown inside the collapsed section.

    This field tripped people up three times running. As a free-text box
    demanding `name: value` they tripped on the format; turned into a table
    (`st.data_editor`), the complaint was "why is only this one a table?"
    Note that the answer is **not** to go back to free text -- that failure
    mode is already known.

    The third time the common factor was finally visible: both versions were
    *shaped differently from everything around them*. Every other field on
    the screen is a plain input; this one was a table, or had a format. So
    name and value became two plain inputs identical to the rest. A fixed
    row count is what that costs, and **looking like everything else is
    worth more**.
    """
    col.markdown(f"**{label}**")
    rows = []
    for i in range(_PROP_ROWS):
        n, v = col.columns(2)
        # Label the first pair only. Repeating the words down the column
        # makes the second pair read as a different kind of thing.
        vis = "visible" if i == 0 else "collapsed"
        rows.append({
            "name": n.text_input(t("field.attr_name"), key=f"pn_{key}{i}",
                                 placeholder=t("ph.attr_name"),
                                 label_visibility=vis),
            "value": v.text_input(t("field.attr_value"), key=f"pv_{key}{i}",
                                  placeholder=t("ph.attr_value"),
                                  label_visibility=vis),
        })
    return rows


def _prop_keys() -> list[str]:
    return [f"p{c}_{side}{i}" for side in "so"
            for i in range(_PROP_ROWS) for c in "nv"]


def _typed(*keys: str) -> bool:
    """Has anything been typed inside the collapsed section?

    If so, draw it open. Pressing submit redraws the page, so leaving it
    collapsed by default would hide **both what the person typed and the
    error printed against it**. Saying "attributes row 2 has a name but no
    value" while that row is invisible is the worst of both.
    """
    return any(st.session_state.get(k) for k in keys)


def _show_problem(problem, slots) -> None:
    """Print the refusal directly under the field that caused it.

    It used to be one message at the very bottom of the page, *below* a long
    block of explanatory text. People look where they just typed, so it
    never got read -- someone re-pressed the same button repeatedly while
    "predicate name is not UPPER_SNAKE_CASE" sat on screen, because nothing
    said which field it meant.

    The trick is to reserve empty slots (`st.empty`) inside the form and
    write into them afterwards: the form has finished drawing, but the slots
    are still there to fill. When no field can be identified, fall back to
    the message at the bottom.

    Two kinds of thing arrive here. A `Problem` names its field outright, so
    it routes on that. A plain string comes from `outbox.domain`, is always
    English, and routes the old way -- on the word "predicate" or "yaml"
    appearing in it, or on the field's own value appearing quoted. Keeping
    the second path is not nostalgia: `domain` must not learn what language
    the screen is in, because its messages also end up in PR bodies.
    """
    field = getattr(problem, "field", "")
    msg = str(problem)
    for value, hint, slot in slots:
        if slot is None:
            continue
        if field:
            if hint == field:
                slot.error(msg)
                return
            continue
        if hint in msg or (value and f"'{value}'" in msg):
            slot.error(msg)
            return
    st.error(msg)


#: Somewhere to park "saved" across a rerun. `st.rerun()` throws the page
#: away and redraws, so an `st.success` printed before the rerun is **never
#: seen once**. That produced "I can't tell whether it saved."
_JUST_SAVED = "kg_token_just_saved"
#: A generation counter used to blank only the token field.
#: `clear_on_submit=True` would also wipe the username when the submission
#: failed, so instead the widget key is rotated on success -- which yields a
#: new, empty widget. (Popping a widget key directly can raise
#: StreamlitAPIException, hence the counter.)
_TOKEN_ROUND = "kg_token_round"
#: Revocation crosses a rerun for the same reason.
_REVOKED = "kg_token_revoked"


def _login(picked: str, typed: str, fallback: str) -> str:
    """Decide the GitHub username used as the commit author.

    Typed wins over picked, the same promise every other field on this
    screen makes. If both are empty, fall back to the Snowflake username --
    it will not resolve to a GitHub account, but at least the history says
    whose proposal it was.
    """
    return (typed or "").strip() or (picked or "").strip() or fallback


def _github_link(session, author: str) -> None:
    """Register, replace or revoke the GitHub credential.

    One credential per Snowflake username. Commits in the PR belong to the
    proposer because they are written with the proposer's own token -- write
    everything with one shared token and, in the history, every proposal by
    everyone is the same bot.
    """
    status = token_status(session, author)

    if st.session_state.pop(_REVOKED, False):
        st.info(t("gh.revoked"))

    just_saved = st.session_state.pop(_JUST_SAVED, None)
    if just_saved:
        # The message that had to survive the rerun. Without it, a closed
        # expander is ambiguous: did it save, or did it just close?
        st.success(t("gh.registered_as", login=just_saved))

    if status:
        login, last4, used_at, last_error = status
        st.success(t("gh.status", login=login or author, last4=last4))
        if last_error:
            # What GitHub actually said the last time this token was used to
            # write. Expiry and missing scopes both surface here.
            st.warning(t("gh.last_error", error=last_error))
        elif used_at:
            st.caption(t("gh.last_used", when=_when(used_at)))
    else:
        st.warning(t("gh.none_registered"))

    label = t("gh.expander_replace" if status else "gh.expander_register")
    with st.expander(label, expanded=not status):
        st.markdown(t("gh.howto", repo=REPO))

        saved_login = status[0] if status else ""
        round_ = st.session_state.get(_TOKEN_ROUND, 0)

        # No clear_on_submit: it would also wipe the username when the token
        # came back empty, which meant retyping. Only the token field should
        # clear, so the key is rotated on success instead.
        with st.form("github_token", clear_on_submit=False):
            if saved_login:
                # Once registered, stop asking. Replacing usually means
                # replacing the token; the name stays the same.
                gh_pick = st.selectbox(
                    t("gh.username"), [saved_login], index=0,
                    help=t("gh.username_registered_help"))
                gh_typed = st.text_input(
                    t("gh.use_other_name"), key=f"gh_login_{round_}",
                    label_visibility="collapsed",
                    placeholder=t("gh.other_name_placeholder",
                                  login=saved_login))
            else:
                gh_pick = ""
                gh_typed = st.text_input(
                    t("gh.username"), key=f"gh_login_{round_}",
                    placeholder="octocat",
                    help=t("gh.username_help"))
            gh_login = _login(gh_pick, gh_typed, author)

            token = st.text_input(
                t("gh.token"), type="password", key=f"gh_token_{round_}",
                placeholder="github_pat_...",
                help=t("gh.token_help"))
            saved = st.form_submit_button(
                t("gh.submit_replace" if status else "gh.submit_register"),
                type="primary")

        if saved:
            if not token.strip():
                # Do not clear the name. Clearing it is what caused retyping.
                st.error(t("gh.token_empty"))
            else:
                save_token(session, author=author, token=token.strip(),
                           gh_login=gh_login)
                st.session_state[_JUST_SAVED] = gh_login
                st.session_state[_TOKEN_ROUND] = round_ + 1
                st.rerun()

        st.caption(t("gh.storage_note"))

    if status and st.button(t("gh.revoke"), key="revoke_token"):
        revoke_token(session, author)
        # Same reason as registration: the message has to outlive the rerun.
        st.session_state[_REVOKED] = True
        st.rerun()


def render(session, db, schema) -> None:
    st.caption(t("intro.caption"))

    if session is None:
        st.warning(t("err.no_session"))
        return

    author = current_user(session)
    if author is None:
        st.error(t("err.no_identity"))
        st.caption(t("err.no_identity_detail"))
        return
    _github_link(session, author)
    st.divider()

    nodes = sorted(db.nodes())
    preds = sorted(schema.get("predicate_defs", {})) or sorted(db.predicates())

    # There is deliberately no mode selector. What people want to add is
    # almost always one edge -- "A does this to B" -- and being able to note
    # what you know about the endpoints at the same time is natural. To add
    # attributes only, leave the relationship blank and fill in one side.
    with st.form("proposal", clear_on_submit=False):
        c1, c2, c3 = st.columns(3)
        s_name = _node_field(c1, t("field.subject"), nodes, "s")
        o_name = _node_field(c3, t("field.object"), nodes, "o")

        predicate = _pick_or_type(c2, t("field.relationship"), preds, "pick_p",
                                  t("ph.pick_or_new_pred"))
        p_desc = c2.text_input(
            t("field.pred_meaning"), key="desc_p",
            placeholder=t("ph.pred_meaning"))
        # "Is this a new predicate" is decided by **whether it is in the
        # list**. It used to be decided by whether anything had been typed
        # into the "new predicate" box, so typing an existing name in there
        # produced a proposal to re-declare it.
        is_new_pred = bool(predicate) and predicate not in preds

        # **Always** say something about the predicate: what it means if it
        # exists, what the naming rule is if it doesn't. The rule used to
        # live in the placeholder, which disappears the moment you start
        # typing -- so nobody learned it until they were rejected.
        if predicate and not is_new_pred:
            c2.caption(t("hint.pred_known", name=predicate,
                         meaning=schema.get("predicate_defs", {})
                                       .get(predicate, "")))
        else:
            c2.caption(t("hint.pred_naming"))
        # Reserved slot, filled after the form is drawn -- there is nothing
        # to say until the button is pressed.
        err_p = c2.empty()

        # Keep the three columns above readable as one sentence. Attributes
        # are optional and occasional, so they collapse in here; anyone who
        # needs them can open it, and a proposal works fine with it shut.
        with st.expander(t("expander.attrs"),
                         expanded=_typed(*_prop_keys())):
            st.caption(t("hint.attrs"))
            a1, a2 = st.columns(2)
            s_props = _props_field(a1, t("field.subject_attrs"), "s")
            o_props = _props_field(a2, t("field.object_attrs"), "o")
            err_props = st.empty()

        # Events collapse too -- same reasoning, it's a field you either
        # need today or don't. But the closed section still shows its label:
        # if people don't know events can be recorded here, they won't be.
        with st.expander(t("expander.event"),
                         expanded=_typed("at_event")):
            st.caption(t("hint.event"))
            at = st.date_input(t("field.when"), value=None,
                               format="YYYY-MM-DD", key="at_event",
                               help=t("help.when"))
            err_at = st.empty()

        known = targets()
        target = _pick_or_type(
            st, t("field.which_yaml"), known, "pick_target",
            t("ph.which_yaml"), help=t("help.which_yaml"))
        err_t = st.empty()
        note = st.text_area(t("field.note"), placeholder=t("ph.note"),
                            help=t("help.note"))
        prov = st.text_input(t("field.prov"), placeholder=t("ph.prov"))

        submitted = st.form_submit_button(t("btn.propose"), type="primary")

    st.caption(t("foot.caption"))

    if not submitted:
        _history(session, author)
        return

    ops, problem = _bundle(s_name, s_props, predicate, is_new_pred, p_desc,
                           o_name, o_props, at=_at(at), known_nodes=nodes)
    target, target_problem = _target(target, known)
    # Work out which field a refusal is about from its wording. Predicate,
    # then YAML, then attributes -- that is the order in which the name
    # tends to appear verbatim in the message.
    slots = ((predicate, "predicate", err_p),
             (target, "yaml", err_t),
             ("", "event", err_at),
             ("", "attribute", err_props))

    if problem or target_problem:
        _show_problem(problem or target_problem, slots)
    elif not note.strip() or not prov.strip():
        st.error(t("err.note_and_prov"))
    else:
        why = dry_run(db, ops, session=session, author=author, target=target,
                      note=note.strip(), prov=prov.strip(),
                      fresh=target not in known)
        if why:
            # Refused proposals are not queued. Queueing them only means
            # being refused again at build time, where all the proposer sees
            # is that it never made it into a PR.
            # `why` stays English -- it comes from `domain`, and the
            # substring routing above reads it.
            _show_problem(t("err.guard", why=why), slots)
        else:
            insert_many(session, author=author, target_yaml=target, ops=ops,
                        note=note.strip(), prov=prov.strip())
            _publish(session, target, author)

    _history(session, author)


def _target(name: str, known: list[str]) -> tuple[str, Problem | None]:
    """Which YAML to propose into. A name not in the list means "create it".

    One field here too (it used to be "pick" plus "new name"). The default
    selection was dropped as well -- better to make people choose than to
    send a proposal to a file they never picked.

    The name check lives in `domain`. The same name can arrive from paths
    that never touch this screen, so the defence belongs on one side only.
    """
    name = (name or "").strip()
    if not name:
        return "", Problem("yaml", t("err.pick_yaml"))
    if not name.endswith(".yaml"):
        name += ".yaml"
    try:
        domain.check_target_name(name)
    except domain.Refused as exc:
        # Straight from `domain`, so English -- see `Problem`.
        return "", Problem("yaml", str(exc))
    if name not in known:
        # If they typed the name of a file that does exist, treat it as
        # existing without comment -- the service reads the branch and only
        # calls it new if the content is genuinely empty.
        st.caption(t("info.will_be_created", name=name))
    return name, None


def _at(value) -> str:
    """Normalise "when" to a `YYYY-MM-DD` string; empty stays empty.

    `st.date_input` returns a date, but tests pass strings, so both work.
    The date format is decided in this one place -- `at:` in the graph is a
    string, and once the format varies you can no longer filter by range.
    """
    if not value:
        return ""
    return (value.isoformat() if hasattr(value, "isoformat")
            else str(value).strip())


def _bundle(s_name: str, s_props, predicate: str, is_new_pred: bool,
            p_desc: str, o_name: str, o_props, *, at: str = "",
            known_nodes=()) -> tuple[list[tuple[str, dict]], Problem | None]:
    """Turn one submitted form into proposals, ordered the way they apply.

    The order is: declare the predicate, then the endpoint nodes, then the
    edge. Any other order and an edge using a new predicate is refused by
    the ontology guard.

    A non-empty `at` makes it an **event**: the edge gets a date, and the
    object is registered as a `type: event` node -- because "the object of
    AFFECTED_BY must be type:event" is a convention of this graph, and there
    is no reason to make everyone using the screen memorise it.
    """
    ops: list[tuple[str, dict]] = []

    if is_new_pred:
        if not p_desc.strip():
            return [], Problem("predicate", t("err.new_pred_needs_desc"))
        ops.append(("declare_link", {
            "name": predicate, "description": p_desc.strip()}))

    props: dict[str, dict] = {}
    for label, name, raw in ((t("err.where_subject"), s_name, s_props),
                             (t("err.where_object"), o_name, o_props)):
        if not name:
            continue
        got, bad = _props_from_rows(raw, label)
        if bad:
            return [], bad
        if got:
            props.setdefault(name, {}).update(got)

    if at and o_name and o_name not in known_nodes:
        # Never rewrite the type of a node that already exists. Turning an
        # existing node into something else from a screen is a heavier act
        # than adding a fact.
        props.setdefault(o_name, {}).setdefault("type", "event")

    for name, got in props.items():
        ops.append(("set_node", {"name": name, "props": got}))

    if predicate:
        if not (s_name and o_name):
            return [], Problem("", t("err.rel_needs_both"))
        payload = {"s": s_name, "p": predicate, "o": o_name}
        if at:
            payload["at"] = at
        ops.append(("add_triple", payload))
    elif at:
        return [], Problem("event", t("err.date_alone"))

    if not ops:
        return [], Problem("", t("err.nothing_filled"))
    return ops, None


def _publish(session, target: str, author: str) -> None:
    """Build the PR right here, under the credential of whoever pressed.

    If this fails the proposals stay `pending`, so pressing again lands
    them. They cannot land twice: the starting point is that day's branch,
    and trikedb collapses the same triple added twice into one (measured).
    """
    with st.spinner(t("spinner.building")):
        try:
            result = wire.drain(session, target, author=author)
        except Exception as exc:  # noqa: BLE001 - show GitHub's reason as-is
            st.warning(t("warn.pr_failed", target=target, error=exc,
                         button=t("btn.propose")))
            return

    if result.get("created"):
        st.info(t("info.new_file", name=result["created"]))
    if result.get("pr_url"):
        st.success(t("ok.added_to_pr", target=target))
        st.markdown(t("link.open_pr", url=result["pr_url"]))
    else:
        st.info(t("info.accepted", target=target,
                  message=result.get("message") or ""))
    _deferred_note(result, author)


def _deferred_note(result: dict, author: str) -> None:
    """Report deferred proposals, **split by whose they are**.

    Deferred means "proposed by someone with no GitHub credential", and that
    someone is not necessarily another person -- queue proposals before
    registering, then press, and your own are deferred. This used to receive
    only a count and described all of them as "other people's proposals",
    which told the person whose own proposal was deferred nothing at all.
    """
    by_author = dict(result.get("deferred_by_author") or [])
    ours = by_author.pop(author, 0)
    theirs = sum(by_author.values())
    if ours:
        st.caption(t("defer.ours", count=ours))
    if theirs:
        st.caption(t("defer.theirs", count=theirs))


def _history(session, author: str) -> None:
    rows = mine(session, author)
    if not rows:
        return
    st.divider()
    st.subheader(t("hist.title"))
    st.caption(t("hist.legend"))
    for created, target, op, payload, status, pr_url, error in rows:
        when = _when(created)
        head = f"`{status}` {when} — {target} / {op}"
        with st.expander(head):
            st.code(payload, language="json")
            if pr_url:
                st.markdown(t("hist.see_pr", url=pr_url))
            if error:
                st.warning(error)
