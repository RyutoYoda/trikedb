<p align="center">
  <b>English</b>
  &nbsp;·&nbsp; <a href="https://github.com/RyutoYoda/trikedb/blob/main/benchmarks/README_jp.md">日本語</a>
  &nbsp;·&nbsp; <a href="https://github.com/RyutoYoda/trikedb/blob/main/benchmarks/README_zh.md">简体中文</a>
</p>

**Evaluation boundary:** historical local substring answer matching, not the official WebQSP metric. Memory/agent corpora were built using gold-answer paths and filtered for reachable questions; this is a selected synthetic task. The 50-fact result is 86% versus full-file 82% (100 paired questions, McNemar p=0.454), which does not establish higher accuracy. Median input tokens fall 88.4%. See [audit and reproducibility notes](VALIDATION.md).

# Benchmarks

Historical measurements; 8B uses 300 questions and 27B uses 150. F1 was rescored on 2026-09-09; timings were not rerun. Graph conditions include grounding instructions.

| | |
|---|---|
| **Retrieval** | trikedb put the gold answer in front of the model for **89.3%** of questions |
| **Speed** | **0.59 s** reported retrieval; **22.48 s** independently measured model request |
| **Scale** | fast to **100,000 triples**; semantic search gives out first, at 30,000 |
| **End to end** | a laptop-sized 8B reader then answers **77.7%** correctly, against **42.7%** with no graph |
| **Against a file** | At 492 facts, 88.4% fewer median input tokens; answer matching 86% versus 82% (not significant) |

## Accuracy

![Hits@1 by model and condition](accuracy.png)

| condition | Hits@1 | F1 | n |
|---|---|---|---|
| `qwen3:8b` alone | 42.7% | 27.7% | 300 |
| `qwen3:8b` + graph | **77.7%** | **59.2%** | 300 |
| `qwen3.8:27b` alone | 44.0% | 30.2% | 150 |
| `qwen3.8:27b` + graph | 67.3% | 56.7% | 150 |

Within each model, the graph and no-graph arms use matching questions. The 8B pair has 300 answers per arm; the 27B pair has 150. The stored graph runs are named `grounded`: they combine retrieved triples with extra instructions to copy answer names. The observed +35 points for 8B therefore measures **retrieval plus grounding instructions**. Historical answer logs do not contain the exact prompts, so their style cannot be independently reconstructed from the answers alone. New runs record prompt text, SHA-256, model, condition and style.

On the same 300 questions, answer-string presence in retrieved context is 268/300 (89.3%), while correct answers are 233/300 (77.7%). Their cross-tabulation is:

| | Correct answer | Incorrect answer |
|---|---:|---:|
| Gold string in context | 230 | 38 |
| Gold string absent | 3 | 29 |

The 38 misses are 12.7 percentage points; subtracting 3 context-absent correct answers yields a net gap of 35/300 (11.7 points before rounding). String presence is neither proof of sufficient evidence nor a strict upper bound on model accuracy.

## Against a knowledge file

Project knowledge reaches a model somehow. The usual way is `CLAUDE.md` /
`AGENTS.md` — the whole file, in the context, on every question. The
alternative is a graph the model retrieves from. `memory_bench.py` builds one
corpus and renders it both ways: same facts, same questions, same reader, one
request each, and the corpus grows.

The two filenames are the same mechanism under different harnesses, and both
were measured in the one that reads them — `CLAUDE.md` in Claude Code,
`AGENTS.md` in Codex, in the agent section below. The table here is a raw
model behind one HTTP call, where the file is a payload and its name is
arbitrary.

![Prompt tokens per question as the corpus grows](memory.png)

| facts in the project | as a knowledge file | trikedb, 15 facts returned |
|---|---|---|
| 492 | 9,668 tok · 82.0% | 409 tok · 77.0% |
| 1,181 | 22,153 tok · 72.0% | 397 tok · **73.0%** |
| 1,625 | 30,354 tok · 71.0% | 389 tok · **72.0%** |
| 2,246 | does not fit | 390 tok · 71.0% |
| 3,998 | does not fit | 375 tok · 68.0% |

100 questions, `qwen3:8b`, temperature 0, one request per question so the arms
are turn-matched. No context at all scores 35.0%.

Read the columns separately, because at 492 facts they are not equivalent: the
graph is 5 points behind there, so its 409 tokens buys a worse answer and the
ratio is not a like-for-like saving. How many facts trikedb returns is a knob
(`--cap`), and the honest comparison sets it to where the answers match:

| 492 facts, the file scores 82.0% on 9,668 tokens | Hits@1 | tokens | tokens saved |
|---|---|---|---|
| trikedb, 15 facts | 77.0% | 409 | 95.8%, but 5 points behind |
| **trikedb, 50 facts** | **86.0%** | **1,117** | **88.4%, and 4 points ahead** |
| trikedb, 150 facts | 88.0% | 3,125 | 67.7%, and 6 points ahead |

Measured token reductions depend on the retrieval budget; the 50-fact accuracy difference is not significant (p=0.454). Choosing the budget on these same test questions is exploratory tuning, not held-out validation.

