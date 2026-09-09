"""AGENTS.md against a graph: the same facts, delivered two ways.

The question this answers is the one every agent codebase actually faces.
You have a body of project knowledge — table names, ownership, ingestion
routes, conventions. You can write it into `CLAUDE.md` / `AGENTS.md`, where
the whole file is pasted into the context on every single turn, or you can
put it in a trikedb graph and hand the agent only the facts a question
needs. **Which one answers correctly, how fast, and at what token cost?**

Method
------
Both conditions are fed *the same facts*. One corpus is built once, and then
rendered twice — once as a markdown knowledge file, once as a
`corpus.yaml` trikedb graph. Nothing is in one arm and not the other, so the
difference is delivery, never content.

The corpus is built from WebQSP (via the RoG repack), the same public
benchmark `webqsp_bench.py` uses, so the accuracy numbers are computed with
the published metric implementation and can be read next to the literature.
Each question contributes a small curated slice of its Freebase subgraph —
the answer-bearing facts plus their neighbourhood, which is what a careful
person writing the file down would have kept. Questions whose subgraph
contains no answer-bearing fact are dropped, because they are unanswerable
from the corpus in *both* arms and only add noise to the comparison.

Distractor questions contribute slices to the corpus without being asked.
That is the axis that matters: a knowledge file grows as the project grows,
and the cost of the markdown arm grows with it, while the graph arm sends the
same handful of triples no matter how large the corpus gets.

Conditions
----------
- ``none``     no context. The floor — what the model already knows.
- ``md``       the entire markdown file in the prompt, every question.
               This is literally what CLAUDE.md / AGENTS.md does.
- ``md_grep``  only the lines of that file that match the question, by
               keyword. The control that keeps this honest: it separates
               "retrieval helps" from "a *graph* helps".
- ``graph``    trikedb's own retrieval over `corpus.yaml`, capped.

Measured
--------
Hits@1 and F1 (`webqsp_bench`'s implementations, unmodified), wall-clock
seconds per answer, and **real** prompt/completion token counts as reported
by the server — not a `len(text) // 4` estimate, because the whole point of
the markdown arm is that its token bill is large and it deserves to be
counted rather than approximated.

Usage
-----
One `prepare` builds every corpus size as a nested tier under `d<n>/`:

    uv run --extra all --with polars --with model2vec \\
        python benchmarks/memory_bench.py prepare \\
        --n 100 --distractors 0,150,250,400,900 --facts-per-q 5 \\
        --out bench_out/memory

    for tier in d0 d150 d250 d400 d900; do
      for cond in none md md_grep graph; do
        uv run --extra all --with polars --with model2vec \\
          python benchmarks/memory_bench.py run bench_out/memory/$tier \\
          --condition $cond --model qwen3:8b \\
          --out bench_out/memory/$tier/ans_$cond.jsonl
      done
    done

    uv run --extra all python benchmarks/memory_bench.py score bench_out/memory/d0
    uv run --extra all python benchmarks/memory_bench.py sweep bench_out/memory

`score` is one tier, `sweep` is the growth curve across all of them. Add
`--obfuscate` to `prepare` for a corpus whose answers no model can already
know — needed with any reader strong enough to have memorised WebQSP, and the
reason `agent_bench.py` uses it.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import webqsp_bench as wq  # noqa: E402  — metrics and the answer instruction

CONDITIONS = ("none", "md", "md_grep", "graph")

#: How many facts per question end up in the corpus. Small on purpose: this
#: is a *curated* file, not a dump, and the markdown arm should be judged at
#: the size a human would actually maintain. Fifteen facts is roughly what
#: one entity's paragraph in an AGENTS.md looks like.
DEFAULT_FACTS_PER_Q = 15

#: What the graph arm is allowed to send per question. Matched to
#: FACTS_PER_Q so it can deliver about one question's worth of the corpus —
#: the graph is not being handed a bigger budget than the file has per topic.
DEFAULT_CAP = 15


# ------------------------------------------------------------------ corpus

def _answer_bearing(triples, answers):
    """Facts that name a gold answer on either end.

    Both ends, not just the object: WebQSP subgraphs are undirected in
    practice — half the gold answers appear as the subject of the fact that
    connects them to the question entity.
    """
    wanted = [a.lower() for a in answers if a.strip()]
    return [t for t in triples
            if any(a == t.s.lower() or a == t.o.lower() for a in wanted)]


def _paths_to_answers(db, entities, answers, hops=2):
    """Shortest chains of facts from a question entity to each gold answer.

    Breadth-first over the subgraph treated as undirected, because WebQSP's
    is: a gold answer is as often the subject of the fact that reaches it as
    the object. Returns one chain per answer found, shortest first.
    """
    golds = {a.lower() for a in answers if a.strip()}
    reached_by = {}
    seen = set(entities)
    frontier = list(entities)
    found = []
    for _ in range(hops):
        nxt = []
        for node in frontier:
            for triple in list(db.triples(s=node)) + list(db.triples(o=node)):
                other = triple.o if triple.s == node else triple.s
                if other in seen:
                    continue
                seen.add(other)
                reached_by[other] = (triple, node)
                nxt.append(other)
                if other.lower() in golds:
                    found.append(other)
        frontier = nxt
    chains = []
    for node in found:
        chain, cursor = [], node
        while cursor in reached_by:
            triple, previous = reached_by[cursor]
            chain.append(triple)
            cursor = previous
        chains.append(list(reversed(chain)))
    chains.sort(key=len)
    return chains


def curate(db, question, entities, answers, k):
    """The slice of a subgraph a person would have written down.

    Built as **paths**, not as a set of interesting facts, and that is the
    whole design. An earlier version took the answer-bearing triples first
    and spent whatever budget was left on the question entity's
    neighbourhood. It looked right and it was not: for a question with three
    gold answers, five facts of budget went entirely on answer-bearing
    triples and none on the hop that ties them to the thing being asked
    about. The answer string was in the corpus and nothing led to it.

    That failure is invisible in the obvious check. Measured on the corpora
    that version produced, the answer string was present for 100 of 100
    questions while only **36** had it reachable within two hops of anything
    the question names — so both arms were capped at 36% by the corpus, and
    every score above that was the reader answering from what it already
    knew. A benchmark of two delivery mechanisms cannot afford a corpus that
    neither mechanism can deliver from.

    So each gold answer contributes the chain of facts that reaches it, whole
    or not at all, and chains are added shortest-first until the budget runs
    out. Questions with no chain at all are dropped by returning ``[]``:
    unreachable in the subgraph means unanswerable in every arm.
    """
    import retrieval_bench as rb

    chains = _paths_to_answers(db, entities, answers)
    if not chains:
        return []
    picked = []
    for chain in chains:
        if len(rb._dedupe(picked + chain, k + 1)) > k:
            break                    # a partial chain leads nowhere; skip it
        picked += chain
    if not picked:
        picked = chains[0][:k]       # budget below one hop: keep what fits
    # Whatever budget is left goes to the question entity's own facts, which
    # is what gives the retrieval arms something to match the question
    # against instead of only the answer's own corner of the graph.
    hop1 = []
    for entity in entities:
        hop1 += list(db.triples(s=entity)) + list(db.triples(o=entity))
    return rb._dedupe(picked + hop1, k)


def _slug(name: str) -> str:
    return re.sub(r"\s+", " ", str(name)).strip()


#: Nonsense that still reads like a name, so the corpus looks like a project's
#: and not like a hash dump. Deterministic from the original string: the same
#: entity gets the same alias in every tier and every rerun, which is what
#: makes an obfuscated corpus reproducible at all.
_SYLLABLES = ("var", "quor", "zel", "mek", "tarn", "vex", "lorn", "dask",
              "pell", "rhun", "sithe", "obal", "yarn", "crevin", "topak")


def alias_for(name: str) -> str:
    """A stable invented name for one real entity."""
    import hashlib

    digest = hashlib.sha1(name.encode()).digest()
    parts = [_SYLLABLES[digest[i] % len(_SYLLABLES)] for i in (0, 1)]
    return f"{''.join(parts).capitalize()}-{digest[2] * 256 + digest[3]:05d}"


def obfuscate(eval_set: list, corpus) -> int:
    """Rename every gold answer, in the questions' answers and in the corpus.

    Without this the benchmark cannot answer the question it was built for.
    WebQSP is public trivia, and a current model has read it: measured here,
    claude-haiku-4.5 answers 60% of these questions correctly **with no
    context at all**, against 35% for a local 8B. At that floor neither arm
    can show a gain, because the model is not using the corpus — it already
    knows.

    Project knowledge is the opposite of that by definition: it is what no
    pretraining run has seen. Renaming the answers reproduces that property
    while leaving everything else — the questions, the graph structure, the
    retrieval problem, the metric — exactly as it was. The model's own
    knowledge stops being an answer and starts being a distractor, which is
    the situation a real `CLAUDE.md` is written for.

    Only the answers are renamed, never the entity the question asks about.
    Rewriting "who is the president of costa rica" into a pseudonym would
    make the question unanswerable rather than private, and would do it
    unevenly — the entity is named in the question text sometimes as a full
    name and sometimes not.
    """
    aliases = {a: alias_for(a) for e in eval_set for a in e["answers"]}
    for entry in eval_set:
        entry["answers"] = [aliases[a] for a in entry["answers"]]
    renamed = 0
    for triple in list(corpus.triples()):
        s, o = aliases.get(triple.s), aliases.get(triple.o)
        if s or o:
            corpus.remove(triple.s, triple.p, triple.o)
            corpus.add(s or triple.s, triple.p, o or triple.o)
            renamed += 1
    return renamed


def render_markdown(triples, title: str = "Project knowledge") -> str:
    """The corpus as a knowledge file an agent would be handed.

    Grouped under one heading per subject and written as bullets, because
    that is the shape a real AGENTS.md has — not a flat list of tuples. The
    predicate is kept verbatim so the two arms carry identical information;
    prettifying it here would quietly give the markdown arm a different
    corpus from the graph's.
    """
    by_subject: dict = {}
    for t in triples:
        by_subject.setdefault(_slug(t.s), []).append(t)
    lines = [f"# {title}", "",
             "Facts about this project. Keep this file up to date.", ""]
    for subject in sorted(by_subject):
        lines.append(f"## {subject}")
        for t in by_subject[subject]:
            lines.append(f"- **{_slug(t.p)}** → {_slug(t.o)}")
        lines.append("")
    return "\n".join(lines)


def reachability(corpus, eval_set, hops: int = 2) -> int:
    """How many questions the corpus can actually answer.

    The number that bounds every condition, and the one worth printing
    instead of "the answer string appears somewhere in the file". Presence is
    not reachability: a corpus can name every gold answer and connect none of
    them to the question, and it then reports as perfect while capping the
    whole benchmark. Measured that way, one build of these corpora looked
    like 100/100 and was 36/100.

    A question counts when some corpus node whose name occurs in the question
    text reaches a gold answer within ``hops``. Matching the question by node
    name is an approximation — the eval set keeps questions and answers, not
    the dataset's entity annotations — and it is the conservative direction:
    an entity the question refers to obliquely is missed, so this
    under-reports rather than flatters.
    """
    adjacent: dict = {}
    for triple in corpus.triples():
        adjacent.setdefault(triple.s, set()).add(triple.o)
        adjacent.setdefault(triple.o, set()).add(triple.s)
    names = [n for n in adjacent if len(n) > 3]
    total = 0
    for entry in eval_set:
        golds = set(entry["answers"])
        question = entry["question"].lower()
        seen = {n for n in names if n.lower() in question and n not in golds}
        frontier = set(seen)
        for _ in range(hops):
            frontier = {o for n in frontier for o in adjacent.get(n, ())} - seen
            seen |= frontier
        total += bool(golds & seen)
    return total


def _write_tier(out: Path, corpus, eval_set, meta: dict) -> None:
    """One tier on disk: the graph, the file, the questions, the metadata.

    The corpus is copied before anything is renamed. Obfuscating in place
    would rewrite the accumulator the *next* tier keeps growing, so tier
    d150 would inherit d0's aliases and then alias them again.
    """
    from trikedb import TrikeDB

    if meta.get("obfuscated"):
        copy = TrikeDB(autosave=False)
        for t in corpus.triples():
            copy.add(t.s, t.p, t.o)
        eval_set = [dict(e) for e in eval_set]
        meta = dict(meta, renamed_triples=obfuscate(eval_set, copy))
        corpus = copy
    out.mkdir(parents=True, exist_ok=True)
    corpus.save(out / "corpus.yaml")
    document = render_markdown(list(corpus.triples()))
    (out / "AGENTS.md").write_text(document)
    json.dump(eval_set, open(out / "eval_set.json", "w"),
              ensure_ascii=False, indent=1)
    meta = dict(meta, corpus_triples=len(corpus), document_chars=len(document))
    json.dump(meta, open(out / "corpus_meta.json", "w"), indent=1)

    reachable = reachability(corpus, eval_set)
    print(f"{out.name}: {len(corpus)} triples, {len(document):,} chars of markdown"
          f" (~{len(document) // 4:,} tokens), {meta['distractors']} distractors, "
          f"answer reachable for {reachable}/{len(eval_set)}")


def prepare(n: int, distractors: list, seed: int, out: Path,
            facts_per_q: int = DEFAULT_FACTS_PER_Q,
            obfuscated: bool = False) -> None:
    """Build nested corpora and write each out as both a file and a graph.

    ``n`` questions are asked; ``distractors`` more contribute their facts to
    the corpus and are never asked. Sampling both from one shuffle of the
    same split keeps the distractors the same *kind* of content as the eval
    questions — drawn from another dataset they would be trivially separable
    by topic, and the markdown arm would have an easier haystack than any
    real project's.

    Several distractor counts are built in **one pass**, as nested prefixes
    of the same curation order, because the growth curve is the result. Two
    independent `prepare` runs would differ in their eval questions as well
    as their size, and a difference between them could not be attributed to
    either.
    """
    from trikedb import TrikeDB

    tiers = sorted(set(distractors))
    df = wq.load_test_split()
    take = min(n + max(tiers), df.height)
    rows = df.sample(take, seed=seed, shuffle=True).to_dicts()

    corpus = TrikeDB(autosave=False)
    eval_set, dropped, used, pending = [], 0, 0, list(tiers)
    for row in rows:
        # Flushed at the top of the iteration, not the bottom: a tier written
        # after the next slice has already been merged is one question larger
        # than it claims, and `d0` would not be the eval questions alone.
        while pending and len(eval_set) >= n and used - n >= pending[0]:
            tier = pending.pop(0)
            _write_tier(out / f"d{tier}", corpus, eval_set,
                        {"n": len(eval_set), "distractors": used - n,
                         "seed": seed, "facts_per_q": facts_per_q,
                         "obfuscated": obfuscated,
                         "dropped_no_gold_fact": dropped})
        if not pending:
            break
        sub = TrikeDB(autosave=False)
        for s, p, o in row["graph"]:
            sub.add(str(s), str(p), str(o))
        answers = [str(a) for a in row["answer"]]
        slice_ = curate(sub, row["question"], [str(e) for e in row["q_entity"]],
                        answers, facts_per_q)
        if not slice_:
            dropped += 1
            continue
        for t in slice_:
            corpus.add(t.s, t.p, t.o)
        used += 1
        if len(eval_set) < n:
            eval_set.append({"id": str(row["id"]), "question": row["question"],
                             "answers": answers})
        if used % 50 == 0:
            print(f"  curated {used}, corpus {len(corpus)} triples",
                  file=sys.stderr, flush=True)
    for tier in pending:                      # the split ran out before the tier did
        _write_tier(out / f"d{tier}", corpus, eval_set,
                    {"n": len(eval_set), "distractors": used - n, "seed": seed,
                     "facts_per_q": facts_per_q, "obfuscated": obfuscated,
                     "dropped_no_gold_fact": dropped})
    print(f"{len(eval_set)} questions asked, {dropped} dropped for having no "
          f"answer-bearing fact in their subgraph")


# --------------------------------------------------------------- retrieval

_STOP = {"what", "who", "where", "when", "which", "is", "are", "was", "were",
         "the", "a", "an", "of", "in", "on", "for", "to", "did", "do", "does",
         "and", "or", "by", "from", "that", "this", "it", "he", "she", "they",
         "his", "her", "their", "s", "how", "many", "name", "called", "with"}


def grep_lines(document: str, question: str, k: int) -> list:
    """The lines of the file a keyword search would surface.

    This is what an agent with `Grep` and no graph actually gets, and it is
    the arm that keeps the headline honest: without it, any win by the graph
    could be explained by "you sent less text", with nothing said about the
    graph. Section headings are carried along with their matched bullets,
    because a bullet without its subject line is not a fact.
    """
    terms = [w for w in re.findall(r"[a-z0-9]+", question.lower())
             if w not in _STOP and len(w) > 2]
    heading, scored = "", []
    for line in document.splitlines():
        if line.startswith("## "):
            heading = line
            continue
        if not line.startswith("- "):
            continue
        low = line.lower() + " " + heading.lower()
        score = sum(1 for t in terms if t in low)
        if score:
            scored.append((score, heading, line))
    scored.sort(key=lambda r: -r[0])
    out, seen = [], set()
    for _, head, line in scored[:k]:
        if head and head not in seen:
            seen.add(head)
            out.append(head)
        out.append(line)
    return out


def entities_from_question(db, question: str, limit: int = 4) -> list:
    """Corpus nodes the question names, found without an entity oracle.

    The dataset ships a gold `q_entity` per question and this deliberately
    does not use it. Handing the graph the right entity to start from — when
    the markdown arm has nothing of the kind — would measure an annotation
    the graph will not have in production. Matching node names against the
    question text is what an agent can actually do, so it is what the
    entity-based methods get.

    Longest match first: "Costa Rica" should win over "Rica" when both are
    nodes, because the longer name is the more specific claim about what the
    question is about.
    """
    lowered = question.lower()
    hits = [n for n in db.nodes() if len(n) > 3 and n.lower() in lowered]
    hits.sort(key=len, reverse=True)
    return hits[:limit]


def find_payloads(db, question, entities, budget):
    """`find()` — semantic recall, then each hit's whole fact list.

    A different shape of context from the others, and the reason it is worth
    measuring separately: the ranked unit is a *node* with everything known
    about it, not a triple. For a question whose answer hangs off the
    question's own entity that is exactly the right neighbourhood; for one
    that needs a specific edge it spends the budget on an entity's other
    twenty facts.
    """
    from trikedb.db import Triple
    import retrieval_bench as rb

    out = []
    for hit in db.find(question, k=budget):
        for fact in hit.get("facts", []):
            if len(fact) >= 2:
                out.append(Triple(hit["node"], fact[0], fact[1]))
    return rb._dedupe(out, budget)


def graph_methods() -> dict:
    """Every way trikedb can be asked, keyed by name.

    `retrieval_bench`'s five, imported rather than restated, plus `find`.
    Choosing one of these and reporting it as "the graph arm" is how a
    benchmark ends up measuring a single API call instead of the tool: the
    methods select genuinely different triples, and `methods` below prices
    all of them before any model is run.
    """
    import retrieval_bench as rb

    return {**rb.METHODS, "find (node payloads)": find_payloads}


DEFAULT_RETRIEVAL = "hybrid (entity + semantic)"


def graph_context(db, question, entities, k, method: str = DEFAULT_RETRIEVAL):
    """trikedb's own retrieval, over the whole corpus."""
    return graph_methods()[method](db, question, entities, k)


