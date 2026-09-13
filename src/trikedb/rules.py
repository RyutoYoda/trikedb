"""What a predicate declares about itself, and what that costs at write time.

`domain` and `range` say what an action may connect; `requires` and `by`
say when it may run and who may run it. A semantic layer stops at the
first two and leaves the rest to whatever code performs the update —
which is how an order gets delivered before it shipped.

These are free functions taking the store as their first argument, the
shape `audit`, `reasoning` and `importers` already use, rather than more
methods on TrikeDB: the class keeps one-line delegations so that
`db._unmet(...)` still means what it always did, and the reasoning about
when a condition holds lives in one file that the write path and `audit`
both call.
"""

from __future__ import annotations

import shlex
from typing import Any, Optional

from .model import (RULE_KEYS, OntologyError, Triple, _is_pattern, _term,
                    _time_key, _unify)


def declare_predicate(db, name: str, value: Any, *,
                      keep_existing: bool = False) -> None:
    """Record one predicate declaration: a description, or a shape.

    ``INGESTS_TO: "job -> table"`` is a comment; nothing checks it. The
    mapping form says the same thing to the machine::

        INGESTS_TO: {description: ..., domain: job, range: table}
    """
    if keep_existing and name in db.ontology:
        return
    if not isinstance(value, dict):
        db.ontology[name] = str(value or "")
        return
    db.ontology[name] = str(value.get("description") or "")
    rule = {}
    for key in RULE_KEYS:
        want = value.get(key)
        if want is None or want == "":
            continue
        if isinstance(want, (list, tuple)):
            rule[key] = tuple(str(t) for t in want)
        else:
            rule[key] = (str(want),)
        if key == "requires":
            for need in rule[key]:
                # A condition that is neither a predicate name nor an
                # (s p o) pattern used to be kept as a predicate name
                # nothing could ever match, which reads in audit as
                # "this has never happened" — a condition that always
                # fails and a condition that is misspelled have to be
                # distinguishable, or the guarantee is worth nothing.
                if len(shlex.split(need)) not in (1, 3):
                    raise OntologyError(
                        f"{name} requires {need!r}, which is neither a "
                        f"predicate name nor an (s p o) pattern — write "
                        f"one term or three, e.g. 'SHIPPED_FROM' or "
                        f"'?order PLACED_BY ?s'")
    if rule:
        db.predicate_rules[name] = rule
    else:
        db.predicate_rules.pop(name, None)


def declaration(db, name: str) -> Any:
    """What this predicate looks like in the file: a string, or a shape."""
    rule = db.predicate_rules.get(name)
    if not rule:
        return db.ontology[name]
    out: dict = {}
    if db.ontology[name]:
        out["description"] = db.ontology[name]
    for key in RULE_KEYS:
        want = rule.get(key)
        if want:
            out[key] = list(want) if len(want) > 1 else want[0]
    return out


def declare_link(db, predicate: str, *, domain=None, range=None,
                 requires=None, by=None,
                 description: Optional[str] = None) -> dict:
    """Declare what a predicate connects and how it may run, and have
    it enforced.

    ``domain`` is the node type allowed as the subject, ``range`` the
    one allowed as the object. ``requires`` names what must already
    have happened to the subject — all of them, if you pass a list,
    because that is what the word says — and ``by`` the node type of
    whoever performs it. Once declared, an edge written the wrong way
    round, an action run out of order, and an action nobody signs are
    all refused instead of stored, which is the whole point of writing
    the declaration down.

    A declaration is the whole shape restated, not a patch to it, so
    what you leave out is withdrawn — ``declare_link("P")`` with
    nothing else takes the declaration off again.
    """
    predicate = _term(predicate, "p")
    spec: dict = {"description": description
                  if description is not None else db.ontology.get(predicate, "")}
    for key, want in (("domain", domain), ("range", range),
                      ("requires", requires), ("by", by)):
        if want is not None:
            spec[key] = want
    declare_predicate(db, predicate, spec)
    for t in db._triples:
        if t.p == predicate:
            check_link(db, t.s, t.p, t.o)
            check_action(db, t)
    db._autosave()
    return {"description": db.ontology[predicate],
            **{k: list(v) for k, v in db.predicate_rules.get(predicate, {}).items()}}


def rule_text(rule: dict, key: str) -> str:
    want = rule.get(key)
    return "|".join(want) if want else "any"


def fits(db, rule: dict, s: str, o: str) -> bool:
    for name, key in ((s, "domain"), (o, "range")):
        want = rule.get(key)
        if not want:
            continue
        have = (db.nodes_meta.get(name) or {}).get("type")
        if have is None or str(have) not in want:
            return False
    return True


