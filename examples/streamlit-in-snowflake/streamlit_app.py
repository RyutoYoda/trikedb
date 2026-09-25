"""A curation screen for a trikedb knowledge graph, running as a Streamlit
in Snowflake app.

trikedb ships no write UI on purpose: what a curation screen should look
like depends on who is curating. This is a recipe, not a product -- copy it,
change the names at the top of `curation.py`, `graph_store.py` and
`outbox/wire.py`, and change the wording to match your graph and your
colleagues.

What it does:

    someone types a fact  ->  a row in KG_OUTBOX  ->  a pull request
                                                      against the YAML in git

The graph itself is never written from the screen. The source of truth stays
in git, where facts get reviewed before they are believed, and Snowflake
holds a derived read-only copy that the screen queries.

Three things make this worth copying rather than inventing:

  * The person who presses the button is the person who opens the PR, using
    their own credential. No shared bot, no shared role, and the history
    says who proposed what.
  * The guard that decides whether a proposal is admissible runs twice --
    once on the screen to tell people early, once just before the PR is
    built, because the table can be written to from elsewhere.
  * Exactly one hole out of Snowflake: `api.github.com:443`.

Run it locally with `streamlit run streamlit_app.py` against a YAML
checkout, or deploy it with `snow streamlit deploy` (see README.md).
"""
from __future__ import annotations

import os

import streamlit as st

import curation
import graph_store
import i18n
from i18n import t

# `page_title` is fixed the first time the script runs, before the language
# picker below has been drawn, so on a very first load it is whatever the
# default language is. Every later rerun -- including the one the picker
# itself causes -- sets it to the chosen language.
st.set_page_config(page_title=t("app.title"), layout="wide")

# Drawn first so that everything below it is rendered in the language that
# is already selected. Streamlit reruns the whole script when the radio
# changes, and `st.session_state` carries the new value into that rerun, so
# nothing else has to be done to switch the page over.
i18n.picker(st.sidebar)

try:
    from snowflake.snowpark.context import get_active_session
    session = get_active_session()
except Exception:  # noqa: BLE001 - running outside Snowflake
    session = None


@st.cache_resource(show_spinner=False)
def open_graph():
    """Open the graph, preferring the Snowflake table over the staged YAML.

    The staged YAML stays as a fallback for when the table cannot be read,
    but a fallback that happens **silently** is the dangerous kind: people
    conclude they are looking at the current graph when they are looking at
    a snapshot. So the fallback always says so on screen.

    The staged copy is from the moment this container started; the table is
    read every time. Right after a deploy the staged copy can be older than
    the table, and after a failed push the table can be older than the
    staged copy. Both directions happen, so the mismatch message does not
    name one cause.

    Returns `(db, schema, content hash, source, notice)`, where `notice`
    is `(key, params)` rather than a finished sentence. That is not
    fussiness: this function is `@st.cache_resource`, so it runs once and
    its return value is reused for every rerun and every viewer. A sentence
    built in here would be frozen in whichever language happened to be
    selected the first time somebody opened the app -- and shown to
    everyone after that.
    """
    bases = [b for b in ("kg", os.path.join("..", "..", "ontology"))
             if os.path.exists(os.path.join(b, "workspace.yaml"))]

    staged_hash = ""
    if bases:
        try:
            staged_hash = graph_store.open_local(bases[0]).content_hash()[:12]
        except Exception:  # noqa: BLE001, S110 - only used for the warning
            pass

    if session is not None:
        try:
            ws = (os.path.join(bases[0], "workspace.yaml") if bases
                  else "kg/workspace.yaml")
            db = graph_store.open_snowflake(session, workspace=ws)
            live_hash = db.content_hash()[:12]
            stale = (None if not staged_hash or staged_hash == live_hash
                     else ("warn.stale",
                           {"live": live_hash, "staged": staged_hash}))
            return db, graph_store.schema(db), live_hash, "table", stale
        except Exception as e:  # noqa: BLE001
            notice = ("warn.table_unreadable",
                      {"table": graph_store.SNOWFLAKE_TABLE,
                       "error": f"{type(e).__name__}: {e}"})
    else:
        notice = None

    for base in bases:
        db = graph_store.open_local(base)
        return (db, graph_store.schema(db, base), db.content_hash()[:12],
                "local", notice)
    return None, {"predicate_defs": {}, "nodes": []}, "", "none", notice


db, schema, graph_hash, source, notice = open_graph()
if notice:
    st.warning(t(notice[0], **notice[1]))

with st.sidebar:
    st.subheader(t("side.graph"))
    if db:
        st.metric(t("side.triples"), len(list(db.triples())))
        st.metric(t("side.nodes"), len(schema["nodes"]))
        st.caption(t("side.predicates",
                     names=", ".join(list(schema["predicate_defs"])[:8])))
        # The content hash identifies exactly which version of the graph an
        # answer came from. Without it, "the graph says X" is unfalsifiable
        # a week later.
        st.caption(t("side.content_hash", value=graph_hash))
    st.caption(t("side.engine"))
    st.caption(t("side.reading_table", table=graph_store.SNOWFLAKE_TABLE)
               if source == "table" else t("side.reading_staged"))
    st.caption(t("side.source_of_truth", repo=curation.REPO))

st.title(t("app.title"))

if not db:
    st.error(t("err.no_graph"))
    st.stop()

curation.render(session, db, schema)