The whole-file arm deliberately sends all Markdown content. Its observed 82% at 492 facts is a result for that prompt, reader and sample, not a ceiling for files. Markdown can also be indexed, split into sections, or retrieved semantically. The 88.4% token reduction with 86% versus 82% accuracy is an observation on these 100 questions, not a universal accuracy advantage.

The growth curve follows the harness: whole-file input grows with the corpus; capped retrieval sends at most the chosen number of facts. At 2,246 and 3,998 facts the recorded token/character counts indicate context truncation, so those whole-file rows do not measure reading the entire corpus. They do not establish a universal Ollama truncation policy.

Keyword retrieval of the same Markdown scores 68% → 61%, versus 77% → 68% for hybrid retrieval with 15 facts. This compares two retrieval algorithms. It does not isolate a causal benefit of graph structure; a Markdown control with matching embeddings and ranking would be needed.

**Which retrieval matters more than whether.** trikedb can be asked six ways
and they are not interchangeable, so all of them are priced before any model
runs — no LLM, just whether a gold answer reached a 15-triple context:

![Answer-in-context by retrieval method](retrieval_methods.png)

| method | 492 facts | 3,998 facts |
|---|---|---|
| `hybrid` (entity + semantic) | **94%** | **86%** |
| `find` (node payloads) | 92% | 72% |
| `search` (semantic only) | 84% | 72% |
| `1-hop + CVT` | 73% | 73% |
| `2-hop` | 73% | 71% |
| `1-hop` | 51% | 52% |
| `AGENTS.md`, matching lines | 74% | 60% |

Picking `search` and calling it "the graph" costs 10-14 points against
`hybrid` at the same budget. The numbers above use `hybrid`.

### Inside a real agent

The same corpora through Claude Code and Codex, with the file loaded from disk
into the system prompt the way each harness actually does it. Tokens as the
harness reports them, not dollars: cost depends on which cache band a token
lands in and on session lifetime, and this benchmark controls neither.

![Tokens and accuracy in two agent CLIs](agent.png)

| | 492 facts | 1,625 facts | 3,998 facts |
|---|---|---|---|
| Claude Code, `CLAUDE.md` | 41,318 · 70.0% | 63,172 · 63.3% | 110,839 · 70.0% |
| Claude Code, trikedb | 31,377 · 66.7% | 29,769 · 60.0% | **29,758 · 66.7%** |
| → tokens saved | 24.1% | 52.9% | **73.2%** |
| Codex, `AGENTS.md` | 29,173 · 73.3% | 58,308 · 60.0% | 87,153 · 56.7% |
| Codex, trikedb | 20,523 · 66.7% | 20,503 · 66.7% | **20,510 · 66.7%** |
| → tokens saved | 29.7% | 64.8% | **76.5%** |

30 questions, `claude-haiku-4.5` and Codex's default. Every row is one turn
except Codex's file arm, which took a second turn at 1,625 facts and a third
at 3,998 — it starts working to find things in a file that large, and that is
part of why its token count climbs. Most of each number is the harness's own
prompt — 31,014 tokens for Claude Code with no project knowledge at all —
which neither arm avoids.
In these Codex runs: as the corpus grows its file arm gets both more
expensive and *less* accurate (73.3% → 56.7%) while the graph arm holds
66.7% on a flat 20,510 tokens.

**Letting the agent query the graph itself was worse.** Given the MCP server
and told to use it, both harnesses spent three or four turns, and every turn
re-sends the prefix: 85,098 tokens at 26.7% for Claude Code, 84,730 at 70.0%
for Codex. Retrieving once *before* the agent runs and putting the result in
the prompt beat it on tokens in both harnesses and on accuracy in one. That is
the configuration the rows above use, and it is what a context hook does.

## Speed

![Where the time goes in one question](speed.png)

The published retrieval median is **0.59 s over 30 questions** (graph construction plus hybrid retrieval). The independent model HTTP-request median is **22.48 s over 20 questions**, excluding retrieval. These are different samples: subtracting or stacking them does not measure end-to-end time. The earlier 3% time-share chart was incorrect. The model measurement survives in a saved summary; individual retrieval timings were not retained, so 0.59 s is a historical reported value, not a fresh verification. Semantic search uses embeddings and a cache. Prompt sizes below are character-count estimates, not tokenizer measurements.

| retrieval | answer in context | prompt |
|---|---|---|
| 1-hop + CVT, 250 triples | 70.7% | ~4,377 tokens |
| **hybrid, 250 triples** | **89.3%** | ~4,377 tokens |
| semantic only, 250 triples | 88.7% | ~4,377 tokens |
| hybrid, 100 triples | 81.3% | ~1,823 tokens |

Same budget, better selection: +18.6 points of usable context for free. The
entity anchor is worth almost nothing next to plain ranking — 0.6 points at 250
triples, and a slight loss at 100.

## Scale

![Each operation hits its own ceiling](ceiling.png)

