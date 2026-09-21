# Contributing

Thanks for looking. trikedb is small on purpose, and the fastest way to get a
change merged is to keep it that way.

## Setting up

```bash
git clone https://github.com/RyutoYoda/trikedb
cd trikedb
pip install -e ".[dev]"      # or: uv sync --extra dev
python -m pytest tests/ -q
```

The suite is fast — a few seconds — and it runs offline. Nothing in `tests/`
needs a network, a warehouse, or a model download: the SQL storage layer is
driven through a fake DB-API connection, and the semantic-search tests skip
themselves when `model2vec` is not installed. If a test you add needs any of
those, it belongs in `benchmarks/`, not `tests/`.

CI runs the same command on Python 3.10 and 3.13 — the floor and the ceiling of
`requires-python`.

## What a good pull request looks like

**One change, with the reason in the diff.** The comments in this codebase say
*why*, not *what*; the code already says what. If you had to work something out
to make the change — a measurement, a spec paragraph, a failure you hit — write
that down next to the line it explains. That note is the part a future reader
cannot reconstruct.

**A test that fails before it.** Not a test that exercises the new code, a test
that would have caught the bug. The test names in `tests/test_trikedb.py` read
as sentences about behaviour (`test_the_decision_log_template_really_refuses_what_it_claims`)
because the name is the specification.

**No new required dependency.** Every optional capability is an extra, and the
core is PyYAML + rdflib + pyoxigraph. If your feature needs a library, add an
extra and import it inside the function that uses it, so someone who does not
want the feature never pays for it.

**The layer respected.** `tests/test_architecture.py` is the dependency diagram,
and it fails the build when the code stops matching it: a module may import only
from a layer strictly below its own, and a new module has to be given a layer on
purpose. An import inside a function is how an adapter stays optional — that is
the fix, not the violation.

## Things that will be turned down

Not because they are bad ideas, but because they are a different product:

- **A query language of its own.** Reads go to Oxigraph, updates and OWL/SHACL
  to rdflib. Cypher, SWRL, RIF and a hand-rolled SPARQL subset are all out.
- **A server, a daemon, or a schema registry.** The file is the database. If
  something only works when a process is running, it does not belong in the core.
- **Scale work for millions of triples.** Everything is in memory and scans are
  linear, deliberately. Hundreds to thousands is the range where a curated graph
  is possible at all; past that, the answer is an export to a real triple store.
- **A framework around the graph.** Orchestration, agent loops, prompt templates —
  those go in your code, not in this library.

If you are unsure whether an idea lands on the wrong side of that list, open an
issue before writing the code. It is a cheaper conversation than a closed PR.

## Docs

`README.md`, `README_jp.md` and `README_zh.md` are kept structurally identical —
the same sequence of heading levels and byte-identical code blocks, with only
prose and code comments translated. A test enforces it, so a section added to one
has to be added to all three. The same goes for `docs/REFERENCE*.md`.

The README is also the PyPI long description, and PyPI freezes it per released
version: **every link in it must be an absolute `https://github.com/...` URL**,
because a relative link resolves against the PyPI page and 404s forever.

## Reporting a vulnerability

Privately, please — see [SECURITY.md](SECURITY.md). Not in an issue.