def check_link(db, s: str, p: str, o: str) -> None:
    """Refuse a link that contradicts its own declaration.

    Only where the type is actually known. Types get written after the
    edges that use them as often as before, and rejecting on a type
    nobody has stated yet would make a correct import fail on the order
    it happens to be in. What is still unknown, ``audit()`` reports.
    """
    rule = db.predicate_rules.get(p)
    if not rule:
        return
    for role, name, key in (("subject", s, "domain"), ("object", o, "range")):
        want = rule.get(key)
        have = (db.nodes_meta.get(name) or {}).get("type")
        if not want or have is None or str(have) in want:
            continue
        hint = (f" — the other way round ({o} {p} {s}) fits"
                if fits(db, rule, o, s) else "")
        raise OntologyError(
            f"{p} is declared {rule_text(rule, 'domain')} -> "
            f"{rule_text(rule, 'range')}, so its {role} cannot be "
            f"{name!r}, which is a {have!r}{hint}"
        )


def happened(db, node: str, predicate: str, before: str) -> bool:
    """Had this already happened to this node by then?

    Both directions, the reading history() gives rather than the one
    state() gives, and the difference matters here more than anywhere.
    The moment an event grows properties of its own it becomes an
    object, and that moves the thing it happened to onto the far side
    of the edge: a retirement written ``RET-0007 RETIRED <product>``
    leaves the product with no RETIRED of its own. Reading only the
    subject side would mean a precondition stops holding the moment an
    event is promoted — failing in precisely the case this is for.

    A fact carrying no date is simply already true: ``SOLD_IN`` with no
    time is not something that happened on a day, it is how the world
    is, and nothing can be earlier than it.
    """
    limit = _time_key(before)
    for t in db._p_index()[1].get((predicate, node), ()):
        stamp = t.when()
        if not stamp or _time_key(stamp) <= limit:
            return True
    return False


def solve(db, patterns: list, binding: dict, limit: Optional[str]):
    """How this conjunction can be satisfied, as of then.

    The join query() does, with the two differences a precondition
    needs. The bindings arrive already carrying ``s`` and ``o`` — the
    two ends of the action being checked — so the question is asked
    about *this* action rather than about the graph at large. And every
    candidate is filtered by the clock before the join, which yields
    exactly the solutions whose every step had already happened; a step
    carrying no date is how the world is rather than something that
    occurred, so nothing can be earlier than it.

    Returns the solutions and, when there are none, the step that came
    up empty — a condition spanning three patterns is only debuggable
    if it says which one of them failed.
    """
    rows = [dict(binding)]
    for i, pat in enumerate(patterns):
        by_p, by_end = db._p_index()
        step = []
        for row in rows:
            # Whichever end this step already knows — written into the
            # pattern, or bound by a step before it — picks the pool.
            # Without that the join reads the whole predicate every
            # time and a condition costs the size of the graph.
            ends = [row.get(x[1:]) if x.startswith("?") else x
                    for x in (pat[0], pat[2])]
            known = next((e for e in ends if e), None)
            if pat[1].startswith("?"):
                pool = db._triples
            elif known is not None:
                pool = by_end.get((pat[1], known), ())
            else:
                pool = by_p.get(pat[1], ())
            for t in pool:
                stamp = t.when()
                if limit is not None and stamp and _time_key(stamp) > limit:
                    continue
                nb = _unify(pat, t, row)
                if nb is not None:
                    step.append(nb)
        rows = step
        if not rows:
            return [], i
    return rows, None


def unmet(db, t: Triple, rule: dict) -> list:
    """Which declared conditions the graph does not meet — the ones that
    need triples other than this one to answer.

    Kept apart from the checks the triple settles by itself, because
    the two behave differently while a graph is still being built.
    These are monotone: writing more triples can satisfy one of them,
    never break one. So a condition that fails halfway through a bulk
    load is evidence not yet written rather than a violation, and the
    honest move is to ask again once the graph is whole — which is what
    _settle does. The ones above cannot be repaired by anything written
    later, so they are refused where they are written.
    """
    out = []
    actors, who = rule.get("by"), str(t.attrs.get("by") or "")
    if actors and who:
        have = (db.nodes_meta.get(who) or {}).get("type")
        if have is not None and str(have) not in actors:
            out.append(
                f"{t.p} is declared to be performed by "
                f"{rule_text(rule, 'by')}, so {who!r}, which is a "
                f"{have!r}, cannot be the one who did it")
    needs = rule.get("requires")
    if not needs:
        return out
    when = t.when()
    # Either end, because an action that is itself an object is its own
    # subject: MIT-0007 MITIGATED INC-2025-01 puts the incident — the
    # thing that had to have been raised first — on the far side, and
    # the mitigation, newly created, has no history at all to ask
    # about. The condition is a question about what this action
    # touches, not about one nominated end of it.
    for need in [n for n in needs if not _is_pattern(n)]:
        if any(happened(db, end, need, when) for end in (t.s, t.o)):
            continue
        ends = {t.s, t.o}
        later = any((need, end) in db._p_index()[1] for end in ends)
        out.append(
            f"{t.p} is declared to require {need} first, but "
            f"({t.s} {t.p} {t.o}) "
            + (f"only has its {need} after {when}"
               if later else f"has no {need} on either end"))
    # A step is one edge; a condition is often not. "a review may only be
    # written by someone who bought the thing" is PLACED_BY joined to
    # CONTAINS, and no single-edge check can reach it. Written as
    # patterns the steps join on their shared variables, with ?s and ?o
    # standing for the two ends of the action itself.
    pats = [db._parse_pattern(n) for n in needs if _is_pattern(n)]
    if not pats:
        return out
    rows, failed = solve(db, pats, {"s": t.s, "o": t.o}, _time_key(when))
    if not rows:
        step = " ".join(pats[failed])
        whole = "; ".join(" ".join(x) for x in pats)
        ever, _ = solve(db, pats[:failed + 1], {"s": t.s, "o": t.o}, None)
        out.append(
            f"{t.p} is declared to require ({whole}) first, but for "
            f"({t.s} {t.p} {t.o}) nothing satisfies ({step}) "
            + (f"by {when}" if ever else "at all"))
    return out