| triples | open `.json` | open `.yaml` | save `.yaml` | SPARQL 2-hop | `to_html` | `search()` |
|---|---|---|---|---|---|---|
| 733 | 1 ms | 9 ms | 8 ms | 1 ms | 14 ms | 19 ms |
| 7,333 | 5 ms | 122 ms | 101 ms | 9 ms | 163 ms | 155 ms |
| 20,400 | 13 ms | 456 ms | 305 ms | 26 ms | 491 ms | 4.3 s |
| 73,333 | 71 ms | 1.6 s | 1.0 s | 94 ms | 1.9 s | 13.5 s |
| 204,000 | 147 ms | 4.6 s | 3.2 s | 297 ms | 6.0 s | 41.9 s |

These historical observations cover 733–204,000 triples in one synthetic graph family on Apple silicon. They do not establish a universal capacity limit or behavior beyond the measured range. Open/save/SPARQL are medians of 3; HTML and search are each one timed sample after warm-up. Search timing excludes initial model/index warm-up. Queries run in memory after loading; end-to-end latency still depends on the storage backend. The older backend +1-fact experiment added the same fact repeatedly, so its historical column measures reload/save with only the first repetition adding a fact.

## Reproduce

```bash
uv run --extra all --with polars --with model2vec \
    python benchmarks/webqsp_bench.py prepare --n 300 --seed 42 \
    --retrieval "hybrid (entity + semantic)" --cap 250 --out bench_out/hybrid

for cond in nograph graph; do
  uv run --extra all --with polars python benchmarks/webqsp_bench.py run \
      bench_out/hybrid/eval_set.json --model qwen3:8b --condition $cond \
      --style grounded --out bench_out/ans_$cond.jsonl --workers 8
done

uv run --extra all python benchmarks/webqsp_bench.py score \
    bench_out/hybrid/eval_set.json bench_out/ans_nograph.jsonl bench_out/ans_graph.jsonl
uv run --extra all python benchmarks/webqsp_bench.py compare \
    bench_out/hybrid/eval_set.json bench_out/ans_nograph.jsonl bench_out/ans_graph.jsonl
```

The reader is local and named on purpose: the score depends on it, so it has to
be re-runnable without an API key. `score` prints Wilson intervals; `compare`
runs the paired test, which is the right one here because both runs answer the
same questions with the same model.

Scale numbers come from `ceiling_bench.py` (3 repeats for open/save/SPARQL; 1 warm sample for HTML/search, one synthetic
pipeline-shaped graph, Apple silicon); backend numbers from `backend_bench.py`;
the retrieval comparison from `retrieval_bench.py`, which `webqsp_bench.py`
imports rather than reimplementing.

The knowledge-file comparison is `memory_bench.py`. One `prepare` builds every
corpus size as a nested tier, so the questions are identical at every size:

```bash
uv run --extra all --with polars --with model2vec \
    python benchmarks/memory_bench.py prepare --n 100 --seed 42 \
    --distractors 0,150,250,400,900 --facts-per-q 5 --out bench_out/memory

for tier in d0 d150 d250 d400 d900; do
  for cond in none md md_grep graph; do
    uv run --extra all --with polars --with model2vec \
        python benchmarks/memory_bench.py run bench_out/memory/$tier \
        --condition $cond --model qwen3:8b \
        --out bench_out/memory/$tier/ans_$cond.jsonl
  done
done

uv run --extra all --with model2vec \
    python benchmarks/memory_bench.py methods bench_out/memory --cap 15
uv run --extra all python benchmarks/memory_bench.py sweep bench_out/memory
```

`methods` needs no model and finishes in seconds; `sweep` is the growth curve.
The agent rows are `agent_bench.py`, which drives the `claude` and `codex`
CLIs (`--harness`) and reads the token counts each one reports. Put its
workspaces outside a git repository with `--workspace-root`: both CLIs walk up
from the working directory looking for a knowledge file, and an unrelated
`CLAUDE.md` two levels up gets measured as part of the condition.

## What this does not show

- These are historical observations, not a fresh model or performance run of this release. Accuracy summaries were rescored from saved answers after fixing F1; timing and token measurements were retained.
- Hits@1 is a local normalized substring check over the answer text; F1 uses newline-separated predictions, matched-prediction precision and matched-gold recall. Both are bounded by 0 and 1. This scorer is not claimed to reproduce an official WebQSP/RoG scorer, and these numbers should not be directly ranked against published scores.
- WebQSP question-specific graphs and curated memory corpora are separate experiments. Gold-informed curation and retained reachable questions limit generalization. Answer-string presence and two-hop reachability do not establish an accuracy ceiling.
- There is no matched vector-RAG or alternative database control. Retrieval, grounding instructions, graph representation and ranking effects are not independently identified.
- Agent results use fresh sessions. Compare within the same harness, corpus, condition and cache state. Cache creation, cache reads, fresh input and output have different costs; token reductions alone are not dollar savings. Subtracting independent medians does not isolate knowledge cost.
- Codex file runs use median 1, 2 and 3 turns at 492, 1,625 and 3,998 facts; pre-retrieved graph runs use 1. Claude Code uses 1 for both. The chart therefore includes a harness-loop difference.
- External warehouse durability, production throughput and long interactive sessions are outside these benchmark results.
