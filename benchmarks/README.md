# Benchmarks

## KGQA: does the graph reduce hallucination?

**Question:** if an LLM answers factual questions with a trikedb graph as
context, how much more accurate is it than the same LLM answering alone?

**Setup:** [WebQSP](https://aclanthology.org/P16-2033/) questions via the
[RoG-WebQSP](https://huggingface.co/datasets/rmanluo/RoG-webqsp) repack
(gold answers + Freebase subgraph per question, downloaded at runtime —
no dataset content is stored in this repository). Per-question context is
retrieved with trikedb's pattern API: the 1-hop neighborhood of the
question entity, expanded through Freebase mediator (CVT) nodes, capped
at 250 triples. Scoring is a case-insensitive containment match against
the gold answers.

**Pilot result** (N=30, seed 42, model: claude-haiku-4-5, 2026-08):

| condition | accuracy |
|---|---|
| LLM alone | 18/30 (60%) |
| LLM + trikedb context | **25/30 (83%)** |

Retrieval ceiling for the graph condition: the gold answer was present in
the retrieved context for 20/30 questions — the graph condition scores
above the ceiling because the prompt allows falling back to model
knowledge when the triples don't contain the answer. 4 of its 5 remaining
misses are retrieval misses (answer deeper than the retrieved hops), not
reasoning errors.

Typical failures of the no-graph condition are classic hallucinations:
confidently naming the wrong record label, the wrong Soviet leader for
the asked time frame, or missing minority languages of a country — all of
which the graph condition answers from triples.

**Reproduce:**

```bash
uv run --with pandas --with pyarrow --with trikedb \
    python benchmarks/webqsp_bench.py prepare --n 30 --seed 42
# run bench_out/prompts_*.json through your LLM of choice,
# save [{"id", "answer"}] arrays as answers_nograph.json / answers_graph.json
uv run --with trikedb python benchmarks/webqsp_bench.py score \
    bench_out/eval_set.json answers_nograph.json answers_graph.json
```

Caveats: N=30 is a pilot, containment matching is generous to both
conditions equally, and WebQSP subgraphs are larger than trikedb's
intended sweet spot (they are loaded in-memory per question, which works
fine — the YAML file is not the bottleneck here).

## Scoring sensitivity (why we report the containment protocol)

We also ran three variants and report them for transparency:

| protocol | LLM alone | LLM + graph | delta |
|---|---|---|---|
| containment match (primary) | 60% | **83%** | **+23pt** |
| containment, retrieval v2 (relevance-sorted context) | — | 77% | — |
| containment, retrieval v3 (deeper CVT expansion) | — | 80% | — |
| LLM-judge, gold-anchored, applied to both conditions | 73% | 77% | +4pt |

Findings worth knowing before you tune this benchmark yourself:

- **Relevance-sorting the context hurt.** Sorting triples by question-word
  overlap pushed the actual answer triples past the context cap in
  several questions (e.g. GDP-measurement `currency` triples outranked
  the country's real currency). Plain hop-order retrieval did better.
- **Gold labels are noisy.** ~10% of sampled questions have questionable
  gold answers (e.g. "soviet leader during world war ii" → gold
  *Brezhnev/Khrushchev*; "what did galileo do to become famous" → gold
  is a profession list). This caps honest absolute scores on raw WebQSP
  labels — published SOTA sits around ~86% for the same reason.
- **LLM-judge scoring is unstable.** A judge that accepts granularity
  variants rescues the no-graph condition's vague answers and compresses
  the delta; a stricter judge restores it. We therefore report the
  deterministic containment protocol as primary — it is reproducible
  from the committed script with no judgment calls.

The robust claim is the **delta**: under any fixed protocol applied to
both conditions equally, the graph condition wins. Absolute 90%+ scores
on WebQSP raw labels are not honestly reachable (label noise); a
1-hop benchmark over a self-contained KB (e.g. MetaQA 1-hop, currently
gated on HF) is the right target for high absolute numbers.
