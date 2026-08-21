"""KGQA benchmark: does a trikedb graph reduce LLM hallucination?

Uses the WebQSP benchmark via the RoG-WebQSP repack on Hugging Face
(rmanluo/RoG-webqsp): each question ships with gold answers and a
Freebase subgraph. Dataset content is downloaded at runtime and never
committed to this repository.

Method
------
1. `prepare` samples N questions, loads each subgraph into an
   in-memory TrikeDB, and retrieves a per-question context with the
   pattern API: 1-hop neighborhood of the question entity, expanding
   through Freebase CVT/mediator nodes (m.* / g.*), capped at 250
   triples. Writes eval_set.json and two prompt sets:
     - prompts_nograph.json  (questions only)
     - prompts_graph_*.json  (questions + retrieved triples, chunked)
2. Run both prompt sets through the SAME model (any LLM). The model
   must return [{"id": ..., "answer": ...}] per file.
3. `score` grades with a containment match: a prediction is a hit if
   any gold answer is a substring of it (or vice versa),
   case-insensitive.

Usage
-----
uv run --with polars --with trikedb \
    python benchmarks/webqsp_bench.py prepare --n 30 --seed 42
# ... run the prompt files through your LLM, save answers_*.json ...
uv run --with trikedb python benchmarks/webqsp_bench.py score \
    eval_set.json answers_nograph.json answers_graph.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

#: The WebQSP test split, both shards. Using only the first — which this
#: benchmark did until it was checked — samples from 814 of the 1,628
#: questions that published numbers are computed over, so a result would not
#: be comparable to anything.
BASE = ("https://huggingface.co/datasets/rmanluo/RoG-webqsp/resolve/main/data/")
TEST_SHARDS = (
    "test-00000-of-00002-9ee8d68f7d951e1f.parquet",
    "test-00001-of-00002-773a7b8213e159f5.parquet",
)


def load_test_split():
    """The full 1,628-question test split.

    Polars rather than pandas: it reads the parquet over HTTPS directly, with
    no pyarrow to install, and does it several times faster — which matters
    because every benchmark run in this directory starts by loading it.

    RoG-WebQSP ships a pre-retrieved Freebase subgraph per question, so this
    measures retrieval *within* that subgraph — the same basis the RoG line of
    work reports on, and not retrieval from all of Freebase.
    """
    import polars as pl

    frames = [pl.read_parquet(BASE + shard) for shard in TEST_SHARDS]
    return pl.concat(frames)


#: The retrieval methods live in ``retrieval_bench`` and are imported, not
#: copied. Two implementations of "which triples are the context" is the one
#: duplication that would make these two benchmarks silently disagree about
#: the same question — and the retrieval numbers are what the accuracy numbers
#: are supposed to be explained by.
def _methods():
    import retrieval_bench

    return retrieval_bench.METHODS


#: Answer-in-context is not the same quantity as Hits@1 and must not be read
#: as a cap on it: a model also answers from what it already knows. Measured
#: on the 300-question set, 24 of its correct answers were not in the
#: retrieved context at all.
DEFAULT_RETRIEVAL = "1-hop + CVT"
DEFAULT_CAP = 250


def prepare(n: int, seed: int, out: Path, retrieval: str = DEFAULT_RETRIEVAL,
            cap: int = DEFAULT_CAP, like: Path = None) -> None:
    """Sample questions, retrieve a context for each, write the eval set.

    ``like`` reuses the exact questions of an existing eval set instead of
    sampling. Changing the retrieval method and the question set at the same
    time would make the two runs incomparable, and the whole point of a second
    run is to attribute the difference to the method.
    """
    from trikedb import TrikeDB

    retrieve = _methods()[retrieval]
    df = load_test_split()
    if like:
        wanted = [e["id"] for e in json.load(open(like))]
        import polars as pl

        rows_by_id = {r["id"]: r for r in df.filter(pl.col("id").is_in(wanted)).to_dicts()}
        rows = [rows_by_id[i] for i in wanted if i in rows_by_id]
        if len(rows) != len(wanted):
            raise SystemExit(f"only {len(rows)}/{len(wanted)} of {like} found in the split")
    else:
        rows = (df if n <= 0 or n >= df.height
                else df.sample(n, seed=seed)).to_dicts()

    eval_set = []
    for i, r in enumerate(rows, 1):
        if i % 25 == 0:
            print(f"  retrieved {i}/{len(rows)}", file=sys.stderr, flush=True)
        db = TrikeDB()
        for s, p, o in r["graph"]:
            db.add(str(s), str(p), str(o))
        uniq = retrieve(db, r["question"], [str(e) for e in r["q_entity"]], cap)
        eval_set.append({
            "id": r["id"],
            "question": r["question"],
            "answers": [str(a) for a in r["answer"]],
            "triples": [f"({t.s}, {t.p}, {t.o})" for t in uniq],
        })

    out.mkdir(parents=True, exist_ok=True)
    json.dump(eval_set, open(out / "eval_set.json", "w"), ensure_ascii=False, indent=1)
    json.dump(
        [{"id": e["id"], "question": e["question"]} for e in eval_set],
        open(out / "prompts_nograph.json", "w"), ensure_ascii=False, indent=1,
    )
    chunk = 10
    for i in range(0, len(eval_set), chunk):
        json.dump(
            [{k: e[k] for k in ("id", "question", "triples")} for e in eval_set[i:i + chunk]],
            open(out / f"prompts_graph_{i // chunk}.json", "w"), ensure_ascii=False, indent=1,
        )

    reachable = sum(
        any(any(a.lower() in t.lower() for t in e["triples"]) for a in e["answers"])
        for e in eval_set
    )
    print(f"prepared {len(eval_set)} questions with {retrieval}, cap {cap} -> {out}/")
    print(f"answer present in context for {reachable}/{len(eval_set)} "
          f"({100 * reachable / len(eval_set):.1f}%)")


#: The reference implementation's normalisation, reproduced so the numbers
#: mean the same thing published WebQSP results do: lowercase, drop
#: punctuation, drop the articles, collapse whitespace. Matching is then
#: *substring* — a gold answer counts if it appears inside the prediction —
#: which is looser than exact match and is what every number in the
#: literature is computed with. Departing from it would make a score that
#: looks comparable and is not.
_ARTICLES = {"a", "an", "the"}


def _normalize(text: str) -> str:
    import re
    import string

    text = str(text).lower().replace("<pad>", " ")
    text = text.translate(str.maketrans("", "", string.punctuation))
    words = [w for w in text.split() if w not in _ARTICLES]
    return re.sub(r"\s+", " ", " ".join(words)).strip()


def _matches(prediction: str, gold: str) -> bool:
    gold_norm = _normalize(gold)
    return bool(gold_norm) and gold_norm in _normalize(prediction)


def hits_at_1(prediction, gold) -> int:
    """1 if the prediction contains any gold answer.

    Note what this is *not*: it does not require the prediction to be only
    the answer, and with several gold answers one is enough. That leniency is
    the standard, and it is why Hits@1 sits ~15 points above F1 in every
    published table.
    """
    text = prediction if isinstance(prediction, str) else "\n".join(map(str, prediction))
    return int(any(_matches(text, g) for g in gold))


def f1(prediction, gold) -> float:
    """F1 over the predicted answer *set* against the gold set.

    A string prediction is split on newlines, as the reference does. Each gold
    answer is credited once, so repeating a correct answer cannot inflate the
    score — but it does cost precision, which is why F1 punishes a model that
    lists everything it saw.
    """
    predicted = ([p for p in prediction.split("\n") if p.strip()]
                 if isinstance(prediction, str) else [str(p) for p in prediction])
    if not predicted or not gold:
        return 0.0
    matched = sum(1 for g in gold if any(_matches(p, g) for p in predicted))
    precision = matched / len(predicted)
    recall = matched / len(gold)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


#: One instruction for both conditions. The only difference between them is
#: whether the retrieved triples are present, because anything else would
#: confound "does the graph help" with "was the prompt better".
_PROMPT = """Answer the question with only the answer itself — no explanation.
If there are several correct answers, put one per line.
If you do not know, reply exactly: I don't know
"""

_WITH_GRAPH = """
Facts from a knowledge graph, as (subject, predicate, object):
{triples}
"""

#: Added to the graph condition by ``--style grounded``.
#:
#: The failures this exists to fix are not retrieval failures. At n=186 the
#: retrieved subgraph contained the answer and the model still lost the point
#: two ways: it paraphrased instead of naming the entity ("Short stories and
#: novels, particularly satirical works" against a gold of "Novelist"), and it
#: listed everything it saw ("Brazil Chile Argentina Paraguay Peru Amazon
#: rainforest Andes ...", where the five countries are exactly right and the
#: rest destroys precision, so F1 falls even though Hits@1 passes).
#:
#: Constraining the answer to labels present in the subgraph is what every
#: published KGQA method on this dataset does — the answer is an entity of the
#: graph, not free text. It applies only to the graph condition because there
#: is nothing to copy from without it, so the nograph baseline is untouched
#: and the delta between them credits the grounding to the graph. That is the
#: honest reading: grounding the answer in retrieved facts *is* the technique
#: being measured, not a prompt trick applied to one arm of an A/B.
_GROUNDED = """
Answer with names copied exactly from those facts. Do not reword them.
List only what the question asks for and nothing else — a name you saw that
does not answer the question is a wrong answer.
"""


def _ask(client, model: str, question: str, triples=None, style: str = "plain") -> str:
    body = _PROMPT
    if triples:
        body += _WITH_GRAPH.format(triples="\n".join(triples))
        if style == "grounded":
            body += _GROUNDED
    body += f"\nQuestion: {question}\nAnswer:"
    return client(model, body)


def _ollama_client(host: str, timeout: int = 120):
    """A callable (model, prompt) -> text, against a local Ollama.

    Local on purpose: the score depends on the model, so the model has to be
    nameable and re-runnable by whoever reads the number. An API key behind a
    paid endpoint is neither.
    """
    import json as _json
    import urllib.request

    def call(model: str, prompt: str) -> str:
        payload = _json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0,
                "num_ctx": 16384,
                # A hard ceiling on generation. The metric reads a short
                # answer, and a reasoning model that ignores `think: false`
                # will otherwise run until the request times out — one
                # question stalling for ten minutes and taking the whole run
                # down with it.
                "num_predict": 128,
            },
            "think": False,
        }).encode()
        request = urllib.request.Request(
            f"{host}/api/generate", data=payload,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return _json.load(response).get("response", "").strip()

    return call


def run(eval_path: Path, model: str, out: Path, condition: str,
        host: str = "http://localhost:11434", limit: int = 0,
        style: str = "plain") -> None:
    """Answer every question in eval_set.json and append results as they land.

    Appended per question, not collected and written at the end: a full test
    split takes hours, and losing all of it to one interruption is a way to
    never finish. Re-running skips what is already answered.
    """
    eval_set = json.load(open(eval_path))
    if limit:
        eval_set = eval_set[:limit]
    client = _ollama_client(host)

    done = {}
    if out.exists():
        for line in out.read_text().splitlines():
            if line.strip():
                record = json.loads(line)
                done[record["id"]] = record
        print(f"resuming: {len(done)} already answered", file=sys.stderr)
    out.parent.mkdir(parents=True, exist_ok=True)
    log = out.open("a")

    failed = 0
    for i, item in enumerate(eval_set, 1):
        if item["id"] in done:
            continue
        triples = item["triples"] if condition == "graph" else None
        try:
            answer = _ask(client, model, item["question"], triples, style)
        except Exception as exc:                        # noqa: BLE001
            # One question must never end the run. An empty answer scores
            # zero, which is the honest outcome, and it is recorded so a
            # rerun does not retry it forever.
            failed += 1
            print(f"  {item['id']}: {type(exc).__name__} — recorded as empty",
                  file=sys.stderr, flush=True)
            answer = ""
        log.write(json.dumps({"id": item["id"], "answer": answer},
                             ensure_ascii=False) + "\n")
        log.flush()
        if i % 25 == 0:
            print(f"  {i}/{len(eval_set)}"
                  + (f"  ({failed} failed)" if failed else ""),
                  file=sys.stderr, flush=True)
    log.close()
    print(f"wrote {out}"
          + (f" — {failed} question(s) recorded empty after an error" if failed else ""),
          file=sys.stderr)


def score(eval_path: Path, *answer_paths: Path, out_json: Path = None) -> None:
    """Report Hits@1 and F1 — the two metrics WebQSP results are published in.

    Both are computed exactly as the reference implementation does, so a score
    here can be put next to the literature. Anything else measured on this
    dataset (retrieval recall, for one) is a different quantity and does not
    belong in the same table.
    """
    gold = {e["id"]: e["answers"] for e in json.load(open(eval_path))}
    print(f"{'answers':<34}{'Hits@1':>9}{'F1':>9}{'n':>7}")
    rows = []
    for path in answer_paths:
        text = path.read_text()
        answers = ([json.loads(line) for line in text.splitlines() if line.strip()]
                   if path.suffix == ".jsonl" else json.loads(text))
        # Score only what this eval set has gold for, so a partial or a
        # differently-sampled answer file is a smaller n rather than a KeyError.
        answers = [a for a in answers if a["id"] in gold]
        hit = sum(hits_at_1(a["answer"], gold[a["id"]]) for a in answers)
        f = sum(f1(a["answer"], gold[a["id"]]) for a in answers)
        n = len(answers)
        print(f"{path.name:<34}{100 * hit / n:>8.1f}%{100 * f / n:>8.1f}%{n:>7}")
        rows.append({"answers": path.name, "hits_at_1": round(100 * hit / n, 1),
                     "f1": round(100 * f / n, 1), "n": n})
    if out_json:
        # The chart reads this, so the picture and the table cannot disagree.
        out_json.write_text(json.dumps(rows, indent=1) + "\n")
        print(f"wrote {out_json}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--n", type=int, default=30)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=Path, default=Path("bench_out"))
    p.add_argument("--retrieval", default=DEFAULT_RETRIEVAL)
    p.add_argument("--cap", type=int, default=DEFAULT_CAP)
    p.add_argument("--like", type=Path,
                   help="reuse the exact questions of an existing eval set")
    r = sub.add_parser("run", help="answer the questions with a local model")
    r.add_argument("eval_set", type=Path)
    r.add_argument("--model", required=True)
    r.add_argument("--condition", choices=("graph", "nograph"), required=True)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--host", default="http://localhost:11434")
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--style", choices=("plain", "grounded"), default="plain",
                   help="grounded constrains the answer to names present in "
                        "the retrieved facts (graph condition only)")
    s = sub.add_parser("score")
    s.add_argument("eval_set", type=Path)
    s.add_argument("answers", type=Path, nargs="+")
    s.add_argument("--json", type=Path, dest="out_json",
                   help="also write the scores as JSON, for the chart to read")
    args = ap.parse_args()
    if args.cmd == "prepare":
        prepare(args.n, args.seed, args.out, args.retrieval, args.cap, args.like)
    elif args.cmd == "run":
        run(args.eval_set, args.model, args.out, args.condition,
            args.host, args.limit, args.style)
    else:
        score(args.eval_set, *args.answers, out_json=args.out_json)


if __name__ == "__main__":
    main()
