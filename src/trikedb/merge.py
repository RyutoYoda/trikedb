"""What incoming triples would do to the graph, before they do it.

Every write path — a hand-typed `add`, a CSV, an agent calling the MCP
server, an LLM extraction — ends at the same question: is this row new,
is it already here, or does it contradict something the graph already
says? Answering it *after* the write means reading a diff to find out
what you agreed to. Answering it here means the diff is the thing you
agreed to.

Contradiction is decidable rather than guessed, and that is the point of
having declared the ontology: a predicate declared `functional` may hold
one object per subject, so a second one is a conflict and not an
opinion. What the ontology does not declare, this does not invent — two
unrelated-looking facts are simply two facts.

The checks are the ones `TrikeDB.add` runs, in the order it runs them, so
"rejected" here means rejected there. Each row is judged against the
graph as it stands plus the rows before it in the same batch, which is
also how they would be written.
"""

from __future__ import annotations

from .model import Triple
from . import rules
from .reasoning import OWL_CHARACTERISTICS, RDF_TYPE

#: the verdicts, worst first — `trikedb import --dry-run` reports in this
#: order so the thing that needs a decision is not below the noise
ORDER = ("conflict", "rejected", "update", "new", "same")

FUNCTIONAL = OWL_CHARACTERISTICS["functional"]


def functional_predicates(db) -> set:
    """Predicates declared `functional`: at most one object per subject."""
    return {t.s for t in db.triples(p=RDF_TYPE, o=FUNCTIONAL)}


def preview(db, incoming) -> list:
    """Judge each incoming triple against the graph. Writes nothing.

    Returns one finding per row: {"verdict", "triple", "detail",
    "existing"}. `existing` is the triple already in the graph that the
    verdict is about, when there is one.
    """
    functional = functional_predicates(db)
    #: (s, p) -> o, for functional predicates only. Seeded from the graph
    #: and extended as the batch is judged, so two incoming rows that
    #: disagree with each other are caught too — they would be written in
    #: this order, and the second would silently win.
    held: dict = {}
    for t in db:
        if t.p in functional:
            held.setdefault((t.s, t.p), t.o)

    findings = []
    for row in incoming:
        finding = _judge(db, row, functional, held)
        findings.append(finding)
        if finding["verdict"] in ("new", "update"):
            triple = finding.get("_triple")
            if triple is not None and triple.p in functional:
                held.setdefault((triple.s, triple.p), triple.o)
    for finding in findings:
        finding.pop("_triple", None)
    return findings


def _judge(db, row, functional: set, held: dict) -> dict:
    row = dict(row)
    try:
        triple = Triple.from_dict(row)
    except (ValueError, TypeError) as exc:
        return _finding("rejected", row, str(exc))

    # The same gate add() puts every write through, run without the write.
    # Anything it refuses is refused for the same reason and with the same
    # words, so a preview cannot promise a write that then fails.
    try:
        rules.check_predicate(db, triple.p)
        rules.signed_by(db, triple.p, dict(triple.attrs))
        rules.check_link(db, triple.s, triple.p, triple.o)
        rules.check_action(db, triple)
    except Exception as exc:                     # noqa: BLE001 - reported, not raised
        return _finding("rejected", row, f"{type(exc).__name__}: {exc}", triple=triple)

    existing = _existing(db, triple)
    if existing is not None:
        if dict(existing.attrs) == dict(triple.attrs):
            return _finding("same", row, "already in the graph, unchanged",
                            existing=existing, triple=triple)
        return _finding("update", row, _changes(existing.attrs, triple.attrs),
                        existing=existing, triple=triple)

    if triple.p in functional:
        current = held.get((triple.s, triple.p))
        if current is not None and current != triple.o:
            return _finding(
                "conflict", row,
                f"{triple.p} is declared functional and {triple.s} already "
                f"holds {current!r}",
                existing=_lookup(db, triple.s, triple.p, current), triple=triple)

    twin = _lookup(db, triple.s, triple.p, triple.o)
    if twin is not None:
        return _finding("new", row, _twin(twin, triple), existing=twin,
                        triple=triple)
    return _finding("new", row, "new fact", triple=triple)


def _twin(existing: Triple, incoming: Triple) -> str:
    """Why a row with a familiar s/p/o is still going in as a new one.

    A triple's identity includes its time, on purpose: "restarted after
    failure" in April and the same line in September are two events, not
    one. The cost is that a fact re-stated without its date arrives as a
    second row rather than as the same one, and "new" alone does not warn
    anybody. Two real dates are two records and stay quiet; a missing
    date on either side is the case worth naming.
    """
    here, there = existing.when(), incoming.when()
    if here and there:
        return f"a second record of this — the graph already has it at {here}"
    if here:
        return (f"the graph already states this, dated {here}; undated, this "
                "row goes in beside it rather than into it")
    return (f"the graph already states this with no date; dated {there}, this "
            "row goes in beside it rather than into it")


def _existing(db, triple: Triple):
    """The triple already in the graph with this identity, if any."""
    want = triple.identity()
    for t in db.triples(s=triple.s, p=triple.p, o=triple.o):
        if t.identity() == want:
            return t
    return None


def _lookup(db, s: str, p: str, o: str):
    for t in db.triples(s=s, p=p, o=o):
        return t
    return None


def _changes(before: dict, after: dict) -> str:
    """What the upsert would do to the attributes, spelled out.

    add() merges attributes rather than replacing them, so a key the
    incoming row does not carry survives — saying "changed" without
    saying which keys would hide that.
    """
    parts = []
    for key in sorted(set(after) - set(before)):
        parts.append(f"+{key}={after[key]!r}")
    for key in sorted(set(after) & set(before)):
        if before[key] != after[key]:
            parts.append(f"{key}: {before[key]!r} -> {after[key]!r}")
    return "attributes " + ", ".join(parts) if parts else "no change"


def _finding(verdict: str, row: dict, detail: str, *, existing=None,
             triple=None) -> dict:
    return {
        "verdict": verdict,
        "triple": row,
        "detail": detail,
        "existing": existing.to_dict() if existing is not None else None,
        "_triple": triple,
    }


def counts(findings) -> dict:
    """Findings per verdict, in ORDER, omitting the ones that did not occur."""
    tally = {v: 0 for v in ORDER}
    for f in findings:
        tally[f["verdict"]] = tally.get(f["verdict"], 0) + 1
    return {k: v for k, v in tally.items() if v}


def blocking(findings) -> list:
    """The findings that need a human before anything is written."""
    return [f for f in findings if f["verdict"] in ("conflict", "rejected")]
