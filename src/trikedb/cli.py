"""trikedb command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .db import OntologyError, TrikeDB
from .storage import ConcurrentWriteError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        # whichever name it was invoked as: the usage line saying "trikedb"
        # after someone typed "trike" is a small lie that costs a retype
        prog=Path(sys.argv[0]).name or "trikedb",
        description="A knowledge graph in a single YAML file.",
    )
    # metavar keeps the usage line from becoming a wall of command names
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p_init = sub.add_parser(
        "init",
        help="write a starting graph, so the first thing you see is not an empty file",
    )
    p_init.add_argument("file", nargs="?", help="where to write it, e.g. graph.yaml")
    p_init.add_argument(
        "-t", "--template", default="agent-memory", metavar="NAME",
        help="which starting graph to write (default: agent-memory). "
             "Use --list to see them all",
    )
    p_init.add_argument(
        "--list", dest="list_only", action="store_true",
        help="list the available templates and exit",
    )
    p_init.add_argument(
        "-f", "--force", action="store_true",
        help="overwrite the file if it already exists",
    )

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

    p_act = sub.add_parser(
        "act", help="record something you did, and move the node to its new state"
    )
    p_act.add_argument("file")
    p_act.add_argument("s", help="the node it happened to")
    p_act.add_argument("p")
    p_act.add_argument("o", help="what happened, in words")
    p_act.add_argument("--state", default=None,
                       help="the state it leaves the node in")
    p_act.add_argument("--by", default=None, help="who did it")
    p_act.add_argument("--at", default=None, help="when (default: now)")
    p_act.add_argument(
        "-a", "--attr", action="append", default=[], metavar="key=value",
        help="attach a further attribute to the event",
    )

    p_hist = sub.add_parser(
        "history", help="what happened to a node, newest first"
    )
    p_hist.add_argument("file")
    p_hist.add_argument("name")

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

    p_search = sub.add_parser(
        "search", help="semantic search — rank facts by meaning, not spelling ([semantic] extra)"
    )
    p_search.add_argument("file")
    p_search.add_argument("query", help='natural-language query, e.g. "認証まわりの注意点"')
    p_search.add_argument("-k", type=int, default=10, help="max results (default 10)")
    p_search.add_argument("--model", default=None, help="model2vec model name override")
    p_search.add_argument("--json", action="store_true", help="output JSON instead of a table")

    p_find = sub.add_parser(
        "find", help="semantic recall, then filter on node properties ([semantic] extra)"
    )
    p_find.add_argument("file")
    p_find.add_argument("query", help='natural-language question, e.g. "CRMを同期しているのは何？"')
    p_find.add_argument(
        "-w", "--where", action="append", default=[], metavar="key=value",
        help="keep only nodes whose properties match exactly; repeat to add conditions",
    )
    p_find.add_argument("-k", type=int, default=10, help="max results (default 10)")
    p_find.add_argument("--model", default=None, help="model2vec model name override")
    p_find.add_argument("--json", action="store_true", help="output JSON instead of a table")

    p_import = sub.add_parser(
        "import", help="merge triples from CSV/TSV, Markdown tables, or another YAML graph"
    )
    p_import.add_argument("file", help="the graph YAML to merge into (created if missing)")
    p_import.add_argument("sources", nargs="+", help=".csv/.tsv/.md/.yaml files to import")
    p_import.add_argument(
        "-n", "--dry-run", action="store_true",
        help="say what each row would do (new/same/update/conflict/rejected) "
             "and write nothing; exits 1 if anything is blocked",
    )
    p_import.add_argument("--json", action="store_true",
                          help="with --dry-run, output the findings as JSON")

    p_extract = sub.add_parser(
        "extract",
        help="print the extraction prompt for a document, built from this "
             "graph's own predicates and nodes",
    )
    p_extract.add_argument(
        "file", help="the graph whose vocabulary constrains the extraction")
    p_extract.add_argument("document", help="the document to extract from")
    p_extract.add_argument("-o", "--out", default=None,
                           help="write the prompt here instead of stdout")
    p_extract.add_argument(
        "--relevant-to", default=None, metavar="TEXT",
        help="offer only the nodes this text recalls, rather than the first "
             "--limit of them ([semantic] extra). Describe the document.",
    )
    p_extract.add_argument(
        "--limit", type=int, default=None, metavar="N",
        help="how many existing node names to offer (default 200)",
    )

    p_node = sub.add_parser(
        "node", help="show a node (props + edges), or set properties with -a"
    )
    p_node.add_argument("file")
    p_node.add_argument("name")
    p_node.add_argument(
        "-a", "--attr", action="append", default=[], metavar="key=value",
        help="set node properties; conventional keys: label, type, url, description, level",
    )
    p_node.add_argument(
        "--replace", action="store_true",
        help="allow changing the node's existing type (refused by default)",
    )

    p_onto = sub.add_parser(
        "ontology", help="show the predicate vocabulary, or extend it with --set"
    )
    p_onto.add_argument("file")
    p_onto.add_argument(
        "--set", action="append", default=[], metavar="PRED=description",
        help="add or update a predicate (a schema change — review it like one)",
    )
    p_onto.add_argument(
        "--link", action="append", default=[], metavar="PRED=domain>range",
        help="declare what a predicate connects, and have it enforced "
             "(INGESTS_TO=job>table). Either side may be blank or a|b.",
    )

    p_stats = sub.add_parser("stats", help="summarize the graph")
    p_stats.add_argument("file")

    # superseded by `ui generate`; kept working so pipelines that already
    # spell it out do not break, but no longer advertised
    p_html = sub.add_parser("html")
    p_html.add_argument("file", nargs="?", default=None,
                        help="graph file; omit it to pick up the one in this directory")
    p_html.add_argument("-o", "--out", default=None)
    p_html.add_argument("--title", default=None)
    p_html.add_argument(
        "--events", default=None, metavar="PRED1,PRED2",
        help="comma-separated predicates to treat as change events, attached "
             "to the node each one happened to (default: auto-detect — "
             "predicates whose triples carry a time attribute such as at:/when:, "
             "or whose objects open with a date)",
    )
    p_html.add_argument(
        "--layout", default="auto", choices=["auto", "flow", "free"],
        help="initial layout: flow (hierarchical), free (force-directed), "
             "auto (flow up to 150 triples)",
    )

    p_ui = sub.add_parser(
        "ui", help="open the graph in a browser; `ui generate` writes the file instead"
    )
    p_ui.add_argument(
        "target", nargs="*", metavar="[generate] [FILE]",
        help="`trike ui` opens the graph in this directory; `trike ui FILE` opens "
             "that one; `trike ui generate [FILE] -o out.html` writes the page "
             "instead of opening it",
    )
    p_ui.add_argument("-o", "--out", default=None, help="output path for `ui generate`")
    p_ui.add_argument("--title", default=None)
    p_ui.add_argument(
        "--events", default=None, metavar="PRED1,PRED2",
        help="comma-separated predicates to treat as change events",
    )
    p_ui.add_argument(
        "--layout", default="auto", choices=["auto", "flow", "free"],
        help="initial layout: flow (hierarchical), free (force-directed), auto",
    )

    sub._choices_actions = [a for a in sub._choices_actions if a.dest != "html"]

    p_jsonld = sub.add_parser("jsonld", help="export JSON-LD to stdout")
    p_jsonld.add_argument("file")

    p_validate = sub.add_parser(
        "validate", help="validate the graph against SHACL shapes (requires trikedb[shacl])"
    )
    p_validate.add_argument("file")
    p_validate.add_argument("shapes", help="path to a Turtle (.ttl) shapes file")

    p_infer = sub.add_parser(
        "infer", help="materialize OWL-RL inferences (requires trikedb[owl])"
    )
    p_infer.add_argument("file")
    p_infer.add_argument(
        "--apply", action="store_true",
        help="add the inferred triples to the graph (marked inferred: true) and save",
    )

    p_check = sub.add_parser(
        "check", help="CI check: graph parses and a generated HTML is up to date"
    )
    p_check.add_argument("file")
    p_check.add_argument("--html", default=None, help="generated HTML to verify against the graph")

    p_audit = sub.add_parser(
        "audit", help="health findings for a growing graph (dupes, name collisions, orphans)"
    )
    p_audit.add_argument("file")
    p_audit.add_argument("--json", action="store_true")
    p_audit.add_argument("--strict", action="store_true", help="warnings also fail (exit 1)")

    p_mcp = sub.add_parser(
        "mcp", help="serve the graph as an MCP server (stdio) — an ontology layer for AI agents"
    )
    p_mcp.add_argument("file")

    p_serve = sub.add_parser(
        "serve",
        help="serve UI + REST + remote MCP over HTTP (requires trikedb[serve])",
    )
    p_serve.add_argument("file", help="graph YAML, s3:// URL, or workspace file")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument(
        "--token", default=None,
        help="require 'Authorization: Bearer <token>' on every request",
    )
    p_serve.add_argument(
        "--oauth-issuer", default=None,
        help="OAuth 2.1 via your IdP (e.g. https://idp.example.com/) — what "
             "claude.ai and the ChatGPT UI speak. Requires --public-url",
    )
    p_serve.add_argument(
        "--public-url", default=None,
        help="the public HTTPS base URL clients reach this server at. Required "
             "behind a proxy or tunnel (the Host header is checked), and tokens "
             "are bound to <public-url>/mcp as their audience",
    )
    p_serve.add_argument(
        "--oauth-audience", default=None,
        help="override the expected 'aud' claim (default: <public-url>/mcp)",
    )
    p_serve.add_argument(
        "--required-scope", action="append", default=None, metavar="SCOPE",
        help="scope a token must carry; repeat for several",
    )
    p_serve.add_argument(
        "--actor-claim", default=None, metavar="CLAIM",
        help="JWT claim naming who is calling (default: sub). Under OAuth, "
             "actions written through /mcp are signed with this identity and "
             "a caller cannot pass somebody else's name as by=",
    )
    p_serve.add_argument(
        "--stateless", action="store_true",
        help="serve each MCP request independently, with no session to carry. "
             "Needed for clients that don't echo Mcp-Session-Id back, and for "
             "running more than one replica behind a load balancer",
    )

    p_sql_init = sub.add_parser(
        "sql-init",
        help="create the table a warehouse-backed graph URL needs "
             "(requires trikedb[snowflake])",
    )
    p_sql_init.add_argument(
        "url", help="e.g. snowflake://MYDB.PUBLIC.TRIKE_GRAPHS/sales/crm"
    )
    p_sql_init.add_argument(
        "--print", dest="print_only", action="store_true",
        help="print the DDL instead of running it, to review or hand to a DBA",
    )
    p_sql_init.add_argument(
        "--no-views", action="store_true",
        help="create only the table, without the KG_NODE / KG_EDGE / "
             "KG_PREDICATE / KG_TRIPLE views that make the graph queryable "
             "from SQL",
    )

    args = parser.parse_args(argv)
    try:
        return _COMMANDS[args.command](args)
    except (OntologyError, ValueError, SyntaxError, OSError,
            ConcurrentWriteError) as exc:
        # A rejected predicate, a query that does not parse, a member graph
        # that is not where the workspace says it is — every one of these is
        # the graph or the input being wrong, and a traceback reads like
        # trikedb broke instead. Anything not listed here is a bug in
        # trikedb, and for those the traceback is the useful answer.
        raise SystemExit(f"error: {exc}")


def _cmd_init(args) -> int:
    """Write a starting graph.

    The blank page is the real barrier to adopting a knowledge graph —
    `triples: []` says nothing about what belongs in it. Each template is
    a complete small graph of a shape people actually build, meant to be
    edited down and replaced.
    """
    from . import templates

    if args.list_only:
        width = max(len(n) for n in templates.names())
        for name in templates.names():
            print(f"{name.ljust(width)}  {templates.summary(name)}")
        return 0
    if not args.file:
        print("error: init needs a file to write, e.g. `trikedb init graph.yaml` "
              "(or --list to see the templates)", file=sys.stderr)
        return 2

    body = templates.render(args.template)
    path = Path(args.file)
    # Never quietly replace a graph somebody has been adding to: the file is
    # the database, so an overwrite here is the whole database.
    if path.exists() and not args.force:
        print(f"error: {path} already exists — pass --force to overwrite it",
              file=sys.stderr)
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")

    db = TrikeDB(str(path), autosave=False)
    print(f"wrote {path} — {len(db)} triples, {len(db.nodes())} nodes, "
          f"template {args.template!r}")
    print("next:")
    print(f"  trikedb stats {path}          # what is in it")
    print(f"  trikedb ui {path}             # look at it in a browser")
    print(f"  trikedb mcp {path}            # hand it to an agent (trikedb[mcp])")
    return 0


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
    db = TrikeDB(args.file)
    return _print_rows(db.query(args.where), args.json)


def _cmd_sparql(args) -> int:
    db = TrikeDB(args.file)
    result = db.sparql(args.query)
    if isinstance(result, bool):
        print(json.dumps(result) if args.json else ("yes" if result else "no"))
        return 0 if result else 1
    if isinstance(result, int):  # update form: store changed, persist it
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
        attrs[k] = _parse_attrs([pair])[k]
    db = TrikeDB(args.file)
    db.add(args.s, args.p, args.o, **attrs)
    print(f"added ({args.s}, {args.p}, {args.o}) — {len(db)} triples total")
    return 0


def _cmd_act(args) -> int:
    attrs = _parse_attrs(args.attr)
    db = TrikeDB(args.file)
    event = db.act(args.s, args.p, args.o, state=args.state, by=args.by,
                   at=args.at, **attrs)
    state = db.state(args.s)
    print(f"{args.s} {args.p} {args.o}  @ {event.when()}"
          + (f"\n{args.s} is now: {state}" if state else ""))
    return 0


def _cmd_history(args) -> int:
    db = TrikeDB(args.file)
    events = db.history(args.name)
    if not events:
        print(f"nothing recorded for {args.name!r}")
        return 0
    print(f"{args.name} — now: {db.state(args.name) or 'no state recorded'}")
    for t in events:
        who = t.attrs.get("by")
        state = t.attrs.get("state") or t.attrs.get("status")
        trail = "  ".join(x for x in (who and f"by {who}", state) if x)
        print(f"  {t.when()}  {t.o}" + (f"   ({trail})" if trail else ""))
    return 0


def _cmd_rm(args) -> int:
    if not args.s and not args.p and not args.o:
        print("error: give at least one of -s / -p / -o", file=sys.stderr)
        return 2
    db = TrikeDB(args.file)
    removed = db.remove(s=args.s, p=args.p, o=args.o)
    print(f"removed {removed} triple(s) — {len(db)} remaining")
    return 0


def _cmd_search(args) -> int:
    db = TrikeDB(args.file)
    try:
        rows = db.search(args.query, k=args.k, model=args.model)
    except ImportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        return _print_rows(rows, True)
    display = []
    for r in rows:
        if r["kind"] == "triple":
            attrs = {k: v for k, v in r.items() if k not in ("score", "kind", "s", "p", "o")}
            fact = f"{r['s']} {r['p']} {r['o']}"
            if attrs:
                fact += "  (" + ", ".join(f"{k}: {v}" for k, v in attrs.items()) + ")"
        else:
            props = {k: v for k, v in r.items() if k not in ("score", "kind", "node")}
            fact = f"{r['node']}  {{" + ", ".join(f"{k}: {v}" for k, v in props.items()) + "}"
        display.append({"score": r["score"], "kind": r["kind"], "fact": fact})
    return _print_rows(display, False)


def _cmd_import(args) -> int:
    if args.dry_run:
        return _preview_import(args)
    db = TrikeDB(args.file)
    added = 0
    for source in args.sources:
        n = db.import_file(source)
        added += n
        print(f"{source}: +{n}")
    db.save()
    print(f"added {added} triple(s) — {len(db)} total in {args.file}")
    return 0


def _preview_import(args) -> int:
    """`import --dry-run`: what the sources would do, without doing it."""
    from . import merge

    db = TrikeDB(args.file, read_only=True)
    report, blocked = {}, 0
    for source in args.sources:
        findings = db.preview(db.read_file(source))
        report[source] = findings
        blocked += len(merge.blocking(findings))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 1 if blocked else 0
    for source, findings in report.items():
        print(f"{source}: {len(findings)} row(s)")
        _print_findings(findings)
    print("nothing written" + (f" — {blocked} row(s) need a decision first"
                               if blocked else ""))
    return 1 if blocked else 0


def _print_findings(findings) -> None:
    from . import merge

    for verdict in merge.ORDER:
        for f in (x for x in findings if x["verdict"] == verdict):
            t = f["triple"]
            print(f"  {verdict:9} {t.get('s')} {t.get('p')} {t.get('o')}")
            # "new fact" says nothing the verdict did not; anything else a
            # new row has to say is the reason to look at it twice.
            if f["detail"] != "new fact":
                print(f"  {'':9} └ {f['detail']}")
    tally = merge.counts(findings)
    print("  " + (", ".join(f"{n} {v}" for v, n in tally.items()) or "no rows"))


def _cmd_extract(args) -> int:
    """Print the prompt. The model is yours; this is the part that is ours.

    Nothing here calls out to anything: the graph's declared predicates
    and existing node names go into a prompt, and the answer comes back
    through `import --dry-run` like any other source.
    """
    db = TrikeDB(args.file, read_only=True)
    kwargs = {"relevant_to": args.relevant_to}
    if args.limit is not None:
        kwargs["limit"] = args.limit
    prompt = db.extract_prompt(
        Path(args.document).read_text(encoding="utf-8"), **kwargs)
    if args.out:
        Path(args.out).write_text(prompt, encoding="utf-8")
        print(f"wrote {args.out} — send it to any model, save the table it "
              f"answers with, then: trikedb import {args.file} <table>.md --dry-run")
        return 0
    print(prompt)
    return 0


def _parse_attrs(pairs) -> dict:
    from .importers import _coerce

    attrs = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"error: expected key=value, got {pair!r}")
        k, v = pair.split("=", 1)
        attrs[k] = _coerce(v)
    return attrs


def _cmd_node(args) -> int:
    db = TrikeDB(args.file)
    if args.attr:
        db.set_node(args.name, replace=args.replace, **_parse_attrs(args.attr))
    record = {
        "name": args.name,
        # An unknown name and a node with nothing on it produce the same empty
        # record, and "no such node" is the answer people actually wanted.
        "exists": args.name in db.nodes(),
        "properties": db.node(args.name),
        "outgoing": [t.to_dict() for t in db.triples(s=args.name)],
        "incoming": [t.to_dict() for t in db.triples(o=args.name)],
    }
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0 if record["exists"] else 1


def _cmd_find(args) -> int:
    db = TrikeDB(args.file)
    where = _parse_attrs(args.where) if args.where else None
    try:
        hits = db.find(args.query, where=where, k=args.k, model=args.model)
    except ImportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        return _print_rows(hits, True)
    if not hits:
        print("no match")
        return 1
    for h in hits:
        print(h["node"])
        for k, v in (h.get("props") or {}).items():
            print(f"    {k}: {v}")
        for pred, obj in (h.get("facts") or []):
            print(f"    -> {pred} {obj}")
    return 0


def _cmd_ontology(args) -> int:
    db = TrikeDB(args.file)
    if args.set or args.link:
        for pair in args.set:
            pred, _, desc = pair.partition("=")
            db.ontology[pred.strip()] = desc.strip()
        for pair in args.link:
            pred, _, shape = pair.partition("=")
            domain, _, rng = shape.partition(">")
            db.declare_link(
                pred.strip(),
                domain=[t for t in domain.split("|") if t.strip()] or None,
                range=[t for t in rng.split("|") if t.strip()] or None,
            )
        db.save()
    shown = {p: ({"description": desc,
                  **{k: list(v) for k, v in db.predicate_rules[p].items()}}
                 if p in db.predicate_rules else desc)
             for p, desc in db.ontology.items()}
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    return 0


def _cmd_stats(args) -> int:
    db = TrikeDB(args.file)
    print(db)
    print(f"nodes: {len(db.nodes())}")
    for p in db.predicates():
        count = sum(1 for _ in db.triples(p=p))
        desc = db.ontology.get(p, "")
        print(f"  {p}: {count}" + (f"  — {desc}" if desc else ""))
    return 0


def _default_html_out(graph: str) -> str:
    """Where `trikedb html` writes when no -o is given.

    A local graph gets its sibling: `graph.yaml` -> `graph.html`. A URL has
    no sibling to speak of, and swapping the extension on one produced
    nonsense — `snowflake://DB.PUBLIC.TRIKE_GRAPHS/sales/crm` became
    `snowflake://DB.PUBLIC.html` — so the view lands in the working
    directory, named after the graph. The workbench is a rendering of the
    graph, not part of it; where the graph lives never decides where the
    page goes.
    """
    from .storage import is_remote

    if is_remote(graph):
        last = graph.rstrip("/").rsplit("/", 1)[-1]
        stem = last.rsplit(".", 1)[0] if "." in last else last
        return f"{stem or 'graph'}.html"
    return (graph.rsplit(".", 1)[0] if "." in graph else graph) + ".html"


def _is_workspace(path: Path) -> bool:
    """Does this file union other graphs? (a top-level `graphs:` key)"""
    try:
        head = path.read_text(errors="replace")[:65536]
    except OSError:
        return False
    return any(line.startswith(("graphs:", '"graphs":', "'graphs':"))
               for line in head.splitlines())


def _find_graph() -> str:
    """The graph in this directory, when the command was given no path.

    `trike ui` with nothing after it is the whole point of the short form,
    and in a repo that holds one graph there is nothing to disambiguate.

    A workspace is not a competing candidate — it is the union *of* the
    other files, so a directory of member graphs plus one workspace has an
    obvious answer. Only a genuine tie stops and says what it found.
    """
    here = Path(".")
    for conventional in ("workspace.yaml", "graph.yaml"):
        if (here / conventional).exists():
            return conventional
    found = sorted(p for ext in ("*.yaml", "*.yml") for p in here.glob(ext))
    if len(found) == 1:
        return str(found[0])
    unions = [p for p in found if _is_workspace(p)]
    if len(unions) == 1:
        return str(unions[0])
    if not found:
        raise SystemExit("error: no .yaml graph here — pass one: trike ui graph.yaml")
    listed = ", ".join(f"{p} (workspace)" if p in unions else str(p) for p in found)
    raise SystemExit("error: several graphs here, name one: " + listed)


def _cmd_ui(args) -> int:
    """Open the workbench, or write it out with `ui generate`.

    Two verbs under one noun, the way `dbt docs serve` and `dbt docs
    generate` split: the thing is the UI, and you either look at it or hand
    it to someone. When opening, the temp file is keyed by the graph's
    content hash, so opening the same unchanged graph twice reuses it
    instead of littering the temp directory.
    """
    import tempfile
    import webbrowser

    target = list(args.target)
    generate = bool(target) and target[0] == "generate"
    if generate:
        target = target[1:]
    if len(target) > 1:
        raise SystemExit(f"error: expected one graph, got {' '.join(target)}")
    path = (target[0] if target else None) or _find_graph()

    db = TrikeDB(path)
    events = None if args.events is None else [p.strip() for p in args.events.split(",") if p.strip()]
    title = args.title or f"trikedb — {path}"
    if generate:
        out = args.out or _default_html_out(path)
        db.to_html(out, title=title, event_predicates=events, layout=args.layout)
        print(f"wrote {out}")
        return 0
    if args.out:
        raise SystemExit("error: -o writes a file — did you mean `trike ui generate`?")
    out = Path(tempfile.gettempdir()) / f"trikedb-{db.content_hash()}.html"
    db.to_html(out, title=title, event_predicates=events, layout=args.layout)
    webbrowser.open(out.as_uri())
    print(f"opened {path} → {out}", file=sys.stderr)
    return 0


def _cmd_html(args) -> int:
    print("note: `trikedb html` is now `trike ui generate`", file=sys.stderr)
    args.file = args.file or _find_graph()
    db = TrikeDB(args.file)
    out = args.out or _default_html_out(args.file)
    title = args.title or f"trikedb — {args.file}"
    events = None if args.events is None else [p.strip() for p in args.events.split(",") if p.strip()]
    db.to_html(out, title=title, event_predicates=events, layout=args.layout)
    print(f"wrote {out}")
    return 0


def _cmd_jsonld(args) -> int:
    db = TrikeDB(args.file)
    print(json.dumps(db.to_jsonld(), ensure_ascii=False, indent=2))
    return 0


def _cmd_validate(args) -> int:
    db = TrikeDB(args.file)
    conforms, report = db.validate(args.shapes)
    print(report)
    return 0 if conforms else 1


def _cmd_infer(args) -> int:
    db = TrikeDB(args.file)
    new = db.infer(apply=args.apply)
    for s, p, o in new:
        print(f"+ ({s}, {p}, {o})")
    if args.apply and new:
        db.save()
    print(f"{len(new)} inferred triple(s)" + (" — applied and saved" if args.apply else ""))
    return 0


def _cmd_check(args) -> int:
    import re

    db = TrikeDB(args.file)
    print(f"parse OK: {db}")
    if args.html:
        # Through the storage layer: a workbench published to a bucket has to
        # be checkable the same way a local one is, or CI can only guard the
        # copies that happen to sit on disk.
        from . import storage

        if not storage.exists(args.html):
            print(f"stale: {args.html} does not exist — generate it", file=sys.stderr)
            return 1
        m = re.search(r"trikedb:hash:([0-9a-f]+)", storage.read_text(args.html))
        if not m:
            print(f"stale: {args.html} has no content hash (older trikedb?) — regenerate", file=sys.stderr)
            return 1
        if m.group(1) != db.content_hash():
            print(f"stale: {args.html} does not match the graph — regenerate", file=sys.stderr)
            return 1
        print(f"HTML up to date: {args.html}")
    return 0


def _cmd_audit(args) -> int:
    db = TrikeDB(args.file)
    findings = db.audit()
    if args.json:
        print(json.dumps(findings, ensure_ascii=False, indent=2))
    else:
        if not findings:
            print("clean: no findings")
        for f in findings:
            print(f"[{f['severity']}] {f['kind']}: {f['detail']}")
    errors = [f for f in findings if f["severity"] == "error"]
    if errors or (args.strict and findings):
        return 1
    return 0


def _cmd_mcp(args) -> int:
    from .mcp_server import serve

    serve(args.file)
    return 0


def _cmd_serve(args) -> int:
    from .serve import serve

    serve(
        args.file,
        host=args.host,
        port=args.port,
        token=args.token,
        oauth_issuer=args.oauth_issuer,
        public_url=args.public_url,
        oauth_audience=args.oauth_audience,
        required_scopes=args.required_scope,
        stateless=args.stateless,
        actor_claim=args.actor_claim,
    )
    return 0


def _cmd_sql_init(args) -> int:
    """Create the table, or show what would be created.

    Creating tables in a company-wide warehouse is not something a graph
    library should do behind someone's back, so it is an explicit command
    and --print exists for the case where only a DBA may run the DDL.
    """
    from . import storage_sql

    views = not args.no_views
    if args.print_only:
        print(storage_sql.ddl_for(args.url, views=views) + ";")
        return 0
    created = storage_sql.open_url(args.url).create_table(views=views)
    for name in created:
        print(f"ready: {name}", file=sys.stderr)
    return 0


_COMMANDS = {
    "init": _cmd_init,
    "query": _cmd_query,
    "sparql": _cmd_sparql,
    "search": _cmd_search,
    "find": _cmd_find,
    "import": _cmd_import,
    "extract": _cmd_extract,
    "add": _cmd_add,
    "act": _cmd_act,
    "history": _cmd_history,
    "rm": _cmd_rm,
    "node": _cmd_node,
    "ontology": _cmd_ontology,
    "stats": _cmd_stats,
    "html": _cmd_html,
    "ui": _cmd_ui,
    "jsonld": _cmd_jsonld,
    "check": _cmd_check,
    "audit": _cmd_audit,
    "validate": _cmd_validate,
    "infer": _cmd_infer,
    "mcp": _cmd_mcp,
    "serve": _cmd_serve,
    "sql-init": _cmd_sql_init,
}


if __name__ == "__main__":
    raise SystemExit(main())
