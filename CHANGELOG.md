# Changelog

Notable changes, newest first. Versions before 0.30.0 are in the
[commit history](https://github.com/RyutoYoda/trikedb/commits/main).

## 0.43.0

- **A Word file is a document trikedb can read.** `trikedb extract
  graph.yaml notice.docx` works, and so does
  `trikedb.importers.read_document(path)` — a `.docx` is a zip holding
  `word/document.xml`, so reading one costs `zipfile` and
  `xml.etree.ElementTree` and no dependency at all. Headings, list items
  and tables come out as Markdown rather than as one wall of text,
  because which section a fact came from and which rows are separate
  facts is most of what the extractor has to work with. Comments,
  footnotes and deleted text are left out: a remark in the margin, and a
  sentence the author already struck, should not become a fact without a
  person deciding that they should. Google Docs exports Markdown
  directly, which was always readable; the format that kept documents
  out of the graph was the one people receive, not the one they write.
  A `.doc` says to save it as `.docx` instead of failing as if it were
  broken text. PDF is deliberately not here — it needs a real dependency
  and loses the layout that carries the meaning.

- **A merged table cell keeps the columns it covers.** Word writes a cell
  merged across two columns as one `w:tc` with `w:gridSpan`, so the row holds
  fewer cells than the header has columns; padding the row at its end kept the
  column count right and slid every value after the merge one column to the
  left, under a heading belonging to something else. The table still looked
  square, so nothing downstream could see it. Found in a real Word file, where
  seven of sixty rows were affected.

- **A line break inside a paragraph is a line break.** `w:br` and `w:tab` hold
  no text and were skipped, welding the last word of one line to the first of
  the next — a sentence the document never contained. Found in the same file,
  nineteen times.

- **A text file that is not UTF-8 says which file and what to do.** A .txt
  saved on Windows is cp932, and the answer was `'utf-8' codec can't decode
  byte 0x93 in position 0` — which names neither the file nor anything to act
  on, and arrives only after the person has already pointed the command at the
  document they meant. It now names the file and the `iconv` line that
  converts it. A byte order mark is honoured, because a file carrying one has
  said what it is and Excel and Notepad both write one; nothing past that is
  detected, since a wrong guess turns a document into plausible nonsense
  rather than into an error.

- **A run of bullets in a .docx arrives as one list.** Word marks every item
  as its own paragraph, so each one was separated by a blank line: minutes and
  a weekly report are mostly list, and their line count nearly doubled for
  nothing the model could use.

- **`extract --relevant-to` offers both ends of a matching triple, once
  each.** Search ranks triples, and a triple is about the thing it points
  at as much as the thing it points from — but only the subject was
  taken. A notice about a new department matched
  `データ基盤部 BELONGS_TO アクメ` as its best hit and was then offered the
  department and never the company, so a model reading it had no listed
  spelling for アクメ and had to invent one: exactly the collision the
  entity list exists to prevent. Two triples sharing a subject also spent
  two slots on one name, and `--limit` is a promise about names. On a
  197-node graph with a real Word notice, the seven nodes the document is
  about now fill the first seven slots.

## 0.42.1

- **`extract --relevant-to` named the extra instead of dumping a
  traceback.** Without `trikedb[semantic]` it raised
  `ModuleNotFoundError: No module named 'numpy'` in full, and only on a
  graph holding more nodes than the prompt lists — so an install worked
  on the graph someone tried first and broke on the one they meant.
  `search` and `find` caught it and printed the module's name, which
  still does not say what to install. All three now say
  `pip install 'trikedb[semantic]'`.
- **An eval that scored nothing no longer passes.** `evals/score.py
  --answers DIR` skips a case whose answer file is absent; skipping every
  case printed an empty table and exited 0, which in CI reads as "nothing
  wrong" while having measured nothing.

## 0.42.0

A document is the third way to fill a graph, after typing the facts and
after letting an agent add them — and the one that was missing.

- **Extraction constrained by the graph it writes into.** `db.extract(text,
  llm=...)` and `trikedb extract` build the prompt from the target graph:
  the predicates the ontology declares are the only ones offered, the node
  names already in the file are the spellings to reuse, and each
  `domain`/`range` goes in as the shape of the row. An extractor corrected
  after the fact has already spent the facts it guessed wrong. `llm` is any
  callable from prompt to text with **no default** — a test reads
  `extract.py` with `ast` and fails if it ever imports a vendor SDK, so
  `pip install trikedb` does not grow by a byte. Five providers are written
  out in `examples/extract_providers.py` as documents, not dependencies.
- **`preview()` and `import --dry-run`, which help without a model at all.**
  Every incoming row is judged before anything is written — `conflict`,
  `rejected`, `update`, `new`, `same`, worst first — by the checks `add()`
  runs, in the order it runs them, so a preview cannot promise a write that
  then fails. A `conflict` is decidable rather than guessed: a predicate
  declared `functional` may hold one object per subject. Hand-typed adds,
  CSVs and agent writes all go through it.
- **`prov` is a verbatim quote, so hallucination is checked by substring.**
  No judge model, no threshold. `evals/` ships three adversarial cases with
  their graphs, documents and hand-written gold answers, plus the
  unconstrained baseline prompt in the repository where a diff can be read.
  No numbers are committed — a number is one model on one day — but a test
  guarantees the gold answers score a perfect 1.0, so the ceiling is known
  to exist.
- **Three MCP tools, taking it to sixteen.** `extraction_prompt`,
  `preview_triples` and `add_triples`, the last all-or-nothing.

The library was fine and the front door was not. A README of 876 lines
answered every question except the first one — *what do I write, and why
would I* — and the first thing anyone did after installing was open an
empty file and look at it.

- **`trikedb init --template`.** An empty file is a worse starting point
  than a wrong one: with nothing on the screen there is no shape to
  disagree with. Four templates — `agent-memory`, `service-map`,
  `decision-log`, `minimal` — each write a small graph that already has a
  vocabulary, node types and a few facts, so the first edit is a
  correction rather than an invention. `decision-log` ships the
  `requires`/`by` pair on a real action, which is the feature people ask
  for after they stop believing a checklist enforces anything. Without
  `--force`, `init` refuses to write over a file that exists — the file is
  the database, so an overwrite here is the whole database. All four load
  clean under `audit`.
- **The README is 233 lines and starts with no ontology at all.** The
  ontology is what makes trikedb worth using and it was also what made it
  look like a week of modelling before the first fact. It now arrives one
  section later, as *then lock it down*, after three facts that need
  nothing declared. Everything cut — the storage backends, serve and
  OAuth, hybrid retrieval, the triple-store comparison, the compatibility
  and safety contract — was already in `docs/REFERENCE.md`, said better
  and at length. The four calls a real graph is actually built from
  (`add`, `act`, `find`, `sparql`) are now a table instead of something you
  had to find by reading.
- **The things a stranger looks for before filing anything.**
  `CONTRIBUTING.md` (how to run the tests, what a good PR looks like, and
  what gets turned down and why), `SECURITY.md` (private reporting, and an
  explicit in-scope/out-of-scope split — the write guard is in scope, a
  slow SPARQL query is not), and issue templates that point security
  reports away from the public tracker.
- **`py.typed`.** The package has been annotated throughout and PEP 561
  says a type checker must ignore all of it without this marker file, so
  everyone importing trikedb saw `Any`. Also `Typing :: Typed`, the
  per-minor Python classifiers, and `Repository`/`Issues`/`Documentation`/
  `Changelog` URLs, which is what fills in the sidebar on PyPI.
- **Two tests instead of two more conventions.** One checks that every
  `https://github.com/RyutoYoda/trikedb/...` link in a README points at a
  file that exists — absolute is not the same as correct, and PyPI freezes
  the README per released version, so a link to a translation that was
  planned and never written is broken there forever. The other checks that
  every `trikedb …` line in the README parses as a real subcommand with
  real flags. Both were written because they caught something.
- **`docs/REFERENCE_zh.md`, and the reference is now the same in three
  languages.** The Chinese READMEs had been pointing readers at the
  English reference for every detail, which is not a translation so much
  as a redirect. The parity test that already held `README.md`,
  `benchmarks/README.md` and `docs/ARCHITECTURE.md` to the same headings
  and the same runnable code now covers `docs/REFERENCE.md` too, so the
  three cannot drift apart again quietly. Three Japanese rows in the
  Python API table were found by that pass describing an API two releases
  old — `history` without `incoming`, `declare_link` without `requires`
  and `by` — and the workbench section was missing the incoming-event
  marker and the timeline strip.
- **165 regenerable files left the repository.** `bench_out/` is scratch:
  `prompts_*.json` are outputs of the run scripts and `eval_set.json` is
  27 MB that `webqsp_bench.py prepare` downloads from the public WebQSP
  release. The benchmark's own docstring already promised no dataset
  content was committed here, and now that is true. What stays is
  `benchmarks/*_data.json` — the scored results the charts and the number
  in the README are read from.

## 0.41.0

The workbench panel could be opened but not left. Opening a detail view
from the action log replaced the log with the node, and the only control
left was a `×` that threw away the whole trail — the way back out of an
answer did not exist.

- **The panel remembers how you got here.** A node, the whole action log
  and a predicate's declaration still replace one another in one panel:
  each is the answer to a question the last view raised, so stacking
  windows would be wrong. What was missing is the step back, and the
  button names its destination — `← action log` reads differently from
  `← RESOLVED_BY`, and a bare arrow could say neither. Stepping back to
  a node puts the graph's selection and camera back with it. Closing
  clears the trail: reopening starts a new question, not an abandoned
  one. `Esc` closes, unless you are typing in a field.
- **The header no longer pushes its own buttons off the screen.** It was
  one row of fixed height with no overflow, so in a 900px window
  `predicates`, `Fit` and `light` sat past the right edge and `events`
  was cut in half; with `body { overflow: hidden }` nothing could scroll
  to them, so they were not awkward to reach, they were gone. The bar
  takes a second row instead, and everything fixed below it reads the
  height the bar actually took rather than a constant. Wide windows look
  exactly as they did.
- **The member-graph chips step aside for the panel.** The workspace bar
  ran the full width and the detail panel drew over its right end,
  hiding chips. It now stops at the panel, the way the SPARQL bar
  already did.

## 0.40.0

`by` said who did something, and over HTTP it was whatever the caller
typed. A declaration that only an approver may approve was a convention
an agent could step around by naming an approver.

- **An action written through an authenticated `/mcp` is signed by the
  token.** `act` stamps `by` with the caller's own identity, and a `by`
  naming somebody else is refused rather than recorded. `add_triple`
  stamps it too, but only on a predicate that declares `by` — a fact is
  not a deed, so a plain triple still grows no `by`. Nothing changes for
  a static `--token`, for stdio, or for library use: those transports
  name nobody, and `by` there behaves exactly as it always has.
- **`subject` is the node property that maps an identity onto an actor.**
  A token's `sub` is `auth0|ryuto`; a graph knows the same person as
  `Rune Halvorsen`, whose `type` is what a declared `by` is checked
  against. Curating `{type: approver, subject: "auth0|ryuto"}` connects
  the two, so a bot's token cannot write `APPROVED_BY` — not for naming
  the wrong actor, but for being one. An identity mapped nowhere is
  stamped verbatim, so a graph with no `subject` in it still gets signed
  events. Two nodes claiming one `subject` is an error, not a coin flip.
- **The identity map is not writable by an authenticated caller.**
  `set_node` with a `subject` property is refused whenever the request
  itself carries an identity, because an actor that could name itself is
  not an actor. The guard sits on the wrapper every MCP tool goes
  through, not on the four write tools, so a tool added later cannot
  quietly omit it.
- **`--actor-claim CLAIM` signs with a claim other than `sub`.**
  `--actor-claim email` writes `by: ryuto@example.com`. A token missing
  the configured claim is refused with a message naming the claim, rather
  than falling back to `sub` — a signature that is sometimes a different
  kind of name is worse than none.

## 0.39.6

- **The workbench now calls the inventory what it is.** The `ontology · N`
  button and panel were showing the number of predicate types, not the
  ontology as a whole. They now say `predicates · N` and `N predicate types`,
  with the separate enforced-rule count still visible. The distinction is
  important: triples are facts, predicates are the kinds of relationships,
  and ontology declarations are the rules that may constrain them.

## 0.39.5

The README told you to edit a file the sdist does not carry, and the test
that guards it shipped anyway.

- **`examples/generate_trike_demo.py` is in the sdist now.**
  `MANIFEST.in` listed `*.yaml *.csv *.md *.ipynb` under `examples`, and
  the generator is the one `.py` in there, so it was the single file in
  that directory that did not ship. All three READMEs point at it and say
  the demo grows by editing the generator rather than the data — advice
  that cannot be followed from a tarball. Worse, `tests/` ships whole:
  `test_the_demo_still_comes_out_of_its_own_generator` runs the generator
  by path with no skip guard, so `pytest` on an unpacked sdist failed on
  a missing file rather than on anything about the code. It passes now.

## 0.39.4

0.39.3 caught one spelling of an event written onto the node. There were
six, and which key a user happens to write is not theirs to get right.

- **`event-written-on-node` now fires on every shape of it.** 0.39.3
  asked for a time *and* a state on the node, so `{type: event, date:}`,
  `{type: event, state:}` and a bare `{type: event}` all still loaded,
  still returned an empty `history()`, and still said nothing. A node
  that declares `type: event` is a stronger signal than either key, and
  it went unused. Now an event record is recognised two ways — it says
  `type: event`, or it carries both an event's time and an event's state
  — and either key alone stays ordinary, so a release with a date and an
  `act()`-written state on a real entity are still not flagged.
- **The mirrored mistake is caught too.** The check only looked at
  triples pointing *at* the node, but the documented promoted form has
  the event as the **subject** (`PC-0007 CHANGED kettle at: ...`), so the
  same misplacement made the other way round — `PC-0007 {date, state}
  CHANGED kettle` with nothing on the triple — was invisible to it. Every
  triple touching the node is asked now, either side, and the finding
  names the triple to put `at:` on.
- **`history()` says where `at:` and `state:` go.** It is the method that
  advertises promotion, and it is what the user who lost 16 events read;
  0.39.3 put the rule and the README pointer on `state()` only, which is
  not the door they came through. Both carry it now, and a test holds
  them to it.

Verified against the graph that reported this: 437 triples, one finding —
an event node nothing dates, which 0.39.3 would have kept quiet about.
Zero findings on all 16 shipped examples.

## 0.39.3

An event written onto the node instead of onto the triple loaded fine and
then disappeared. Now `audit` says so.

- **New `audit` finding: `event-written-on-node`** (warning). Promotion
  gives an event an id so it can hold what made it worth promoting — a
  before, an after, a reason. It does not move `at:` and `state:`, which
  `when()` and `state()` read off the triple. Put those two on the node
  and nothing raises: the graph loads, `state()` returns `None`, and
  `history()` returns fewer rows than the file looks like it holds. A
  user lost 16 of 18 events to that silence and spent a day finding it.
  Both keys together are the signal — a date alone is an ordinary
  property (a release has one) and a state alone is what `act()` writes
  onto every node it touches — so the check fires only when a node
  carries a time *and* a state, and it names the triple to move `at:`
  onto. Zero findings on every shipped example.
- **`state()` says what it reads.** The docstring promised a hand-written
  graph the same answer as one built through `act()` without saying that
  it looks only at the triples the node is the *subject* of, and only at
  the triple's own attributes. Both are deliberate — an event pointing at
  a node did not leave the node in the event's state — and both are now
  written down, next to a pointer to the README section that shows the
  promoted form in YAML.

## 0.39.2

The Examples list advertised three demos at the bottom and told you which
file was behind only one of them.

- **Every example that powers a page now says which page.**
  `examples/acme_pipeline.yaml` is what `/pipeline.html` draws, and the
  bullet never said so, while `examples/freebase_sample.yaml` — which
  powers no page at all since 0.39.1 — still carried a sentence explaining
  its absence from one. A reader counting three demo links against the
  bullets came up one short and one unexplained. `generate_trike_demo.py`
  said it wrote "the six files above", a count left over from when the
  workspace and its five members were listed separately. Fixed in all
  three READMEs. A published PyPI description cannot be edited, so the
  correction needs a version to ride on.

## 0.39.1

Two demos of the same 614 facts, and only one of them showed anything the
other did not.

- **`/freebase.html` is gone; `/workspace.html` renders those facts.** The
  page was one release old — 0.39.0 moved the old front page there — and it
  drew exactly what `/workspace.html` draws, minus the six member-graph
  filter chips. Two URLs for one dataset is a choice the reader has to make
  before they know enough to make it. `examples/freebase_sample.yaml`
  stays: a flat file of undeclared, undated third-party data is worth
  keeping next to the declared graph, whether or not it is also a page.
  The READMEs, in all three languages, point their demo links and the
  screenshot at `/workspace.html` now, and `/freebase.html` itself keeps
  answering: it is a redirect to `/workspace.html`. The README shipped
  inside trikedb 0.39.0 links that URL four times and a released PyPI
  description cannot be edited, so deleting the page outright would have
  left four dead links on a page nobody can ever fix. A URL that has been
  published is a promise; the page behind it is not.
- **CI checks the pipeline demo now.** `docs-are-current` regenerated and
  compared three of the four pages. `docs/pipeline.html` — the one that
  shows the action layer — was not among them, so an edit to the renderer
  or to `examples/acme_pipeline.yaml` could leave it stale without failing
  anything. It takes the slot the Freebase check gave up.
- **The sdist no longer carries a graph nothing linked.**
  `examples/today_slides_graph.yaml` and its page were deleted after
  0.39.0 was published, and `examples/` ships whole — so the file sat in
  the 0.39.0 tarball with nothing pointing at it. Files on PyPI cannot be
  edited after the fact; this is the release that drops it.

## 0.39.0

An event can be an object, and an action can say when it may run.

- **`requires` and `by`: the other half of declaring an action.** A
  predicate could already declare what it connects (`domain`, `range`).
  It can now declare what must have happened first, and who is allowed to
  do it — the half a type check cannot reach. An order delivered before
  it ever shipped breaks no type. Neither does a price change approved by
  nobody. Both are refused now:

  ```yaml
  DELIVERED_TO:
    domain: order
    range: region
    requires: SHIPPED_FROM     # this has to have happened first
    by: courier                # and this is who may do it
  ```

  This is the line the comparison tables draw between a semantic layer and
  an ontology: one describes updates and leaves the rules to whatever code
  performs them, the other defines execution conditions, permissions,
  state change and history in the same place as the object. trikedb had
  the last two. It has all four now.
- **`requires` reads both ends, like `history()` reads a node.** A
  precondition asks what an action *touches*, not what it is the subject
  of, because promotion moves the thing an action is about across the
  edge — and in both directions. `RET-0007 RETIRED "Copper Kettle"`
  leaves the kettle with no `RETIRED` of its own; `MIT-0007 MITIGATED
  INC-2025-01` makes the mitigation its own subject, and a mitigation
  created this moment has no history to ask about at all. Matching
  subjects only would fail in exactly the case promotion exists for. An
  action with a precondition must carry a time, because "before" is
  otherwise a question nothing can answer. Preconditions cross member
  graphs: the demo requires `PLACED_BY` before `SHIPPED_FROM`, and the
  two live in different files.
- **A condition can span more than one step.** One predicate name is
  enough for "it had to have shipped first", and not enough for most
  real rules, because the thing they turn on is usually named by
  neither end of the action. "You may review what you bought" is the
  plain example: the review is customer → product, and the purchase is
  an *order* — a third node neither end mentions. `requires` now takes
  `(s p o)` patterns as well as predicate names, joined on shared
  variables, with `?s` and `?o` already bound to the action's own two
  ends:

  ```yaml
  REVIEWED:
    domain: customer
    range: product
    requires:
      - "?order PLACED_BY ?s"    # some order this customer placed
      - "?order CONTAINS ?o"     # and that same order held this product
  ```

  The demo declares exactly this, and a review planted by hand — real
  customer, real product, both types right, date plausible — is now
  refused with `nothing satisfies (?order CONTAINS ?o) at all`. Every
  type check in the file passes it. Fixed-length paths only: recursion
  and transitive closure stay with `infer()`, which already owns them.
- **Checked at write time, not downgraded to a report.** A multi-step
  condition asked mid-build can fail for two different reasons, and only
  one of them is a violation: the evidence may be wrong, or it may
  simply not be written yet. Adding triples can *satisfy* a condition
  and can never break one, so a failure while the graph is still being
  assembled is a question with no answer yet — not a no. Conditions that
  fail inside an open `batch()` are therefore **held and asked again at
  batch exit**, and again in `save()`, so the evidence may legitimately
  be written after the write that needs it. Nothing is skipped and
  nothing is checked more loosely; only the moment the exception arrives
  moves. Outside a batch, a single `act()` is refused where it is
  written, as before.
- **It costs the same at 200,000 triples as at 1,000.** Triples are
  indexed by predicate *and* by `(predicate, endpoint)` — either end,
  the same both-directions rule `history()` follows — and the index is
  extended on each append instead of dropped, which is the difference
  between a check that is indexed and a check that is indexed and still
  linear. A two-step condition costs 42µs at 1k and 41µs at 200k —
  `benchmarks/precondition_bench.py` measures it against a control
  predicate that declares nothing, so the number is the check and not the
  append it rides on.
- **An action no longer copies the graph it is not touching.** `act()`
  opens a `batch()` so that the event and the state it leaves on the node
  cannot come apart, and `batch()` guaranteed rollback by deep-copying the
  entire store on the way in. So every single action deep-copied every
  triple, every node and the whole ontology: 5.8ms on a 1,200-triple graph
  and **1.5 seconds** on a 200,000-triple one — the action layer got
  slower the more history a graph had, which is exactly backwards. The
  snapshot copies pointers now, which is the same guarantee as long as
  nothing edits an object the store already holds, so the two places that
  did — `add()`'s attribute merge and the state `act()` writes onto a node
  — record their pre-image or replace instead. One action costs 69µs at
  1.2k triples and 12ms at 200k: **84× and 123× faster**. Rollback is not
  taken on trust: `test_a_failed_batch_puts_everything_back` asserts the
  store is identical afterwards across nine different mutations, so a
  mutation added later that edits in place fails the build.
- **Typing a node no longer reads the whole graph.** `set_node(x,
  type=...)` has to check that the type does not contradict an edge
  already written, and it did that by walking every triple — which makes
  a bulk load quadratic, because a bulk load types every node it writes.
  It goes through the `(predicate, endpoint)` index now, bounded by how
  many predicates the ontology declares rather than by how much data is
  in it: loading 25,000 triples under a `domain`/`range` declaration was
  98 seconds and is 0.4, and 200,000 — which was over an hour — is 3.4.
- **A `requires` entry that is neither shape is refused at declaration.**
  It used to be kept as a predicate name nothing could ever match, which
  reads in audit as "this has never happened" — a rule that always fails
  and a rule that is misspelled have to be distinguishable, or the
  guarantee is worth nothing. One term or three, and anything else says
  so at `declare_link` time. (This one bit the demo generator first.)
- **Checked twice, the way shapes already are.** `add` and `act` refuse
  what they can see; `audit` reads the finished file for the rest, so
  the line a triple happens to sit on never decides whether the graph
  obeys itself — the clock does. Audit asks the *same call the write
  path makes* rather than re-deriving "had this happened yet": two
  implementations of that would eventually disagree, and the one a
  reader trusts is whichever they ran last. New findings:
  `precondition-unmet`, `action-has-no-actor`,
  `actor-contradicts-declaration` (errors) and `unchecked-actor`
  (warning). Whoever performed an action now counts as attached to the
  graph, so a courier named only in `by=` is no longer reported as an
  orphan node.

- **`history()` folds both directions.** An action that grows properties
  of its own stops fitting on a line: a price change with a before, an
  after and an approver is a *thing*, and the honest shape is
  `PC-0007 CHANGED "Copper Kettle 1.5L"` with `PC-0007 APPROVED_BY
  "Rune Halvorsen"` — the same move Palantir makes when an Action Type
  earns its own Object Type, and what PROV-O calls an `Activity`. That
  promotion used to orphan everything it touched, because `history()`
  matched subjects only and the kettle is now the *object* of `CHANGED`.
  It now reads incoming dated triples too, so the product still has its
  own record. `history(name, incoming=False)` is the old view.
- **`state()` deliberately did not follow.** Widening both at once is the
  bug this release exists to avoid: the change's `applied` would have
  landed on the product *and* on the person who signed it off. A node
  wears only the state of events it is the subject of — an event pointing
  at you says something happened to you, not that you took its state.
- **The detail panel shows both.** Events a node is the object of are
  listed with the rest of its history, marked `←` with the subject they
  came from.
- **The bottom strip is back.** 0.38.1 removed it on the argument that a
  ticker attached to nothing is the one thing an action layer must not
  look like. Both readings are real: the line says *where* something
  happened, the strip says *when* — and time order is the one thing the
  graph layout cannot show. Events are now drawn in both places, the
  `events` button folds the strip away and back, and the strip's own
  label opens the whole log in the panel.
- **The page shows the rules, not just the facts.** A declaration that
  only lives in the YAML is a declaration nobody reads. The header now
  carries an `ontology · N` button listing every predicate with what it
  declares — `domain`, `range`, `requires`, `by`, spelled out as
  sentences — and clicking a predicate chip beside any fact opens that
  one predicate's rule right where the question came up. Predicates with
  nothing declared are listed too, saying so: a page that quietly omitted
  them would look stricter than the graph is.
- **A node reads as what it is, and keeps its id.** The drawing still
  uses ids — short, stable, the thing you would paste into a query — but
  the detail panel, every link and the action log now show `label`,
  `name`, `title` or `summary` when the node has one, with the id kept
  underneath the heading and in each link's tooltip. An incident stops
  being `INC-2025-11` and becomes "inventory-service leaked connections
  under retry storms"; `PC-0007`, which has no other name, stays
  `PC-0007`. The property that supplied the heading is not then repeated
  in the property list.
- **`set_node("SVC-1", name="checkout-api")` works.** It used to raise
  `TypeError`, and so did `trikedb node SVC-1 -a name=...`: the parameter
  holding the node was itself called `name` and ate the property. The
  node is positional-only now, which is the fix for the key a caller most
  wants to set.
- **The demo is a company, not a sample.** `examples/trike_*.yaml` —
  trike goods, a fictional homeware retailer as five member graphs and a
  workspace: catalog, commerce, fulfilment, org, incidents. 567 triples,
  every predicate declared with an enforced `domain`/`range`, eleven of
  them with an enforced actor (`by:`) as well, and
  **not one dangling sentence**: the price changes, retirements and
  mitigations are all promoted objects, so every object of every dated
  triple is a node the graph knows something else about. The generator
  ships with it — `examples/generate_trike_demo.py`, stdlib only,
  deterministic — and a test diffs its output against the committed YAML
  byte for byte, because a demo that has drifted from its own generator
  is one nobody can safely change.
- **And it is the front page now.** The live demo used to open on
  `examples/freebase_sample.yaml`: 614 real facts, no `domain`, no
  `range`, no `requires`, no `by`, and not one dated triple. A fine
  picture of a graph, and a demonstration of nothing this project
  argues. The root URL now serves the trike goods workspace — 36
  predicates that all declare a domain and a range, nine that declare a
  precondition, eleven that declare an actor, and 240 dated actions that
  `state()` is assembled from. Freebase did not go away: it moved to
  `/freebase.html`, because third-party data nobody curated is worth
  showing next to data that was. `/workspace.html` keeps its URL
  unchanged — it has been linked from released PyPI pages, and those
  pages cannot be edited after the fact.
- **A filter re-frames what it left standing.** In the exported page,
  hiding a type or a member graph set `hidden` on the nodes and moved the
  camera not at all, so the sixth of a workspace you asked to see stayed
  a speck in whichever corner the layout had put it, at the zoom chosen
  for the whole graph — the answer was off screen until you found `Fit`.
  It re-frames now. Only when it must: a predicate toggle hides edges and
  moves no node, and re-framing for that is the jarring kind of help, so
  the visible node set is compared before the camera is touched. Both
  halves are asserted in `tests/browser_smoke.py`, in a real browser,
  because neither is visible to a test that only reads the HTML.
- **`db.py` stopped being the whole library.** The repo had already
  written its own rule down — a capability lives in its own module and
  reaches users as a thin delegating method on `TrikeDB` — and every
  module but the core one followed it. `db.py` is 1530 lines down to 877,
  lighter by four: `model.py` (what a triple *is*, importing nothing from
  trikedb), `rules.py` (`domain`/`range`/`requires`/`by`), `rdf.py` (the
  RDF projection and SPARQL) and `persistence.py` (load, save,
  workspaces). `semantic.py` and `semantics.py` — one letter apart and
  meaning unrelated things — became `embeddings.py` and `reasoning.py`.
  Behaviour is unchanged and every old import path still resolves, but
  the import cycles are gone for real rather than deferred into function
  bodies: `html` and `reasoning` needed one name and two names from the
  store, and both now take them from `model`. Two things moved for anyone
  reaching inside: `trikedb.db._read_text` / `_write_text` are
  monkeypatch points on `trikedb.persistence` now, and the `semantic` /
  `semantics` shims re-export values but cannot serve as `patch()`
  targets — patch `trikedb.embeddings` / `trikedb.reasoning` instead.
- **The core no longer depends on the page that draws it.** Splitting the
  files left one edge pointing backwards: `db.py` imported `html` at the
  top, so a graph could not be loaded without loading the workbench that
  renders it, and the same held for `importers` and `embeddings` — an
  adapter for a file format nobody is reading and a model that may not be
  installed. All three are imported inside the three methods that use
  them. `html`, `importers` and `embeddings` now sit *above* the core in
  the layering rather than inside it, and seven private methods that
  forwarded verbatim to a module function and were called by nothing at
  all are gone: a forward nobody follows is not an interface.
- **The layering is declared, and the build fails when code stops
  matching it.** `tests/test_architecture.py` states which layer every
  module belongs to and checks that imports only ever point strictly
  downward, that there are no cycles, and that a newly added module has
  been placed in a layer on purpose. A diagram in a document is a wish;
  this is the same argument the library makes about ontologies, applied
  to the repository. The layering is written up in
  [ARCHITECTURE.md](https://github.com/RyutoYoda/trikedb/blob/main/docs/ARCHITECTURE.md#modules-and-layering).

## 0.38.1

Events are drawn where they happened.

- **An action happens *between* two objects, so that is where the page
  draws it.** The event edge now reads as the action it is — its own
  colour on the line, labelled with when it happened and the state it
  left behind (`2025-04-01 ▸ applied`) instead of the predicate name.
  A predicate pinned with `--events` that carries neither still falls
  back to its name.
- **The bottom bar is gone.** Change events used to be chips in a 46px
  strip pinned across the bottom of the window, which made them look
  like a ticker attached to nothing — the one thing an action layer
  must not look like. The whole log still reads in time order, from an
  `events · N` button in the header; the count is also how you can tell
  at a glance whether a graph has an action layer at all. The canvas
  and the detail panel get those 46px back.
- **Clicking a line opens the node it hangs off.** Edge clicks did
  nothing before, which on a page where every line is a fact is a dead
  end. For an event that means the panel that opens already has the
  rest of that node's history in it.
- **Edge labels are legible on a hub.** A label is drawn at the middle
  of its line, so a hub's fan wrote a dozen predicates in the same spot
  and the demo page read `lotiationlolationtivets`. Labels now sit on an
  opaque plate, and above 150 triples each edge of a hub gets its own
  vertical lane. Small graphs are left alone — a label nudged off its
  own line for no reason is worse than none.
- `examples/acme_pipeline.yaml` is a real action log now: eight dated
  events across five nodes, each with who did it and the state it left,
  two nodes carrying more than one so `history()` reads as a history,
  and a dated `MIGRATED_TO` so the demo contains the plain shape —
  object, action, object. It ships as a third demo page,
  [pipeline.html](https://ryutoyoda.github.io/trikedb/pipeline.html).

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
