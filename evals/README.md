# Extraction evals

Three small documents, the graph each one is extracted into, and the
answer a careful person would write. Run a model against them and see
what it does.

```bash
python evals/score.py --llm examples.extract_providers:anthropic
python evals/score.py --llm examples.extract_providers:anthropic --baseline
```

The first uses the prompt trikedb builds from the graph — its declared
predicates, its existing node names. The second uses `triples-naive`,
which asks for the same table and supplies no vocabulary at all. Running
both is the only comparison worth making: every difference between the
two rows is what the graph contributed, measured on the same document by
the same model on the same afternoon.

No model at hand, or a model with no API? Answer the prompts yourself:

```bash
python evals/score.py --record out/     # writes out/<case>.prompt.txt
                                        # paste each answer into out/<case>.md
python evals/score.py --answers out/
```

## No numbers are committed here

Not modesty — a committed score is a score for one model on one day, and
whoever reads it cannot tell which. The cases, the answer sheets and the
scorer are here so that anyone can produce the figure for the model they
actually use, including the model they are deciding against.

The one number this repository does assert is the ceiling:
`tests/test_extract.py` runs each gold answer through the scorer and
fails if it does not come out at 1.0 with zero defects. A perfect answer
has to be reachable, or nothing below it means anything.

## The cases, and what each one is built to catch

| case | the mistake it is for |
|---|---|
| `press-release` | 「同社」 left as a pronoun; 「株式会社アクメ」 opening a second node beside `アクメ`; 「田中」 and 「田中 亮」 becoming two people; a headcount with no predicate to hold it being given one anyway; 「2015年」 turned into a guessed `2015-01-01`; a *former* employer written as a current fact under a `functional` predicate |
| `incident-log` | the same failure on two dates collapsed into one row (a triple's identity includes its time — they are two facts); "the ingest job" not linked to the `ingest` node; an opinion ("we should size the pool") extracted as a fact |
| `vendor-memo` | `Tamaki Metals Co., Ltd.` beside the graph's `Tamaki Metals`; one fact stated twice extracted twice; invoicing complaints and lead times inventing `COMPLAINS_ABOUT` and `HAS_LEAD_TIME` because there is nowhere to put them |

Each case is deliberately adversarial and deliberately small. They are a
diagnostic — they tell you which of these a model does to *your*
ontology — not a benchmark anybody should rank on.

## What is counted

`precision` / `recall` / `f1` on `(s, p, o, at)` against the gold answer.
The date is in the tuple because it is in a triple's identity.

Then four counts that matter more than F1 once a graph is something you
have to live with:

- **invented** — rows using a predicate the ontology does not declare.
  The write refuses these, so each one is a row a person had to find and
  throw away. The constrained prompt is handed the list; it should be 0.
- **split** — names that look like one thing written two ways, against
  the graph and within the answer. Each row is *true*, passes every
  check, and becomes a second node no query joins back. The exact-match
  half of the rule is reliable; the substring half is a hint, so every
  pair is listed under `--json` to be read rather than trusted.
- **unquotable** — rows whose `prov` is missing or is not a verbatim span
  of the document. No judge model and no threshold: a substring test
  against the source. This is what asking for a verbatim quote buys, and
  it is the cheapest hallucination check in the pipeline.
- **blocked** — rows `merge.preview` stops before the write. Not a defect
  of the model: work the graph did instead of the reviewer.

And **review**, the row count, because recall bought with fifty
speculative rows is not the same product as recall bought with eight.