# ------------------------------------------------------------------- asking

_HEADER = "Facts you have been given:\n"


def build_prompt(question: str, context: str, salt: str = "") -> str:
    """One instruction for every condition.

    ``webqsp_bench``'s prompt and its grounding rule, imported rather than
    restated, so a score here means the same thing a score there does. The
    only thing that varies between conditions is the payload under
    ``_HEADER`` — markdown bullets in one arm, triples in another — because
    anything else would confound the delivery mechanism with the wording.

    ``salt`` is one comment line at the very top, and it exists to *lose* the
    server's prefix cache on purpose. A knowledge file is a fixed prefix, so
    the second question of a session and every one after it skips the whole
    prefill — measured here, 7.1 s for the first question and 0.4 s for the
    rest of the same file. That is a real advantage and the warm numbers
    report it. It is also not the whole picture: the first turn of every
    session pays it, an edit to the file pays it again, and the tokens are
    charged whether or not the prefill was skipped. ``--cache cold`` prices
    that turn.
    """
    body = (f"<!-- session {salt} -->\n" if salt else "") + wq._PROMPT
    if context:
        body += "\n" + _HEADER + context + "\n" + wq._GROUNDED
    return body + f"\nQuestion: {question}\nAnswer:"


def _client(host: str, num_ctx: int, timeout: int = 1800):
    """(model, prompt) -> dict with the text *and* the server's token counts.

    ``num_ctx`` is explicit and recorded rather than left at the server's
    default, because getting it wrong silently destroys the markdown arm:
    Ollama does not refuse a prompt that overflows the window, it drops the
    front of it. The file's facts vanish, the run completes, and the arm
    scores like it had no context at all — a wrong number that looks like a
    finding.
    """
    import urllib.request

    def call(model: str, prompt: str) -> dict:
        payload = json.dumps({
            "model": model, "prompt": prompt, "stream": False,
            "options": {"temperature": 0, "num_ctx": num_ctx, "num_predict": 128},
            "think": False,
        }).encode()
        request = urllib.request.Request(
            f"{host}/api/generate", data=payload,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
        return {"text": data.get("response", "").strip(),
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0)}

    return call


