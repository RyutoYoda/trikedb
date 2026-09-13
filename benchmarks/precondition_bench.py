"""What a declared precondition costs as the graph grows.

`REVIEWED requires ["?order PLACED_BY ?s", "?order CONTAINS ?o"]` is the
expensive shape: two patterns joining through an order named by neither end
of the review, so the check cannot be answered by looking at the triple
being written. The claim under test is that it costs the same at 200,000
triples as at 1,000 — which is only true if the indexes are *extended* on
append rather than dropped and rebuilt.

    python benchmarks/precondition_bench.py [size ...]

A control predicate that declares nothing is measured alongside, because
the interesting number is the check, not the append it rides on.
"""
import sys
import time

from trikedb import TrikeDB

REPS = 200


def build(n):
    """n triples as order/customer/product trios, plus the two declarations."""
    db = TrikeDB(autosave=False)
    db.declare_link("PLACED_BY", description="order -> customer",
                    domain="order", range="customer")
    db.declare_link("CONTAINS", description="order -> product",
                    domain="order", range="product")
    db.declare_link("REVIEWED", description="customer -> product",
                    domain="customer", range="product",
                    requires=["?order PLACED_BY ?s", "?order CONTAINS ?o"])
    db.declare_link("NOTED", description="customer -> product")   # the control
    with db.batch():
        for i in range(n // 2):
            order, customer, product = "ORD-%d" % i, "C-%d" % i, "P-%d" % i
            db.set_node(order, type="order")
            db.set_node(customer, type="customer")
            db.set_node(product, type="product")
            db.add(order, "PLACED_BY", customer, at="2025-01-01")
            db.add(order, "CONTAINS", product, at="2025-01-01")
    return db


def per_write(db, predicate):
    """Seconds per accepted write of `predicate`, each one a new triple.

    Distinct `at` values on purpose: re-adding the same triple is an upsert
    that never reaches the check, and popping the triple back off would
    leave the index length mismatched and force a rebuild per iteration —
    a benchmark measuring the rebuild instead of the check.
    """
    i = len(db) // 4
    subject, obj = "C-%d" % i, "P-%d" % i
    start = time.perf_counter()
    for rep in range(REPS):
        db.add(subject, predicate, obj, at="2025-06-%02d" % (rep % 28 + 1),
               rating=rep)
    return (time.perf_counter() - start) / REPS


def main(sizes):
    print("%9s  %14s  %14s  %12s" % ("triples", "no rule", "2-step requires", "the check"))
    for n in sizes:
        db = build(n)
        size = len(db)
        control = per_write(db, "NOTED")
        checked = per_write(db, "REVIEWED")
        print("%9d  %11.1f µs  %11.1f µs  %9.1f µs"
              % (size, control * 1e6, checked * 1e6, (checked - control) * 1e6))


if __name__ == "__main__":
    main([int(a) for a in sys.argv[1:]] or [1_000, 10_000, 50_000, 200_000])
