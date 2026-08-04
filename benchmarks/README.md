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
