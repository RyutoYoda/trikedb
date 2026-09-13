"""Deterministic health checks for a growing graph.

Ontologies accumulate facts from many hands (and agents). These
heuristics catch the decay modes that the ontology guard cannot:
duplicated facts across workspace members, same-entity-different-
spelling node names, near-duplicate free-text facts, orphaned node
properties, declared-but-unused predicates, links that do not hold
up against the shape their predicate declares, and events written onto
the node instead of onto the triple that carries them.

Severity: "error" findings (duplicate-triple, link-contradicts-
declaration) fail `trikedb audit`;
the rest are warnings unless --strict. Semantic dedup beyond these
heuristics is a job for an LLM agent reviewing the report.
"""

from __future__ import annotations

import json
from collections import defaultdict

from .model import TIME_ATTRS
from .rules import unmet as _unmet

ERROR_KINDS = {"duplicate-triple", "link-contradicts-declaration",
               "precondition-unmet", "action-has-no-actor",
               "actor-contradicts-declaration"}


def audit(db) -> list:
    """Return findings as [{"kind", "severity", "detail"}, ...]."""
    findings = []

    # 1. identical (s, p, o) appearing more than once (e.g. in two
    #    workspace member graphs) — a real duplicate, not a warning
    seen: dict = {}
    for t in db:
        # An event is compared whole. Two events can be the same sentence on
        # two days ("restarted after failure") — two things that happened,
        # not one fact written twice — and two actions in the same
        # millisecond are still two actions, told apart by who ran them and
        # what state each left behind. Only a row identical down to its last
        # attribute is a double-write. A plain fact, carrying no time, is
        # still just its (s, p, o).
        body = {k: v for k, v in t.attrs.items() if k != "graph"}
        key = t.spo() + ((json.dumps(body, sort_keys=True, default=str),)
                         if t.when() else ())
        where = t.attrs.get("graph", "-")
        if key in seen:
            findings.append({
                "kind": "duplicate-triple", "severity": "error",
                "detail": f"({t.s}, {t.p}, {t.o}) in graphs [{seen[key]}] and [{where}]",
            })
        else:
            seen[key] = where

    # 2. node names that normalize to the same string — likely the same
    #    entity spelled differently ("Tokyo" vs "tokyo", trailing spaces)
    norm: dict = defaultdict(list)
    for n in db.nodes():
        norm[n.strip().lower()].append(n)
    for names in norm.values():
        if len(names) > 1:
            findings.append({
                "kind": "name-collision", "severity": "warning",
                "detail": f"possibly the same entity: {names}",
            })

    # 3. near-duplicate free-text facts on the same subject+predicate
    #    (token overlap > 60% of the smaller fact). Two events at two
    #    different times are excluded however alike they read: "restarted
    #    after failure" in April and again in September is a log doing its
    #    job, and calling that a near-duplicate asks you to delete history.
    events: dict = defaultdict(list)
    for t in db:
        if any(c.isspace() for c in t.o):
            events[(t.s, t.p)].append((t.o, t.when()))
    for (s, p), texts in events.items():
        for i in range(len(texts)):
            for j in range(i + 1, len(texts)):
                if texts[i][1] != texts[j][1]:
                    continue
                a, b = set(texts[i][0].split()), set(texts[j][0].split())
                if a and b and len(a & b) / min(len(a), len(b)) > 0.6:
                    findings.append({
                        "kind": "similar-facts", "severity": "warning",
                        "detail": f"{s} {p}: {texts[i][0][:50]!r} "
                                  f"≈ {texts[j][0][:50]!r}",
                    })

    # 4. node properties for nodes no triple mentions.
    #    Predicates count as mentioned: attaching properties to a predicate
    #    is a documented pattern (`set_node("PROVIDES", since="2024")` — RDF
    #    treats a predicate as an ordinary name), and flagging it meant the
    #    recommended usage produced a warning.
    #    Whoever performed an action counts as mentioned too: an actor is
    #    named in by=, not in a triple's subject or object, so a courier who
    #    only ever delivers would otherwise be reported as unattached the
    #    moment a predicate declares who may run it.
    linked = {x for t in db for x in (t.s, t.p, t.o)}
    linked |= {str(t.attrs["by"]) for t in db if t.attrs.get("by")}
    for n in db.nodes_meta:
        if n not in linked:
            findings.append({
                "kind": "orphan-node", "severity": "warning",
                "detail": f"node {n!r} has properties but no triples",
            })

    # 5. declared predicates that no triple uses
    used = {t.p for t in db}
    for p in db.ontology:
        if p not in used:
            findings.append({
                "kind": "unused-predicate", "severity": "warning",
                "detail": p,
            })

    # 6. links measured against the shape their predicate declares. add()
    #    refuses one it can see is wrong, but a type can arrive after the
    #    edge, and a file can be hand-edited — so what the write path let
    #    through on a missing type gets reported here rather than assumed.
    rules = getattr(db, "predicate_rules", {})
    for t in db:
        rule = rules.get(t.p)
        if not rule:
            continue
        shape = "%s -> %s" % (_names(rule.get("domain")), _names(rule.get("range")))
        for role, name, key in (("subject", t.s, "domain"), ("object", t.o, "range")):
            want = rule.get(key)
            if not want:
                continue
            have = (db.nodes_meta.get(name) or {}).get("type")
            if have is None:
                findings.append({
                    "kind": "unchecked-link", "severity": "warning",
                    "detail": f"{t.p} declares {shape}, but its {role} {name!r} "
                              f"has no type — nothing checked it",
                })
            elif str(have) not in want:
                findings.append({
                    "kind": "link-contradicts-declaration", "severity": "error",
                    "detail": f"{t.p} declares {shape}, but its {role} {name!r} "
                              f"is a {have!r}",
                })

    # 7. the other half of a declaration: when an action may run, and who
    #    may run it. add() and act() refuse what they can see, but a file
    #    is hand-edited and loaded whole — and on load the order the lines
    #    happen to be in must not decide whether the graph obeys itself.
    #    So the finished file is read back with the time, not the line
    #    number, saying what came first.
    #    The conditions themselves are asked through rules.unmet, the
    #    same call the write path makes, rather than re-derived here: two
    #    implementations of "had this happened yet" would eventually
    #    disagree, and the one a reader trusts is whichever they ran last.
    for t in db:
        rule = rules.get(t.p)
        if not rule:
            continue
        actors = rule.get("by")
        who = str(t.attrs.get("by") or "")
        if actors and not who:
            findings.append({
                "kind": "action-has-no-actor", "severity": "error",
                "detail": f"{t.p} is performed by {_names(actors)}, but "
                          f"({t.s} {t.p} {t.o}) says nobody did it",
            })
        elif actors and (db.nodes_meta.get(who) or {}).get("type") is None:
            findings.append({
                "kind": "unchecked-actor", "severity": "warning",
                "detail": f"{t.p} is performed by {_names(actors)}, but "
                          f"{who!r} has no type — nothing checked it",
            })
        if rule.get("requires") and not t.when():
            findings.append({
                "kind": "precondition-unmet", "severity": "error",
                "detail": f"{t.p} requires {_names(rule['requires'])} first, but "
                          f"({t.s} {t.p} {t.o}) does not say when it happened",
            })
            continue
        for detail in _unmet(db, t, rule):
            findings.append({
                "kind": ("actor-contradicts-declaration"
                         if "cannot be the one who did it" in detail
                         else "precondition-unmet"),
                "severity": "error", "detail": detail,
            })

    # 8. an event written onto the node instead of onto the triple.
    #    Promotion gives an event an id so it can hold the properties that
    #    made it worth promoting — a before, an after, a reason. It does
    #    not move `at:` and `state:`: those are read off the triple, by
    #    when() and by state(), and a node carrying both of them is an
    #    event record sitting where nothing reads it. The failure is
    #    silent — history() simply returns fewer rows than the file looks
    #    like it holds — so it is reported here rather than left to be
    #    noticed. Both keys are required to call it: a date alone is an
    #    ordinary property (a release has one), and a state alone is what
    #    act() writes onto every node it touches.
    for name, props in db.nodes_meta.items():
        stamp = next((k for k in TIME_ATTRS if k in props), None)
        mark = next((k for k in ("state", "status") if k in props), None)
        if not (stamp and mark):
            continue
        undated = [t for t in db if t.o == name and not t.when()]
        where = (f"({undated[0].s} {undated[0].p} {name}) carries no time, so "
                 f"history() does not see it" if undated else
                 f"the triples pointing at {name!r} carry their own time, so "
                 f"{stamp!r} here is a second copy and {mark!r} is read by nothing")
        findings.append({
            "kind": "event-written-on-node", "severity": "warning",
            "detail": f"node {name!r} has both {stamp!r} and {mark!r} — an event's "
                      f"time and state belong on the triple, not the node; {where}",
        })

    return findings


def _names(want) -> str:
    return "|".join(want) if want else "any"