def _model_ctx_limit(host: str, model: str, fallback: int = 40960) -> int:
    """The window the model was actually trained for, asked of the server.

    Hard-coding it would be one number to get wrong per model, and the
    consequence of getting it wrong is invisible: ask for more than the model
    has and the answers keep arriving, quietly computed over a prompt that
    was cut to fit.
    """
    import urllib.request

    try:
        request = urllib.request.Request(
            f"{host}/api/show", data=json.dumps({"model": model}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            info = json.load(response).get("model_info", {})
        for key, value in info.items():
            if key.endswith(".context_length"):
                return int(value)
    except Exception:                                       # noqa: BLE001
        pass
    return fallback


def _fit_ctx(needed_tokens: int, floor: int = 4096, ceiling: int = 40960) -> int:
    """Smallest power-of-two window that holds the prompt, with headroom.

    Sized per condition rather than once for the run: giving the graph arm
    the window the markdown arm needs would charge it for a KV cache it never
    uses, and the latency comparison is half the point.

    ``ceiling`` is the model's own limit, and it binds for exactly the reason
    this benchmark exists — a knowledge file large enough stops fitting, and
    what happens then is a result, not a configuration error.
    """
    size = floor
    while size < needed_tokens * 1.15 and size < ceiling:
        size *= 2
    return min(size, ceiling)


def run(bench_dir: Path, condition: str, model: str, out: Path,
        host: str = "http://localhost:11434", cap: int = DEFAULT_CAP,
        limit: int = 0, workers: int = 1, num_ctx: int = 0,
        cache: str = "warm") -> None:
    """Answer every question under one condition, appending as they land.

    Serial by default, unlike ``webqsp_bench.run``: this benchmark reports
    latency as a headline, and a request sharing the GPU with three others is
    not the latency of the configuration. Pass ``--workers`` when only the
    accuracy is wanted.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from trikedb import TrikeDB

    eval_set = json.load(open(bench_dir / "eval_set.json"))
    if limit:
        eval_set = eval_set[:limit]
    document = (bench_dir / "AGENTS.md").read_text()
    db = TrikeDB(bench_dir / "corpus.yaml", autosave=False) if condition == "graph" else None
    if db is not None:                  # pay the embedding cost before timing
        db.search("warm up the index", k=1)

    def context_for(item):
        started = time.perf_counter()
        if condition == "none":
            text = ""
        elif condition == "md":
            text = document
        elif condition == "md_grep":
            text = "\n".join(grep_lines(document, item["question"], cap))
        else:
            text = "\n".join(f"({t.s}, {t.p}, {t.o})"
                             for t in graph_context(db, item["question"], [], cap))
        return text, time.perf_counter() - started

    # One dry pass to size the window, before anything is sent. The biggest
    # prompt of the run decides it, so no answer in the run is silently
    # truncated by a window fitted to the median.
    biggest = max(len(build_prompt(e["question"], context_for(e)[0]))
                  for e in eval_set[: min(len(eval_set), 20)])
    # 3 chars per token is pessimistic on purpose: over-estimating costs a
    # larger KV cache, under-estimating silently truncates the prompt.
    ctx = num_ctx or _fit_ctx(biggest // 3,
                              ceiling=_model_ctx_limit(host, model))
    client = _client(host, ctx)
    print(f"condition={condition} cache={cache} num_ctx={ctx}", file=sys.stderr)

    done = set()
    if out.exists():
        done = {json.loads(l)["id"] for l in out.read_text().splitlines() if l.strip()}
        print(f"resuming: {len(done)} already answered", file=sys.stderr)
    todo = [e for e in eval_set if e["id"] not in done]
    out.parent.mkdir(parents=True, exist_ok=True)
    log, lock, state = out.open("a"), threading.Lock(), {"n": 0, "failed": 0}

    def answer(item):
        context, retrieval_secs = context_for(item)
        prompt = build_prompt(item["question"], context,
                              salt=item["id"] if cache == "cold" else "")
        started = time.perf_counter()
        try:
            result = client(model, prompt)
        except Exception as exc:                            # noqa: BLE001
            # Never recorded: a resume would skip the question forever and
            # the empty answer would score zero as if the model had tried.
            with lock:
                state["failed"] += 1
                print(f"  {item['id']}: {type(exc).__name__} — retry on rerun",
                      file=sys.stderr, flush=True)
            return
        with lock:
            log.write(json.dumps({
                "id": item["id"], "answer": result["text"],
                "secs": round(time.perf_counter() - started, 2),
                "retrieval_secs": round(retrieval_secs, 4),
                # What was *sent*, next to what the server says it *read*.
                # The gap between them is the only reliable way to see a
                # truncated prompt: Ollama cuts an over-long prompt down to
                # half the window and reports the survivor's token count, so
                # nothing in the response says anything was lost.
                "prompt_chars": len(prompt),
                "prompt_tokens": result["prompt_tokens"],
                "completion_tokens": result["completion_tokens"],
                "condition": condition, "num_ctx": ctx, "cache": cache,
            }, ensure_ascii=False) + "\n")
            log.flush()
            state["n"] += 1
            if state["n"] % 10 == 0:
                print(f"  {len(done) + state['n']}/{len(eval_set)}",
                      file=sys.stderr, flush=True)

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(answer, todo))
    else:
        for item in todo:
            answer(item)
    log.close()
    print(f"wrote {out}" + (f" — {state['failed']} left for a rerun"
                            if state["failed"] else ""), file=sys.stderr)


# -------------------------------------------------------------------- score

def _metrics(recs: list, gold: dict) -> dict:
    """Everything one answer file has to say, in one dict.

    Shared by ``score`` and ``sweep`` rather than written twice: the two
    disagreeing about the same file — one counting a truncated prompt, the
    other not — is the kind of divergence nobody notices until the table and
    the chart tell different stories.
    """
    n = len(recs)
    hit = sum(wq.hits_at_1(r["answer"], gold[r["id"]]) for r in recs)
    lo, hi = wq._wilson(hit, n)
    name = recs[0].get("condition", "?")
    if recs[0].get("cache", "warm") != "warm":
        name += "/cold"
    # An over-long prompt is not refused, it is cut down — Ollama keeps about
    # half the window and answers from that, reporting the survivor's token
    # count as if it were the whole prompt. So "the prompt filled the window"
    # does not detect it: a 40,000-token file comes back as 20,482 tokens,
    # comfortably under the limit, having lost most of its facts.
    #
    # What does detect it is the ratio of characters sent to tokens read.
    # English markdown runs about 3.5 characters per token; a run that reads
    # 8 characters per token was charged for less than half of what it was
    # handed. That a knowledge file can outgrow the window is a real result,
    # but only when it is labelled as one rather than read as the model being
    # bad at markdown.
    window = recs[0].get("num_ctx", 0)
    truncated = sum(1 for r in recs
                    if r.get("prompt_chars")
                    and r["prompt_chars"] / max(r["prompt_tokens"], 1) > 5.0)
    return {
        "condition": name, "n": n,
        "hits_at_1": round(100 * hit / n, 1),
        "f1": round(100 * sum(wq.f1(r["answer"], gold[r["id"]]) for r in recs) / n, 1),
        "hits_ci95": [round(lo, 1), round(hi, 1)],
        "median_prompt_tokens": int(statistics.median(
            r["prompt_tokens"] for r in recs)),
        "median_completion_tokens": int(statistics.median(
            r["completion_tokens"] for r in recs)),
        "median_secs": round(statistics.median(r["secs"] for r in recs), 2),
        "first_secs": round(recs[0]["secs"], 2),
        "median_retrieval_ms": round(1000 * statistics.median(
            r.get("retrieval_secs", 0) for r in recs), 1),
        "total_prompt_tokens": sum(r["prompt_tokens"] for r in recs),
        "num_ctx": window,
        "truncated": truncated,
        "median_prompt_chars": int(statistics.median(
            r.get("prompt_chars", 0) for r in recs)),
    }


def score(bench_dir: Path, answers: list = None, out_json: Path = None) -> None:
    """Accuracy, latency and token cost in one table.

    The three are reported together deliberately. Accuracy alone would say
    the arms are close; tokens alone would say one is cheap. The trade is the
    result, so it gets one row per condition and no separate tables.
    """
    gold = {e["id"]: e["answers"] for e in json.load(open(bench_dir / "eval_set.json"))}
    paths = answers or sorted(bench_dir.glob("ans_*.jsonl"))
    meta = json.loads((bench_dir / "corpus_meta.json").read_text())
    print(f"corpus: {meta['corpus_triples']} triples, "
          f"{meta['document_chars']:,} chars of markdown, "
          f"{meta['n']} questions asked, {meta['distractors']} distractors\n")
    header = (f"{'condition':<12}{'Hits@1':>9}{'F1':>8}{'n':>5}"
              f"{'prompt tok':>12}{'secs':>8}{'retrieval':>11}   Hits@1 95% CI")
    print(header)
    rows = []
    for path in paths:
        recs = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        recs = [r for r in recs if r["id"] in gold]
        if not recs:
            continue
        row = _metrics(recs, gold)
        lo, hi = row["hits_ci95"]
        print(f"{row['condition']:<12}{row['hits_at_1']:>8.1f}%{row['f1']:>7.1f}%"
              f"{row['n']:>5}{row['median_prompt_tokens']:>12,}"
              f"{row['median_secs']:>8.1f}{row['median_retrieval_ms']:>9.0f}ms"
              f"   [{lo:.1f}, {hi:.1f}]")
        if row["truncated"]:
            print(f"{'':<12}   ! {row['truncated']}/{row['n']} prompts filled the "
                  f"{row['num_ctx']:,}-token window — context was dropped to fit")
        rows.append(row)
    if out_json:
        out_json.write_text(json.dumps(
            {"corpus": meta, "conditions": rows}, indent=1) + "\n")
        print(f"\nwrote {out_json}", file=sys.stderr)


def sweep(root: Path, out_json: Path = None) -> None:
    """Every tier and every condition in one table — the growth curve.

    The single-tier table answers "which is better here". This one answers
    the question that decides the design: **what happens as the project's
    knowledge grows.** One row per (corpus size, condition), so the two
    trends can be read off against each other — the file's token bill rising
    with the corpus while the graph's stays where it started.
    """
    tiers = sorted((p for p in root.glob("d*") if p.is_dir()),
                   key=lambda p: int(p.name[1:]))
    print(f"{'corpus':>8}{'file tok':>10}  {'condition':<12}{'Hits@1':>8}{'F1':>7}"
          f"{'n':>5}{'prompt tok':>12}{'secs':>7}{'retr':>7}  window")
    rows = []
    for tier in tiers:
        meta = json.loads((tier / "corpus_meta.json").read_text())
        gold = {e["id"]: e["answers"]
                for e in json.load(open(tier / "eval_set.json"))}
        for path in sorted(tier.glob("ans_*.jsonl")):
            recs = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
            recs = [r for r in recs if r["id"] in gold]
            if not recs:
                continue
            row = _metrics(recs, gold)
            row.update(tier=tier.name, corpus_triples=meta["corpus_triples"],
                       file_tokens=meta["document_chars"] // 4,
                       distractors=meta["distractors"])
            flag = ("truncated" if row["truncated"] else
                    f"{row['median_prompt_tokens'] / row['num_ctx']:.0%} full")
            print(f"{row['corpus_triples']:>8,}{row['file_tokens']:>10,}  "
                  f"{row['condition']:<12}{row['hits_at_1']:>7.1f}%"
                  f"{row['f1']:>6.1f}%{row['n']:>5}"
                  f"{row['median_prompt_tokens']:>12,}{row['median_secs']:>7.1f}"
                  f"{row['median_retrieval_ms']:>6.0f}ms  {flag}")
            rows.append(row)
        print()
    if out_json:
        out_json.write_text(json.dumps(rows, indent=1) + "\n")
        print(f"wrote {out_json}", file=sys.stderr)


def methods(root: Path, cap: int = DEFAULT_CAP, out_json: Path = None) -> None:
    """Price every retrieval method against every corpus size, with no model.

    This exists because "the graph arm" is not one thing. trikedb can be
    asked six different ways, they select different triples, and reporting
    one of them as the tool's number is a choice disguised as a measurement.
    No LLM is involved: what is measured is whether a gold answer ends up in
    the context and what the context cost, which is the part that does not
    need a reader and the part that bounds whatever a reader could do.

    `AGENTS.md, matching lines` is in the same table on purpose. It is the
    text baseline at the identical budget, so the column answers "what does
    the graph add over grepping the file" rather than "does retrieval help".
    """
    from trikedb import TrikeDB

    tiers = sorted((p for p in root.glob("d*") if p.is_dir()),
                   key=lambda p: int(p.name[1:]))
    rows = []
    print(f"budget {cap} triples\n")
    for tier in tiers:
        meta = json.loads((tier / "corpus_meta.json").read_text())
        eval_set = json.load(open(tier / "eval_set.json"))
        db = TrikeDB(tier / "corpus.yaml", autosave=False)
        document = (tier / "AGENTS.md").read_text()
        entities = {e["id"]: entities_from_question(db, e["question"])
                    for e in eval_set}
        print(f"{meta['corpus_triples']:,} facts "
              f"(~{meta['document_chars'] // 4:,} tokens as markdown)")
        print(f"  {'method':<28}{'answer in context':>18}{'triples':>9}{'chars':>8}"
              f"{'ms':>7}")
        candidates = dict(graph_methods())
        for name, method in candidates.items():
            reached, sizes, chars, elapsed = 0, [], [], []
            for entry in eval_set:
                started = time.perf_counter()
                try:
                    context = method(db, entry["question"],
                                     entities[entry["id"]], cap)
                except Exception:                           # noqa: BLE001
                    context = []
                elapsed.append(1000 * (time.perf_counter() - started))
                blob = " ".join(f"{t.s} {t.p} {t.o}" for t in context).lower()
                reached += any(a.lower() in blob for a in entry["answers"])
                sizes.append(len(context))
                chars.append(len(blob))
            rows.append({
                "tier": tier.name, "corpus_triples": meta["corpus_triples"],
                "method": name, "n": len(eval_set), "reached": reached,
                "reached_pct": round(100 * reached / len(eval_set), 1),
                "median_triples": int(statistics.median(sizes)),
                "median_chars": int(statistics.median(chars)),
                "median_ms": round(statistics.median(elapsed), 1),
            })
            print(f"  {name:<28}{reached:>8}/{len(eval_set):<9}"
                  f"{rows[-1]['median_triples']:>9}{rows[-1]['median_chars']:>8}"
                  f"{rows[-1]['median_ms']:>7.1f}")
        grep_reached, grep_chars = 0, []
        for entry in eval_set:
            lines = grep_lines(document, entry["question"], cap)
            blob = "\n".join(lines).lower()
            grep_reached += any(a.lower() in blob for a in entry["answers"])
            grep_chars.append(len(blob))
        rows.append({
            "tier": tier.name, "corpus_triples": meta["corpus_triples"],
            "method": "AGENTS.md, matching lines", "n": len(eval_set),
            "reached": grep_reached,
            "reached_pct": round(100 * grep_reached / len(eval_set), 1),
            "median_triples": cap,
            "median_chars": int(statistics.median(grep_chars)),
            "median_ms": 0.0,
        })
        print(f"  {'AGENTS.md, matching lines':<28}{grep_reached:>8}"
              f"/{len(eval_set):<9}{'':>9}{rows[-1]['median_chars']:>8}\n")
    if out_json:
        out_json.write_text(json.dumps(rows, indent=1) + "\n")
        print(f"wrote {out_json}", file=sys.stderr)


def compare(bench_dir: Path, baseline: Path, candidate: Path) -> None:
    """Paired McNemar between two conditions — `webqsp_bench`'s test."""
    wq.compare(bench_dir / "eval_set.json", baseline, candidate)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prepare", help="build one corpus as both a file and a graph")
    p.add_argument("--n", type=int, default=60, help="questions actually asked")
    p.add_argument("--distractors", default="240",
                   help="questions that only contribute facts to the corpus; "
                        "a comma-separated list builds one nested tier each")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--facts-per-q", type=int, default=DEFAULT_FACTS_PER_Q)
    p.add_argument("--obfuscate", action="store_true",
                   help="rename the gold answers so no model can already know "
                        "them — what project knowledge is by definition")
    p.add_argument("--out", type=Path, default=Path("bench_out/memory"))

    r = sub.add_parser("run", help="answer the questions under one condition")
    r.add_argument("bench_dir", type=Path)
    r.add_argument("--condition", choices=CONDITIONS, required=True)
    r.add_argument("--model", required=True)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--host", default="http://localhost:11434")
    r.add_argument("--cap", type=int, default=DEFAULT_CAP,
                   help="context budget for the retrieval conditions")
    r.add_argument("--retrieval", default=DEFAULT_RETRIEVAL,
                   help="which trikedb retrieval the graph arm uses; "
                        "`methods` prices them all")
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--workers", type=int, default=1,
                   help="serial by default: latency is a headline here")
    r.add_argument("--num-ctx", type=int, default=0,
                   help="0 = size it to the largest prompt of the run")
    r.add_argument("--cache", choices=("warm", "cold"), default="warm",
                   help="cold salts every prompt so the server's prefix cache "
                        "never hits — the first turn of a session")

    s = sub.add_parser("score", help="accuracy, latency and tokens in one table")
    s.add_argument("bench_dir", type=Path)
    s.add_argument("answers", type=Path, nargs="*")
    s.add_argument("--json", type=Path, dest="out_json")

    m = sub.add_parser("methods",
                       help="price every retrieval method, no model involved")
    m.add_argument("root", type=Path, help="the directory holding d0/, d150/, ...")
    m.add_argument("--cap", type=int, default=DEFAULT_CAP)
    m.add_argument("--json", type=Path, dest="out_json")

    w = sub.add_parser("sweep", help="every tier and condition — the growth curve")
    w.add_argument("root", type=Path, help="the directory holding d0/, d150/, ...")
    w.add_argument("--json", type=Path, dest="out_json")

    c = sub.add_parser("compare", help="paired significance test of two conditions")
    c.add_argument("bench_dir", type=Path)
    c.add_argument("baseline", type=Path)
    c.add_argument("candidate", type=Path)

    args = ap.parse_args()
    if args.cmd == "prepare":
        prepare(args.n, [int(d) for d in str(args.distractors).split(",")],
                args.seed, args.out, args.facts_per_q, args.obfuscate)
    elif args.cmd == "run":
        run(args.bench_dir, args.condition, args.model, args.out, args.host,
            args.cap, args.limit, args.workers, args.num_ctx, args.cache)
    elif args.cmd == "methods":
        methods(args.root, args.cap, args.out_json)
    elif args.cmd == "sweep":
        sweep(args.root, args.out_json)
    elif args.cmd == "compare":
        compare(args.bench_dir, args.baseline, args.candidate)
    else:
        score(args.bench_dir, args.answers or None, args.out_json)


if __name__ == "__main__":
    main()
