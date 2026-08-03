"""triplite command-line interface."""

from __future__ import annotations

import argparse
import json
import sys

from .db import TripLite


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="triplite",
        description="A knowledge graph in a single YAML file.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_query = sub.add_parser("query", help="match graph patterns with ?variables")
    p_query.add_argument("file")
    p_query.add_argument(
        "-w", "--where", action="append", required=True, metavar="'?s PRED ?o'",
        help="pattern of 3 terms; repeat -w to join patterns on shared variables",
    )
    p_query.add_argument("--json", action="store_true", help="output JSON instead of a table")

    p_add = sub.add_parser("add", help="add a triple")
    p_add.add_argument("file")
    p_add.add_argument("s")
    p_add.add_argument("p")
    p_add.add_argument("o")
    p_add.add_argument(
        "-a", "--attr", action="append", default=[], metavar="key=value",
        help="attach an attribute to the triple",
    )

    p_rm = sub.add_parser("rm", help="remove triples matching a pattern")
    p_rm.add_argument("file")
    p_rm.add_argument("-s", default=None)
    p_rm.add_argument("-p", default=None)
    p_rm.add_argument("-o", default=None)

    p_sparql = sub.add_parser(
        "sparql", help="run SPARQL 1.1 — SELECT/ASK to read, INSERT/DELETE to write"
    )
    p_sparql.add_argument("file")
    p_sparql.add_argument("query", help="SPARQL query or update; prefix t: is pre-bound, e.g. t:PROVIDES")
    p_sparql.add_argument("--json", action="store_true", help="output JSON instead of a table")

    p_stats = sub.add_parser("stats", help="summarize the graph")
    p_stats.add_argument("file")

    p_html = sub.add_parser("html", help="export an interactive HTML visualization")
    p_html.add_argument("file")
    p_html.add_argument("-o", "--out", default=None)
    p_html.add_argument("--title", default=None)

    p_jsonld = sub.add_parser("jsonld", help="export JSON-LD to stdout")
    p_jsonld.add_argument("file")

    args = parser.parse_args(argv)
    return _COMMANDS[args.command](args)


def _print_rows(rows, as_json: bool) -> int:
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("(no matches)", file=sys.stderr)
        return 1
    cols = list(rows[0].keys())
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    print("  ".join(c.ljust(widths[c]) for c in cols))
    print("  ".join("-" * widths[c] for c in cols))
    for r in rows:
        print("  ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols))
    return 0


def _cmd_query(args) -> int:
    db = TripLite(args.file)
    return _print_rows(db.query(args.where), args.json)


def _cmd_sparql(args) -> int:
    db = TripLite(args.file)
    result = db.sparql(args.query)
    if isinstance(result, bool):
        print(json.dumps(result) if args.json else ("yes" if result else "no"))
        return 0 if result else 1
    if isinstance(result, int):  # update form: store changed, persist it
        db.save()
        print(f"{result:+d} triple(s) — {len(db)} total")
        return 0
    return _print_rows(result, args.json)


def _cmd_add(args) -> int:
    attrs = {}
    for pair in args.attr:
        if "=" not in pair:
            print(f"error: --attr expects key=value, got {pair!r}", file=sys.stderr)
            return 2
        k, v = pair.split("=", 1)
        attrs[k] = v
    db = TripLite(args.file)
    db.add(args.s, args.p, args.o, **attrs)
    db.save()
    print(f"added ({args.s}, {args.p}, {args.o}) — {len(db)} triples total")
    return 0


def _cmd_rm(args) -> int:
    if args.s is None and args.p is None and args.o is None:
        print("error: give at least one of -s / -p / -o", file=sys.stderr)
        return 2
    db = TripLite(args.file)
    removed = db.remove(s=args.s, p=args.p, o=args.o)
    db.save()
    print(f"removed {removed} triple(s) — {len(db)} remaining")
    return 0


def _cmd_stats(args) -> int:
    db = TripLite(args.file)
    print(db)
    print(f"nodes: {len(db.nodes())}")
    for p in db.predicates():
        count = sum(1 for _ in db.triples(p=p))
        desc = db.ontology.get(p, "")
        print(f"  {p}: {count}" + (f"  — {desc}" if desc else ""))
    return 0


def _cmd_html(args) -> int:
    db = TripLite(args.file)
    out = args.out or args.file.rsplit(".", 1)[0] + ".html"
    title = args.title or f"triplite — {args.file}"
    db.to_html(out, title=title)
    print(f"wrote {out}")
    return 0


def _cmd_jsonld(args) -> int:
    db = TripLite(args.file)
    print(json.dumps(db.to_jsonld(), ensure_ascii=False, indent=2))
    return 0


_COMMANDS = {
    "query": _cmd_query,
    "sparql": _cmd_sparql,
    "add": _cmd_add,
    "rm": _cmd_rm,
    "stats": _cmd_stats,
    "html": _cmd_html,
    "jsonld": _cmd_jsonld,
}


if __name__ == "__main__":
    raise SystemExit(main())
