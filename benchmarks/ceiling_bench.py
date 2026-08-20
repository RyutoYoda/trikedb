"""Where does each operation stop being pleasant?

The size a graph *fits* in is not the interesting number — a document-shaped
graph runs into GitHub's file limits somewhere around 870k triples, which no
curated graph reaches. What you actually hit is one feature at a time getting
slow, and they do not degrade together: semantic search is unusable while
SPARQL is still instant.

Emits JSON on stdout so the chart in this directory can be regenerated:

    python benchmarks/ceiling_bench.py > benchmarks/ceiling_data.json
    python benchmarks/ceiling_chart.py
"""

from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

from trikedb import TrikeDB

SIZES = [1_000, 3_000, 10_000, 30_000, 100_000, 300_000]

TWO_HOP = "SELECT ?v ?t WHERE { ?v t:PROVIDES ?j . ?j t:INGESTS_TO ?t }"


def build(n: int) -> TrikeDB:
    db = TrikeDB(autosave=False)
    for i in range(n // 3):
        vendor = f"vendor{i % (n // 30 or 1)}"
        job = f"job{i}"
        table = f"TABLE_{i % (n // 15 or 1)}"
        db.add(vendor, "PROVIDES", job)
        attrs = ({"note": f"batch {i} loads nightly overnight", "prov": "runbook.md"}
                 if i % 3 == 0 else {})
        db.add(job, "INGESTS_TO", table, **attrs)
        if i % 5 == 0:
            db.add(table, "FLOWS_TO", f"MART_{i % 40}")
    return db


def median_ms(fn, reps: int = 3) -> float:
    runs = []
    for _ in range(reps):
        start = time.perf_counter()
        fn()
        runs.append((time.perf_counter() - start) * 1000)
    return statistics.median(runs)


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    rows = []
    for n in SIZES:
        db = build(n)
        total = len(db)
        json_path, yaml_path = tmp / f"g{n}.json", tmp / f"g{n}.yaml"
        db.save(json_path)
        db.save(yaml_path)

        row = {
            "triples": total,
            "open_json": median_ms(lambda: TrikeDB(json_path)),
            "open_yaml": median_ms(lambda: TrikeDB(yaml_path)),
            "save_yaml": median_ms(lambda: db.save(yaml_path)),
            "yaml_mb": round(yaml_path.stat().st_size / 1e6, 2),
        }

        loaded = TrikeDB(json_path)
        loaded.sparql(TWO_HOP)                  # build the query graph first
        row["sparql_2hop"] = median_ms(lambda: loaded.sparql(TWO_HOP))

        html_path = tmp / f"g{n}.html"
        loaded.to_html(html_path)                # warm: the first call pays once
        row["to_html"] = median_ms(lambda: loaded.to_html(html_path), 1)
        row["html_mb"] = round(html_path.stat().st_size / 1e6, 2)

        try:                                     # [semantic] extra
            loaded.search("nightly batch load", k=5)   # warm the model
            row["search"] = median_ms(lambda: loaded.search("nightly batch load", k=5), 1)
        except ImportError:
            row["search"] = None

        rows.append(row)
        print(f"  {total:>8,} done", file=sys.stderr)

    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
