# Benchmark audit — September 2026

The results are historical observations, not a general proof that graphs outperform files. The audit inspected all 13 original benchmark/chart scripts, the six chart data files, three-language explanations and the available saved answer logs. No new paid model-answer run was performed. Library correctness tests and local benchmark smoke tests are separate from benchmark accuracy.

| Finding | Correction / interpretation |
|---|---|
| Speed chart subtracted independent medians and presented a 3% share | Show retrieval 0.59 s (historical report, n=30) and model HTTP request 22.48 s (saved summary, n=20) separately. Neither a paired sum nor a decomposition. Raw retrieval timings are unavailable. |
| 50-fact context called more accurate than full Markdown | 86/100 versus 82/100; candidate-only correct 10, baseline-only 6; exact two-sided McNemar p=0.454. Median input reduction is `1 - 1117/9668 = 88.4%`. Accuracy superiority is not established. |
| Gold-informed corpus and test-set tuning | Memory/agent corpora select paths using gold answers, dropping questions without fitting paths. Retrieval cap was explored on the same questions. These are selected synthetic experiments, not held-out production estimates. |
| Metrics described as general accuracy | Hits@1 here is a local gold-substring match anywhere in an answer, not top-one exact match. Verbose answers can benefit. Local F1 is also lenient and is not official WebQSP scoring. |
| Retrieval presence treated as an accuracy ceiling | Presence is a proxy. On 300 saved questions: 230 present/correct, 38 present/incorrect, 3 absent/correct, 29 absent/incorrect. |
| Resumes could mix models, prompts or data | New runs write configuration/input fingerprints and refuse mismatches or appending legacy logs without manifests. Scorers reject duplicate/foreign IDs and mixed recorded conditions. Partial sets report n; they are not failed questions. |
| Memory CLI accepted but ignored `--retrieval` | Forward the selected method and record it. Context sizing examines every question, not only the first 20; the character/token estimate still cannot guarantee tokenizer-level fit. |
| Corpus could include incomplete answer paths or mislabeled tiers | Reject incomplete paths; sample through the full shuffled split; fail rather than label an incomplete tier as complete. New generated corpora can differ from historical ones. |
| Search errors became empty contexts | Fail visibly; do not count implementation/dependency errors as retrieval misses. Unmeasured grep latency/count is null rather than invented zero/cap. |
| Scale plots claimed all measurements were medians of three | Open/save/SPARQL: 3 repeats. HTML/search: 1 warm sample. Maximum measured size 204,000 triples; no claim beyond it. Historical hardware/software versions are incompletely recorded. |
| Backend +1 fact repeatedly added the same fact | Each repetition adds a distinct fact. Historical values describe reload/save, with only the first repetition mutating. Temporary SQL names are unique per run and cleanup deletes exact owned names in finally. |
| Agent parsing and accounting | Accept Claude object/array JSON, reject failed subprocess results, avoid adding reasoning-token subsets twice, label Codex turns as a tool-call estimate. Reject unsupported Codex continuation and continuation resumes that would lose history. Require a model for new runs. |
| Agent environment isolation | Temporary workspaces are unique and outside the repository by default. Codex MCP overrides do not disable other configured servers: a dedicated profile is required. Historical default Codex model/profile was not fully recorded. |
| Chart interpretation | Independent latency bars; neutral token titles; full-file truncation flags; zero-based agent token and retrieval-percentage axes; readable legends and explicit sample sizes. |

The main audit rechecked 40 saved logs (36 memory/agent and 4 primary WebQSP answer files). Question IDs were unique and matched their evaluation sets, and recorded configuration fields were consistent within each file. Missing historical metadata cannot be reconstructed by this check. The 27B comparison contains 150 answers per arm, versus 300 for 8B. Input-token summaries and answer-match rates were checked against those logs. All 35 retrieval-presence rates (5 corpus sizes × 7 methods) were also rerun locally and matched the committed summary; timings from that rerun were kept separate from historical values.

`warm`/`cold` in historical memory logs mean unsalted/salted prompts, not verified cache hits/misses. Context truncation is inferred from character/token ratios, not a server-provided truncation flag. Obfuscating gold-answer nodes may also change another question's lexical anchor; it is not equivalent to unseen private data. Retrieval uses pre-retrieved RoG subgraphs and provided entity annotations in the WebQSP experiment; it is not full-Freebase entity linking. `1-hop + CVT` uses an ID-prefix heuristic, and `2-hop` expands outgoing edges on the second hop.

Full-file versus pre-retrieved agent context compares delivery choices, prompts and sometimes tool loops. Codex `turns` is historically estimated as one plus tool calls; multiple tools can share a model request. Cache creation, cache reads and fresh input have different prices. Token reductions do not establish dollar savings. Native MCP results at 3,998 facts are 26.7%/85,098 input tokens for Claude and 70.0%/84,730 for Codex; the pre-retrieved rows are a different condition.

## Reproduce the audit

```bash
python -m pytest tests/test_benchmarks.py -q
python benchmarks/validate_saved.py bench_out/memory --out audit.json
python benchmarks/memory_bench.py compare bench_out/memory/d0 \
  bench_out/memory/d0/ans_md.jsonl bench_out/memory/d0/ans_graph_cap50.jsonl
```

The answer logs and downloaded dataset are not distributed in the package. `validate_saved.py` requires the local raw logs and matching `eval_set.json`; committed summary JSON alone cannot reproduce per-question scoring or paired tests. Start new benchmark outputs after this audit rather than appending to historical logs. Keep dataset snapshots, model digest, CLI/dependency versions, prompt hashes, cache conditions and raw timing samples when collecting new publishable results.
