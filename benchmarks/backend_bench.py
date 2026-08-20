"""Which backend, and what does it cost?

Times what a person or an agent actually does — open the graph, ask it
something, write one fact back — across every storage backend, at three
sizes. Microbenchmarks are easy to win and tell you nothing; these four
numbers are what you feel.

The interesting comparison is a warehouse row against a local file, because
that is the choice a team actually makes. The queries are deliberately
identical everywhere: they run in memory, so a backend cannot change them,
and seeing that in the numbers is half the point.

Run:
    python benchmarks/backend_bench.py                     # local files only
    VERIFY_TABLE=DB.SCHEMA.TABLE python benchmarks/backend_bench.py

`VERIFY_TABLE` adds a `snowflake://` row to the comparison; it needs
`trikedb[snowflake]` and connection settings in the environment (see the
reference). Rows are written under `bench/` and deleted at the end.
"""

from __future__ import annotations

import os
import statistics
import tempfile
import time
from pathlib import Path

from trikedb import TrikeDB

SIZES = [int(s) for s in os.environ.get("SIZES", "600,6000,60000").split(",")]
TABLE = os.environ.get("VERIFY_TABLE")

#: A 1-hop lookup, a 2-hop join, and a whole-graph aggregate — the three
#: shapes that behave differently as a graph grows.
ONE_HOP = "SELECT ?j WHERE { <urn:trikedb:vendor0> <urn:trikedb:PROVIDES> ?j }"
TWO_HOP = "SELECT ?v ?t WHERE { ?v t:PROVIDES ?j . ?j t:INGESTS_TO ?t }"
AGGREGATE = "SELECT (COUNT(?s) AS ?n) WHERE { ?s ?p ?o }"


def build(n: int) -> TrikeDB:
    """Pipeline-shaped: vendors -> jobs -> tables, a third of the edges
    carrying note/prov attributes, some tables described. Shaped like an
    operations graph rather than a uniform random one, because the attribute
    density is what makes the document big."""
    db = TrikeDB(autosave=False)
    for i in range(n // 3):
        vendor = f"vendor{i % (n // 30 or 1)}"
        job = f"job{i}"
        table = f"TABLE_{i % (n // 15 or 1)}"
        db.add(vendor, "PROVIDES", job)
        attrs = ({"note": f"batch {i} loads nightly", "prov": "runbook.md"}
                 if i % 3 == 0 else {})
        db.add(job, "INGESTS_TO", table, **attrs)
        if i % 5 == 0:
            db.add(table, "FLOWS_TO", f"MART_{i % 40}")
        if i % 7 == 0:
            db.set_node(table, type="table", pii=(i % 14 == 0), rows=i)
    return db


def median_ms(fn, reps: int = 3) -> float:
    """Median, not mean: one slow run (a warehouse resuming, a GC pause) says
    more about the machine than about the code."""
    runs = []
    for _ in range(reps):
        start = time.perf_counter()
        fn()
        runs.append((time.perf_counter() - start) * 1000)
    return statistics.median(runs)


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    header = (f"{'triples':>8} {'backend':<20} {'open':>9} {'1-hop':>8} "
              f"{'2-hop':>9} {'count':>8} {'+1 fact':>9}")
    print(header)
    print("-" * len(header))

    for n in SIZES:
        source = build(n)
        total = len(source)
        targets = [("local .yaml", tmp / f"g{n}.yaml"),
                   ("local .json", tmp / f"g{n}.json")]
        if TABLE:
            targets.append(("snowflake:// row", f"snowflake://{TABLE}/bench/g{n}"))

        for label, target in targets:
            source.save(target)
            TrikeDB(target)          # pay for any connection handshake first

            open_ms = median_ms(lambda: TrikeDB(target))
            db = TrikeDB(target)
            db.sparql(ONE_HOP)       # build the query graph once, as a server would
            one = median_ms(lambda: db.sparql(ONE_HOP), 5)
            two = median_ms(lambda: db.sparql(TWO_HOP))
            agg = median_ms(lambda: db.sparql(AGGREGATE))

            def one_write():
                writer = TrikeDB(target, autosave=False)
                writer.add("bench-writer", "WROTE", "value")
                writer.save()

            write_ms = median_ms(one_write)
            print(f"{total:>8,} {label:<20} {open_ms:8.1f}ms {one:7.2f}ms "
                  f"{two:8.1f}ms {agg:7.1f}ms {write_ms:8.1f}ms")
        print()

    print("SPARQL engine, warm (the graph is already built):")
    big = build(SIZES[-1])
    for engine in ("rdflib", "oxigraph"):
        db = TrikeDB(autosave=False, sparql_engine=engine)
        db._triples = list(big._triples)
        db.nodes_meta = dict(big.nodes_meta)
        db.sparql(ONE_HOP)
        print(f"  {engine:9} 1-hop {median_ms(lambda: db.sparql(ONE_HOP), 5):7.2f}ms"
              f"   2-hop {median_ms(lambda: db.sparql(TWO_HOP)):8.1f}ms"
              f"   count {median_ms(lambda: db.sparql(AGGREGATE)):7.1f}ms")

    if TABLE:
        from trikedb import storage_sql

        storage_sql.open_url(f"snowflake://{TABLE}/cleanup")._run(
            "DELETE FROM {table} WHERE name LIKE 'bench/%'", (), want_rows=False)
        print("\nremoved the bench/ rows")


if __name__ == "__main__":
    main()
