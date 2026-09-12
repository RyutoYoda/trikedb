# Changelog

Notable changes, newest first. Versions before 0.30.0 are in the
[commit history](https://github.com/RyutoYoda/trikedb/commits/main).

## 0.38.0

An action layer you can run, and a declaration that is actually enforced.
0.37.0 could *describe* both; this release makes the machine do them.

- **Running the same action twice destroyed the first record.** A triple's
  identity was `(s, p, o)`, so "restarted after failure" in April and the
  identical line in September were one triple, and `add()` — an upsert —
  overwrote April's record with September's. A log you can delete from by
  appending to it is not a log. The time an event carries is now part of
  what that event *is*: two runs of the same action are two rows. Plain
  relations, which carry no time, still upsert exactly as before.
- **`act()` — the one door for "I did something."** It stamps the time
  (`at=` to override, otherwise now, with the local offset), appends the
  event, and moves the node to the state the action left it in — one write,
  all of it or none of it. The stamp is to the microsecond, because an
  agent acts faster than a second: five actions in a loop, timed to the
  second, claimed one instant between them. An event whose state never reached the node would
  be a log of something that did not happen. `history(name)` reads a node's
  events back newest-first; `state(name)` says where it stands now.
  Available as `db.act(...)`, the MCP tool `act`, and `trike act`.
- **A declared link is enforced, not just documented.** `INGESTS_TO:
  {description: ..., domain: job, range: table}` now refuses the backwards
  edge at write time — on `add`, on `act`, through SPARQL `INSERT`, through
  the MCP tools and the CLI — and says which way round does fit. The plain
  string form (`PROVIDES: "vendor -> job"`) is unchanged and still just a
  comment. Declare one at runtime with `declare_link()`, `trikedb ontology
  --link P=domain>range`, and it first measures the graph it is being added
  to: an existing link that already contradicts it is an error, not a
  silent pass.
- **Checked where checking is possible, reported where it is not.** Types
  get written after the edges that use them as often as before, so a link is
  refused only when the endpoint's type is actually known; `set_node()`
  applies the same rule from the node's side, so the order you wrote things
  in never decides whether the graph obeys its ontology. What no write path
  could check, `audit` reports as `unchecked-link`, and anything that got in
  another way (a hand edit, a declaration added later) as an error finding.
- **`audit` no longer calls two events a duplicate.** Its near-duplicate
  heuristic compared text alone, so two real events with the same wording on
  different days were reported as something to clean up — advice to delete
  history. And its `duplicate-triple` check compared only `(s, p, o)`, so
  two actions an agent ran in the same instant, doing different things,
  failed the audit with an error. An event is compared whole now: two are
  duplicates only when every attribute matches, which is a genuine
  double-write. A plain fact, carrying no time, is still just its
  `(s, p, o)`, and the same event in two workspace members is still caught.
- **"The latest event" was decided by the wrong thing when two events shared
  a day.** The sort is stable, so a tie on the date left the *first* line
  standing as the most recent — the opposite of true for a log you append
  to. Ties now break on file order: written later, happened later.
- **Unpadded dates sorted as text, not as dates.** `2025-4-1` compared
  greater than `2025-12-1` (and than `2025-04-02`), so a node could wear the
  state of an event that was months old. Event ordering now pads each number
  before comparing, and ignores whether the day was written with `-` or `/`.
  What is displayed is unchanged — only the sort key is normalized.
- **The HTML view shows the state the action wrote.** A node's badge and
  detail panel prefer the `state` property `act()` set, falling back to the
  state its newest event left it in — the same rule as `state()` in Python,
  so the page and the library never disagree.
- The SQL views (`KG_PREDICATE`, Snowflake and BigQuery alike) understand
  the declared form and expose it in a new `SHAPE` column; `DESCRIPTION`
  keeps working for both spellings, and a predicate that declares a shape
  and no prose reads as an empty description there just as it does in
  Python. Verified against a real Snowflake: every value that is not an
  object — string, empty string, number, array, null — comes back byte
  identical to what the previous view returned.
- The GitHub Pages demos are regenerated.

**Compatibility:** every graph written before this release loads and behaves
as it did, and its `content_hash` is unchanged — the declarations are added
to the fingerprint only when a graph actually has one, so HTML exported
earlier still passes `trikedb check`. `self.ontology` values stay plain
strings for everything that reads a description. The one behaviour that
changes on old data is the fix itself: two same-`(s, p, o)` events at
different times, which previously collapsed into one row, now both survive
a rewrite.

**Verification:** 267 tests passed, including end-to-end passes through the
MCP tools and the CLI on a wheel installed into a clean virtualenv —
shape enforcement holds on `add_triple`, on `act`, and on SPARQL `INSERT`
alike. The Chromium smoke test adds a section for `act()`
(two runs of one action kept as two events, the node wearing the state the
second wrote, both actors listed newest-first), the README quickstart was
run verbatim in a clean directory against that install, and the two
same-instant bugs above were both found by running the release the way a
user would and are pinned by tests.

## 0.37.0

- **Events are an action layer now: every event belongs to the node it
  happened to.** A triple that carries a time attribute (`at:`, `when:`,
  `date:`, `time:`, `timestamp:`, `occurred:`, `recorded:`) — or whose
  object opens with a date — is a change event on its *subject*. The HTML
  view reads the node's current state off its newest event and writes it on
  the node's label (`RAW_AD_SPEND_MANUAL ▸ pending-review`), and the detail
  panel lists that node's history newest first with when / state / who.
  Nothing new is stored: `state:`, `at:` and `by:` are ordinary edge
  attributes, and the reading is a projection.
- **The HTML view demoted real entities to floating event diamonds.** An
  event was detected by "the object contains whitespace", which in the
  shipped Freebase demo called 69 of 127 predicates change events — among
  them `people.person.parents` and `book.author.works_written` — and redrew
  341 of 547 nodes (62%) as red diamonds, 32 of them entities the graph says
  plenty else about. A relation is not an event just because it is spelled
  out. Objects are now only drawn as event payloads when the graph says
  nothing else about them; an object with node properties or outgoing edges
  stays the node it is.
- **The published demos were regenerated without `--events` at 0.36.0**, so
  they shipped that heuristic's full damage. `docs/index.html` and
  `docs/workspace.html` are rebuilt with curated event predicates: 2 event
  predicates instead of 69, and zero demoted entities.
- **An unquoted date attribute crashed every JSON surface.** PyYAML reads
  `at: 2025-04-01` as a `datetime.date`, which `json.dumps` refuses — so
  `to_html()` and `content_hash()` raised `TypeError` on a perfectly
  ordinary file. Dates, times and datetimes are normalized to ISO strings at
  load time, in edge attributes and node properties alike.
- `examples/acme_pipeline.yaml` shows the action-layer form, including one
  event still in flight.

**Verification:** 252 tests passed; the Chromium smoke test now also asserts
the action layer (state read off the node, newest-first history, no demoted
entities) on both a normal and an adversarial page, and a regression test
pins the state to the agent-facing surfaces — `match`/`get_node` return
`at`/`by`/`state`, and SPARQL reads them through the reification, so "what
state is this in, and what is not settled yet" is a query, not a rendering.

**Compatibility:** which predicates count as change events changes with this
release — a wordy object alone no longer qualifies. Pages generated by 0.36.x
should be regenerated; if a graph relied on the old behaviour, pin the
predicates explicitly with `--events`. YAML, the Python API and the SPARQL
projection are unchanged.

## 0.36.1

- Audit benchmark methodology, saved numeric summaries and all six chart families; document selection bias, local scoring, cache uncertainty and incomplete historical provenance.
- Replace the invalid 3% latency decomposition with independent measurements. Report the 86% versus 82% memory comparison as nonsignificant (paired p=0.454), alongside the verified 88.4% median input-token reduction.
- Validate log IDs/configurations, fingerprint resumable runs, honor retrieval selection, reject incomplete corpus tiers/paths and surface retrieval failures.
- Fix agent JSON parsing/accounting and continuation guards; use unique temporary workspaces. Scope backend cleanup to exact owned rows and add a distinct fact on each write repetition.
- Regenerate three-language charts with clearer scales, labels and legends. Deployment remains pinned to the independently tested 0.36.0 runtime; no deployment or CI changes.

## 0.36.0

- Share and serialize REST/MCP graph state; keep the committed S3/SQL version token to prevent lost updates. Use atomic local replacement and roll back failed batches/imports.
- Escape every generated HTML boundary, preserve special node names, and test normal and adversarial pages in Chromium.
- Persist explicit RDF term types, languages and blank nodes through SPARQL updates and inference. Export equivalent RDF/JSON-LD, avoid statement-name collisions, expose metadata to UPDATE WHERE and reject unsupported dataset updates.
- Return detached mutation snapshots, reload stored ontology, accept NetworkX label/key attributes, include implicit SQL nodes, and parse CLI booleans consistently.
- Add optional GitHub-only ECS Docker/Terraform deployment with private S3 YAML and bearer/OAuth configuration.
- Raise MCP/S3 dependency floors to verified APIs; include source-distribution fixtures and verify built packages locally.
- Bound benchmark F1, rescore saved answers, record new run prompts and correct denominators, reach arithmetic and causal claims in three languages.

**Verification:** 240 tests passed, with real ECS/S3 persistence and external HTTPS MCP checks. A disposable Keycloak authorization-code/PKCE login and authenticated MCP SDK call passed. ChatGPT/Claude UI connector registration remains unverified due to client-side registration/access limitations. No new CI workflow is included.

**Compatibility:** rdf_terms is now reserved. Legacy whitespace objects remain literals. Metadata deletion through SPARQL is rejected; use property APIs. Public return values are snapshots. Local multi-process writes still require external coordination. Existing generated HTML should be regenerated with this release.

## 0.35.1

- Packaging follow-up to 0.35.0; the September audit verified that its PyPI runtime modules matched repository commit 77bb2dc. That audit's findings are addressed in the entry above.

## 0.35.0

- **`ASK` was not answered by the engine it reported.** pyoxigraph returns
  `QueryBoolean`, not `bool`, so the `isinstance` check missed every `ASK`
  and fell through to rdflib — which also evicted the oxigraph store from
  the one-entry graph cache, so the next read rebuilt it. One `ASK` cost
  ~100 ms instead of ~0.1 ms. The answers were always right, which is why
  it went unnoticed.
- **`CONSTRUCT` and `DESCRIBE` raised `TypeError`.** They answer with a
  graph, so rdflib's `result.vars` is `None` and the binding loop failed on
  it — on both engines. They now return `{s, p, o}` rows, the shape a triple
  has everywhere else.
- **Added `trike find`.** `find` existed in the Python API and in MCP but
  had no CLI subcommand, so the project's own parity rule was documented
  and broken at the same time.
- Docs: the layer diagram paired each projection with one interface, which
  read as "oxigraph is only for MCP". Oxigraph normally answers SELECT/ASK across interfaces; other read forms and fallback use rdflib.
- Docs: the `6–40x` speed claim had no source. Replaced with a measurement
  (7–47x on 8,000 triples, by query shape).

## 0.34.0 — input validation

Malformed input used to become an empty graph without a word. Now refused,
with a message that names the file and the key:

- a workspace member that does not exist (a typo dropped a whole graph out
  of the union and every query just returned less)
- `graphs:` with no members
- a URL whose scheme no backend handles (`s2://…` became a local file by
  that name)
- `triples:` / `nodes:` / `graphs:` / `ontology:` of the wrong type
- YAML syntax errors now name the file — PyYAML only says
  `<unicode string>`, which is no help in a workspace of five members
- a triple term that is `None` or empty. `str(None)` is `"None"`, so a graph
  grew a node by that name and every missing value joined through it
- `query([])` — a join over nothing returns one empty row, a true answer to
  a question nobody meant to ask
- an unknown `sparql_engine` name
- `get_node` / `trike node` now report `exists`, so "no such node" and "a
  node with nothing on it" stop looking identical

The CLI turns `SyntaxError` and `OSError` into `error: …` instead of a
traceback.

## 0.33.2, 0.33.3 — the workbench page

- **Every node label was invisible.** vis rewrites any `scaling` object
  passed to it and leaves the label with a NaN font size, so every box drew
  with 0 px of text at every zoom. Shipped that way from 0.31.2; the
  published demo pages were blank boxes too.
- Labels now keep drawing when you zoom out far enough to see the whole
  graph, and appear without needing a click first.

## 0.33.0, 0.33.1

- `trike ui generate` writes the page; `trike ui` opens it. `trikedb html`
  still works for pipelines that spell it out.
- Removed the setuptools license warning at build time.

## 0.32.0, 0.32.1

- `trike ui` opens the graph in a browser, and picks up the graph in the
  current directory without being told.
- Fixed `trike ui` stopping in a directory that contains a workspace.

## 0.31.0 – 0.31.2

- Japanese node names work in SPARQL: names are percent-escaped into IRIs,
  so `SELECT ?s WHERE { ?s t:担当 t:担当A }` runs.
- Force-directed layout no longer settles nodes on top of each other.

## 0.30.0 – 0.30.2

Fixes from running a real 28,000-triple graph:

- `search()` re-embedded the whole graph on every call — vectors are now
  cached per sentence, in a cache directory rather than beside the graph.
- `add()` with autosave rewrote the file per triple, making bulk import
  quadratic. `with db.batch():` writes once.
- `set_node` silently overwrote a node's `type`; it now refuses unless
  `replace=True`.
- Long node properties came back whole through `search`/`find`/MCP (one hit
  returned 540,557 characters). They are previewed; `get_node` still returns
  the full value.
- Flow layout no longer stretches to 13,920 px on a graph with rework loops.
