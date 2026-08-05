"""Where does the single-file model stop being comfortable?

Synthesizes pipeline-shaped graphs (vendors -> jobs -> tables, with
notes/provenance on a third of the edges) at increasing sizes and times
the operations an agent or a human actually performs:

    load        TrikeDB(path)          — cost of "read the whole file"
    save        db.save()              — cost of one mutation with autosave
    query       2-hop pattern join     — db.query([...])
    sparql      2-hop SELECT via rdflib
    search      semantic search        — if the [semantic] extra is present
    html        db.to_html()           — workbench generation + file size

Run:  python benchmarks/scale_bench.py [sizes ...]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from trikedb import TrikeDB


def build(path: Path, n: int) -> None:
    db = TrikeDB(path, autosave=False)
    for i in range(n // 3):
        v, j, t = f"vendor{i % (n // 30 or 1)}", f"job{i}", f"TABLE_{i % (n // 15 or 1)}"
        db.add(v, "PROVIDES", j)
        attrs = {"note": f"batch {i} loads nightly", "prov": "bench"} if i % 3 == 0 else {}
        db.add(j, "INGESTS_TO", t, **attrs)
        if i % 5 == 0:
            db.add(t, "FLOWS_TO", f"MART_{i % 40}")
    db.save()


def clock(label: str, fn) -> float:
    t0 = time.perf_counter()
    fn()
    dt = time.perf_counter() - t0
    print(f"    {label}: {dt:.3f}s", file=sys.stderr, flush=True)
    return dt


def bench(n: int, tmp: Path) -> dict:
    print(f"== {n} triples", file=sys.stderr, flush=True)
    path = tmp / f"bench_{n}.yaml"
    build(path, n)
    row = {"triples": n, "file_kb": round(path.stat().st_size / 1024)}

    t0 = time.perf_counter()
    db = TrikeDB(path, autosave=False)
    row["load_s"] = round(time.perf_counter() - t0, 3)
    print(f"    load: {row['load_s']}s", file=sys.stderr, flush=True)
    row["triples"] = len(db)

    row["save_s"] = round(clock("save", db.save), 3)
    row["query_s"] = round(
        clock("query", lambda: db.query(["?v PROVIDES ?j", "?j INGESTS_TO ?t"])), 3
    )
    row["sparql_s"] = round(
        clock("sparql", lambda: db.sparql(
            "SELECT ?v ?t WHERE { ?v t:PROVIDES ?j . ?j t:INGESTS_TO ?t } LIMIT 5"
        )), 3
    )
    try:
        db.search("nightly batch loads", k=5)  # warm the model outside the clock
        row["search_s"] = round(clock("search", lambda: db.search("nightly batch loads", k=5)), 3)
    except ImportError:
        row["search_s"] = None

    out = tmp / f"bench_{n}.html"
    row["html_s"] = round(clock("html", lambda: db.to_html(out)), 3)
    row["html_mb"] = round(out.stat().st_size / 1024 / 1024, 1)
    return row


def main() -> None:
    sizes = [int(s.replace("_", "")) for s in sys.argv[1:]] or [1_000, 10_000, 100_000]
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        rows = [bench(n, Path(d)) for n in sizes]
    cols = list(rows[0])
    print("| " + " | ".join(cols) + " |")
    print("|" + "|".join("---" for _ in cols) + "|")
    for r in rows:
        print("| " + " | ".join(str(r[c]) for c in cols) + " |")


if __name__ == "__main__":
    main()