def check_action(db, t: Triple) -> None:
    """Refuse an action whose declared conditions are not met.

    ``domain`` and ``range`` catch an edge written the wrong way round.
    Neither can reach the two ways an action goes wrong while staying
    perfectly well-typed: running before the thing that makes it
    possible, and running with nobody accountable for it. An order
    delivered before it shipped is type-correct. So is a price change
    approved by no one.

    What the triple alone settles is refused here and now, because
    nothing written later can repair it. What needs the rest of the
    graph is refused here too — unless a batch is open, in which case
    the graph is still being assembled and the answer is not final yet,
    so the question is held and asked again on the way out. Nothing is
    skipped either way; only the moment the exception arrives moves.
    """
    rule = db.predicate_rules.get(t.p)
    if not rule:
        return
    if rule.get("by") and not str(t.attrs.get("by") or ""):
        raise OntologyError(
            f"{t.p} is declared to be performed by "
            f"{rule_text(rule, 'by')}, so it cannot be recorded "
            f"with nobody's name on it — pass by=")
    if rule.get("requires") and not t.when():
        raise OntologyError(
            f"{t.p} is declared to require {rule_text(rule, 'requires')} "
            f"first, so it has to say when it happened — pass at=")
    failures = unmet(db, t, rule)
    if not failures:
        return
    if db._batch_depth:
        db._pending.append(t)
        return
    raise OntologyError(failures[0])


def settle(db) -> None:
    """Ask the held questions again, now that the graph is whole.

    A bulk load writes in whatever order the source had, and a
    condition is about the clock rather than the line number, so the
    evidence for a write frequently arrives after it. Holding those
    until the end is what lets a multi-step condition be enforced on
    the write path at all instead of being demoted to something
    audit() alone notices.
    """
    held, db._pending = db._pending, []
    failures = [m for t in held
                for m in unmet(db, t, db.predicate_rules.get(t.p) or {})]
    if failures:
        raise OntologyError(
            failures[0] + (f" (and {len(failures) - 1} more like it)"
                           if len(failures) > 1 else ""))


def check_node_type(db, name: str, new_type: str) -> None:
    """Would typing this node this way break an edge already written?

    The other half of _check_link, read from the node's side, so that
    which of the two was written first cannot decide whether the graph
    obeys its own ontology.

    Only the edges that actually touch this node, found through the
    (predicate, node) index rather than by walking the graph: a bulk
    load types every node it writes, and a scan per typed node is
    quadratic in the load — 25k triples took a minute and a half, and
    the same import with the index is under a second. What bounds the
    work now is how many predicates the ontology declares, which is a
    property of the schema and does not grow with the data.
    """
    _, eidx = db._p_index()
    for predicate, rule in db.predicate_rules.items():
        if not rule:
            continue
        for t in eidx.get((predicate, name), ()):
            for role, key, end in (("subject", "domain", t.s),
                                   ("object", "range", t.o)):
                want = rule.get(key)
                if end != name or not want or new_type in want:
                    continue
                raise OntologyError(
                    f"{name!r} is the {role} of ({t.s} {t.p} {t.o}), which is "
                    f"declared {rule_text(rule, key)} there — typing it "
                    f"{new_type!r} would contradict a link already in the graph"
                )


def check_predicate(db, p: str) -> None:
    if (
        db.ontology
        and p not in db.ontology
        and not p.startswith(("http://", "https://"))
    ):
        raise OntologyError(
            f"predicate {p!r} is not in the ontology "
            f"(allowed: {sorted(db.ontology)})"
        )
