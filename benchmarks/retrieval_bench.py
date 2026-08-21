"""Which retrieval method puts the answer in front of the model?

trikedb offers several ways to pull context out of a graph, and they are not
interchangeable: walking outward from the question's entity, joining patterns,
and ranking by meaning select genuinely different triples. This measures the
part that does not need an LLM — **does a gold answer end up in the retrieved
context, and what did it cost to get there** — with every method held to the
same context budget, so the comparison is about *selection* and not about who
was allowed to send more.

Reachability is a ceiling, not an accuracy: the KGQA experiment in README.md
found that making every answer reachable did *not* improve answers, because
the bottleneck moved to attention. So read this as "which method can put the
answer in the window", and read the accuracy numbers next to it.

Run:
    uv run --with pandas --with pyarrow python benchmarks/retrieval_bench.py \\
        --n 100 --seed 42 > benchmarks/retrieval_data.json

Add `--budget 250` to change the cap. The dataset is downloaded at runtime and
never stored in this repository.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

from trikedb import TrikeDB

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
    """The full 1,628-question test split as a DataFrame.

    RoG-WebQSP ships a pre-retrieved Freebase subgraph per question, so this
    measures retrieval *within* that subgraph — the same basis the RoG line of
    work reports on, and not retrieval from all of Freebase.
    """
    import pandas as pd

    return pd.concat([pd.read_parquet(BASE + s) for s in TEST_SHARDS],
                     ignore_index=True)


def _is_cvt(name: str) -> bool:
    """Freebase mediator nodes carry no readable name of their own, so a hop
    that lands on one has learned nothing until it is expanded."""
    return name.startswith(("m.", "g."))


def _dedupe(triples, budget):
    seen, out = set(), []
    for t in triples:
        if t.spo() not in seen:
            seen.add(t.spo())
            out.append(t)
            if len(out) >= budget:
                break
    return out


# --------------------------------------------------------------- the methods
# Each takes (db, question, entities, budget) and returns a list of Triples.

def one_hop(db, question, entities, budget):
    """Everything directly attached to the question's entity."""
    out = []
    for e in entities:
        out += list(db.triples(s=e)) + list(db.triples(o=e))
    return _dedupe(out, budget)


def one_hop_cvt(db, question, entities, budget):
    """1-hop, expanding mediator nodes — the method README.md reports."""
    out = []
    for e in entities:
        hop1 = list(db.triples(s=e)) + list(db.triples(o=e))
        out += hop1
        for t in hop1:
            for mid in (t.o, t.s):
                if _is_cvt(mid):
                    out += list(db.triples(s=mid))
    return _dedupe(out, budget)


def two_hop(db, question, entities, budget):
    """1-hop, then everything attached to whatever that reached."""
    out = []
    for e in entities:
        hop1 = list(db.triples(s=e)) + list(db.triples(o=e))
        out += hop1
        for t in hop1:
            for nxt in (t.o, t.s):
                if nxt not in entities:
                    out += list(db.triples(s=nxt))
    return _dedupe(out, budget)


def semantic(db, question, entities, budget):
    """Rank every fact by meaning against the question text.

    Entity-blind on purpose: this is the one method that does not start from
    the question's entity, so it is the honest test of whether meaning alone
    finds the right neighbourhood.
    """
    from trikedb.db import Triple

    # search() ranks both triples and nodes; only the triples are context.
    return _dedupe(
        [Triple(h["s"], h["p"], h["o"])
         for h in db.search(question, k=budget) if h.get("kind") == "triple"],
        budget,
    )


def hybrid(db, question, entities, budget):
    """Semantic recall anchored back onto the question's entity.

    Half the budget from the entity so the anchor is never lost, the rest
    ranked by meaning — the combination `find()` exists for.
    """
    anchored = one_hop_cvt(db, question, entities, budget // 2)
    ranked = semantic(db, question, entities, budget)
    return _dedupe(anchored + ranked, budget)


METHODS = {
    "1-hop": one_hop,
    "1-hop + CVT": one_hop_cvt,
    "2-hop": two_hop,
    "semantic search": semantic,
    "hybrid (entity + semantic)": hybrid,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=0,
                        help="questions to sample; 0 = the whole test split")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--budget", type=int, default=250)
    parser.add_argument("--checkpoint", type=Path,
                        default=Path("benchmarks/retrieval_progress.jsonl"),
                        help="per-question results, appended as they finish")
    args = parser.parse_args()

    df = load_test_split()
    rows = (df.to_dict("records") if args.n <= 0 or args.n >= len(df)
            else df.sample(args.n, random_state=args.seed).to_dict("records"))

    # A full-split run is over an hour, and it used to hold every result in
    # memory until the end — so a closed laptop, a killed session or one bad
    # question threw the lot away. Each question is appended as it finishes
    # and a rerun skips what is already there.
    done = {}
    if args.checkpoint.exists():
        for line in args.checkpoint.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                done[rec["id"]] = rec
        print(f"  resuming: {len(done)} questions already done", file=sys.stderr)
    args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
    log = args.checkpoint.open("a")

    graph_sizes = []

    for i, row in enumerate(rows, 1):
        if str(row["id"]) in done:
            rec = done[str(row["id"])]
            graph_sizes.append(rec["graph_triples"])
            continue
        db = TrikeDB(autosave=False)
        for s, p, o in row["graph"]:
            db.add(str(s), str(p), str(o))
        graph_sizes.append(len(db))
        question = row["question"]
        entities = [str(e) for e in row["q_entity"]]
        answers = [str(a).lower() for a in row["answer"]]

        record = {"id": str(row["id"]), "graph_triples": len(db), "methods": {}}
        for name, method in METHODS.items():
            start = time.perf_counter()
            try:
                context = method(db, question, entities, args.budget)
            except ImportError as exc:          # the [semantic] extra
                print(f"{name}: {exc}", file=sys.stderr)
                continue
            elapsed = (time.perf_counter() - start) * 1000
            blob = " ".join(f"{t.s} {t.p} {t.o}" for t in context).lower()
            record["methods"][name] = {
                "reached": any(a in blob for a in answers),
                "context": len(context),
                "ms": round(elapsed, 1),
            }
        log.write(json.dumps(record) + "\n")
        log.flush()                    # survive a kill, not just a clean exit
        done[record["id"]] = record
        if i % 10 == 0:
            print(f"  {i}/{len(rows)}", file=sys.stderr)

    log.close()
    answered = [done[str(r["id"])] for r in rows if str(r["id"]) in done]
    methods = []
    for name in METHODS:
        per = [q["methods"][name] for q in answered if name in q["methods"]]
        if not per:
            continue
        methods.append({
            "method": name,
            "reachable": sum(p["reached"] for p in per),
            "reachable_pct": round(100 * sum(p["reached"] for p in per) / len(per), 1),
            "median_context_triples": int(statistics.median(p["context"] for p in per)),
            "median_ms": round(statistics.median(p["ms"] for p in per), 1),
        })
    print(json.dumps({
        "dataset": "WebQSP (RoG repack), full test split",
        "test_split_size": len(df),
        "questions": len(answered),
        "budget": args.budget,
        "median_graph_triples": int(statistics.median(graph_sizes or [0])),
        "methods": methods,
    }, indent=2))


if __name__ == "__main__":
    main()
