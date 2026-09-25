# Curating a graph from Streamlit in Snowflake

A curation screen that runs **inside Snowflake**, writes nothing to the
graph directly, and turns what people type into **one pull request a day**
— each commit signed by the person who proposed it.

`examples/streamlit_app.py` in this repo is the one-file version of the
same idea: a form, the ontology guard, and a diff you commit yourself. It
ends by saying that when the graph lives in a warehouse, review has to move
out of the screen. This directory is what that looks like once several
people use it and nobody wants to hand out a shared token.

trikedb ships no write UI on purpose. **This is a recipe, not a product.**
Everything here has been run in production for one team; the interesting
part is the reasoning in the comments, not the code.

## What happens when somebody presses the button

```
  screen  ──►  KG_OUTBOX              a row: op, payload, note, prov
  (SiS)        (status = 'pending')
                     │
                     │  "open a PR"   pressed by a person, in their session
                     ▼
               outbox/service.drain()
                     │
                     ├─ guard        the proposal is applied to a real
                     │               TrikeDB and refused if it doesn't fit
                     ├─ group        one commit per author
                     └─ GitHub       api.github.com, with **that person's**
                                     personal access token
                     ▼
               one branch  kg/<graph>-<date>
               one PR, N commits, N authors
```

Nothing is a fact until the PR is merged. The screen never writes YAML, and
the table is not the source of truth — git is.

## Why a queue, and why it drains into git

A warehouse table has no working tree, so a screen that writes to it makes
facts true the instant somebody types them. For an operational dataset that
is fine. For a knowledge graph it is not: a graph is mostly *claims about
other teams' systems*, and a claim nobody reviewed is worse than a missing
one, because it answers queries confidently.

So the screen collects **proposals**, and the proposals leave as a pull
request. The people curating never open git; the people reviewing never
open the screen.

## Why one PR, with a commit per person

Because this path rewrites the whole YAML file. Two PRs branched from the
same base would each contain a complete copy of the file, and whichever
merged second would erase the one that merged first — silently, since
neither diff conflicts. Stacked onto a single branch in order, GitHub works
out the diffs and the problem does not arise.

The commits stay separate so authorship survives. A proposal from somebody
who has not linked a GitHub account is **not** folded into another person's
commit: it stays `pending`, the PR body says whose it is and why, and the
next run picks it up.

## Why every person registers their own token

There is no shared bot account. Each person registers a GitHub personal
access token from the screen, it lands in one row of `KG_OUTBOX_TOKEN`, and
the PR is opened as them.

Two layers protect it, and they have different jobs:

| layer | what it is | what it guarantees |
|---|---|---|
| outer | a row access policy + a masking policy, both `CURRENT_USER() = SF_USER` | whoever queries, from anywhere in Snowflake, only ever sees their own row |
| inner | `outbox/adapters/tokens.py` | inside the app, no name but the viewer's is ever looked up — **no query is issued at all** for anyone else |

The overlap is deliberate, and `tests/test_outbox.py::TestTokensOnlyServeTheViewer`
pins it: an invariant that only SQL enforces is exactly the kind that
breaks without anyone noticing.

### The `CURRENT_USER()` trap

This one cost a day, so it is written down in three places (here,
`setup.sql`, and `outbox/adapters/tokens.py`).

`SELECT CURRENT_USER()` **issued by** a Streamlit in Snowflake app returns
NULL. `CURRENT_USER()` **inside a policy expression** is the real user name,
even when the query came from the app — and QUERY_HISTORY records that same
real name. So `CURRENT_USER()` cannot distinguish "inside the app" from "in
a worksheet", and rewriting the policies to `CURRENT_USER() IS NULL` breaks
them.

The bug was never the policy. It was the **name**: the app stored rows under
`str(CURRENT_USER())`, i.e. the string `"None"`, and `CURRENT_USER() = 'None'`
is never true. A row access policy does not restrict `INSERT`, so
registering a token kept succeeding and kept producing a row that nobody —
including its owner — could read. The fix is `curation.current_user()`,
which takes the name from `st.user`.

### Why not a Snowflake SECRET object

* `CREATE SECRET ... SECRET_STRING='...'` **leaves the value unmasked in
  QUERY_HISTORY** (verified with a canary string). The screen is what
  creates it, so that rules it out.
* A SECRET's value cannot be read back from SQL, which is what the code
  needs to do.

Secrets reach SQL only through `execute_bound` (see `outbox/adapters/sql.py`):
Snowpark's `session.sql(sql, params=[...])` binds **server-side**, so
QUERY_HISTORY keeps the `?`. The DB-API default (pyformat) interpolates
client-side and would put the token in the history text.

## Layout

```
streamlit_app.py     the shell: open the graph, show counts, hand off
curation.py          the screens — propose, register a token, history
graph_store.py       open the graph (Snowflake table, or a YAML checkout)
i18n.py              every word on screen, in English and Japanese
outbox/
  domain.py          the rules. Knows trikedb and nothing else.
  ports.py           Protocols: Queue, Source, Clock
  service.py         the procedure: drain proposals into one PR
  wire.py            composition root. **Every proper noun is in here.**
  adapters/          snowflake, github, yaml, clock, tokens
tests/               153 tests, no Snowflake and no network
setup.sql            tables, policies, network rule, grants
snowflake.yml        deployment
environment.yml      pinned Streamlit version, and why
```

