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
uv run --with pandas --with pyarrow --with trikedb \
    python benchmarks/webqsp_bench.py prepare --n 30 --seed 42
# ... run the prompt files through your LLM, save answers_*.json ...
uv run --with trikedb python benchmarks/webqsp_bench.py score \
    eval_set.json answers_nograph.json answers_graph.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PARQUET_URL = (
    "https://huggingface.co/datasets/rmanluo/RoG-webqsp/resolve/main/"
    "data/test-00000-of-00002-9ee8d68f7d951e1f.parquet"
)
CTX_CAP = 250


def _is_cvt(x: str) -> bool:
    return x.startswith("m.") or x.startswith("g.")


def prepare(n: int, seed: int, out: Path) -> None:
    import pandas as pd

    from trikedb import TrikeDB

    df = pd.read_parquet(PARQUET_URL)
    rows = df.sample(n, random_state=seed).to_dict("records")

    eval_set = []
    for r in rows:
        db = TrikeDB()
        for s, p, o in r["graph"]:
            db.add(str(s), str(p), str(o))
        ctx = []
        for e in list(r["q_entity"]):
            hop1 = list(db.triples(s=str(e))) + list(db.triples(o=str(e)))
            ctx += hop1
            for t in hop1:  # CVT nodes carry no names — always expand them
                for mid in (t.o, t.s):
                    if _is_cvt(mid):
                        ctx += list(db.triples(s=mid))
        seen, uniq = set(), []
        for t in ctx:
            if t.spo() not in seen:
                seen.add(t.spo())
                uniq.append(t)
        uniq = uniq[:CTX_CAP]
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
    print(f"prepared {len(eval_set)} questions -> {out}/")
    print(f"retrieval ceiling: answer present in context for {reachable}/{len(eval_set)}")


def score(eval_path: Path, *answer_paths: Path) -> None:
    gold = {e["id"]: e["answers"] for e in json.load(open(eval_path))}
    for path in answer_paths:
        answers = json.load(open(path))
        hits = 0
        for a in answers:
            g = gold[a["id"]]
            hits += any(
                x.lower() in a["answer"].lower() or a["answer"].lower() in x.lower()
                for x in g if len(x) > 2
            )
        print(f"{path}: {hits}/{len(answers)} ({hits / len(answers):.0%})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--n", type=int, default=30)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=Path, default=Path("bench_out"))
    s = sub.add_parser("score")
    s.add_argument("eval_set", type=Path)
    s.add_argument("answers", type=Path, nargs="+")
    args = ap.parse_args()
    if args.cmd == "prepare":
        prepare(args.n, args.seed, args.out)
    else:
        score(args.eval_set, *args.answers)


if __name__ == "__main__":
    main()