`domain`, `service` and `ports` import nothing from the outside world —
`tests/test_outbox.py::TestLayering` checks that as plain text, because
breaking it takes exactly one import line and that line should show up in a
review.

The practical payoff is `wire.py`: pointing this at a different repo, table
or branch is a one-file edit.

## The language switch

The screen is in English and Japanese, chosen from a radio at the top of
the sidebar. `i18n.py` is a dict and a lookup — no gettext, no `.po` files,
no build step — because a screen of this size does not earn any more than
that, and the people editing the words are the people editing the screen.

Three things in there are worth keeping if you copy it:

**Keys are slugs, not English sentences.** Keying the dict on the English
text is the obvious shortcut, and it breaks the day somebody improves an
English sentence: the Japanese silently vanishes and Japanese readers get
English, which looks like a translation nobody got to rather than a bug.

**The choice lives in `st.session_state`.** A Streamlit server runs every
session in one process, so a module-level "current language" is shared by
everyone: one person switching switches it for all of them.

**Widget `key=` values are never translated.** Streamlit identifies a
widget by its key, so translating keys makes every field a *different*
field the moment the language changes — throwing away everything typed, at
exactly the moment somebody is most likely to switch, which is partway
through a form they cannot read. `tests/test_i18n.py` pins that, along with
"every key has both languages" and "both languages take the same
`{placeholders}`".

One deliberate exception: **refusals from `outbox/domain.py` stay English.**
They are also written into PR bodies and into the `ERROR` column, read by
people who did not press the button and whose language is unknowable from
there. That is also why `domain` never learns the screen exists.

That exception cost one refactor. `_show_problem()` prints a refusal under
the field that caused it, and it used to work out which field by looking
for the word `predicate` or `yaml` *inside the message*. Translate the
message and every refusal falls through to the bottom of the page — the
exact failure the function was written to stop. So the screen's own
refusals are now a `Problem(field, text)`, where `field` is a
language-independent tag; `domain`'s plain strings keep the old substring
routing.

## Running the tests

They touch no Snowflake, no GitHub and not even Streamlit. Being able to
write them at all is the proof of the layering claim.

```bash
cd examples/streamlit-in-snowflake
uv run --with trikedb --with streamlit python -m unittest discover -s tests -q
```

## Deploying

1. **Run `setup.sql`.** Tables, the two policies, the network rule and the
   external access integration. Change the names in the first block.

2. **Stage trikedb.** It is not in Snowflake's Anaconda channel (pyyaml and
   rdflib, the only things it needs, are). Copy the package next to the app
   so `graph_store._VENDOR` can put it on `sys.path`:

   ```bash
   mkdir -p vendor
   pip install --target vendor --no-deps trikedb
   ```

3. **Point the code at your objects.** Three places, all at the top of their
   file: `curation.py` (`TABLE`, `TOKEN_TABLE`, `REPO`, `DISPLAY_TIMEZONE`),
   `graph_store.py` (`SNOWFLAKE_TABLE`, `GRAPH_PREFIX`) and `snowflake.yml`.

   If you want only one language, cut `LANGUAGES` in `i18n.py` down to it
   and the picker disappears on its own.

4. **Deploy**, then attach the integration — `snowflake.yml` cannot carry
   it, and the app object has to exist first:

   ```bash
   snow streamlit deploy --replace
   snow sql -q "ALTER STREAMLIT DEMO_DB.KG.GRAPH_CURATION
                SET EXTERNAL_ACCESS_INTEGRATIONS = (GITHUB_ACCESS_INTEGRATION);"
   ```

5. **Fill `TRIKE_GRAPHS`** from the YAML in your repo, however you already
   run things after a merge. The app only reads it; if the table is empty or
   missing, it falls back to a staged YAML checkout and says so on screen.

## Things that will bite you

* **`additional_source_files` must use wildcards.** A list of filenames
  deploys *successfully* with a file missing — the app then raises
  ImportError partway through a write, or quietly serves one graph fewer.
* **Timestamps render in the session timezone**, which is the account
  default, not yours. `TIMESTAMP_LTZ` columns are converted per-SELECT with
  `CONVERT_TIMEZONE` rather than by `ALTER SESSION SET TIMEZONE`, because
  that would also change what `CURRENT_TIMESTAMP()` means on writes.
* **Only `api.github.com:443` is reachable.** Skip the network rule and
  everything looks healthy right up until the PR is opened.
* **Regenerating any HTML artifact is not a `git diff` test.** `trikedb html`
  emits its N-Triples block in a nondeterministic order, so the file differs
  on every run even when the graph has not changed. Use
  `trikedb check --html` to decide whether it is stale.

## What is not here

The chat/answering half of the original app. Reading a graph with an LLM is
a different concern from curating one, and mixing them made both harder to
explain. This directory is the write path only.
