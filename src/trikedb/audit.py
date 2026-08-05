"""Deterministic health checks for a growing graph.

Ontologies accumulate facts from many hands (and agents). These
heuristics catch the decay modes that the ontology guard cannot:
duplicated facts across workspace members, same-entity-different-
spelling node names, near-duplicate free-text facts, orphaned node
properties, and declared-but-unused predicates.

Severity: "error" findings (duplicate-triple) fail `trikedb audit`;
the rest are warnings unless --strict. Semantic dedup beyond these
heuristics is a job for an LLM agent reviewing the report.
"""

from __future__ import annotations

from collections import defaultdict

ERROR_KINDS = {"duplicate-triple"}


def audit(db) -> list:
    """Return findings as [{"kind", "severity", "detail"}, ...]."""
    findings = []

    # 1. identical (s, p, o) appearing more than once (e.g. in two
    #    workspace member graphs) — a real duplicate, not a warning
    seen: dict = {}
    for t in db:
        key = t.spo()
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
    #    (token overlap > 60% of the smaller fact)
    events: dict = defaultdict(list)
    for t in db:
        if any(c.isspace() for c in t.o):
            events[(t.s, t.p)].append(t.o)
    for (s, p), texts in events.items():
        for i in range(len(texts)):
            for j in range(i + 1, len(texts)):
                a, b = set(texts[i].split()), set(texts[j].split())
                if a and b and len(a & b) / min(len(a), len(b)) > 0.6:
                    findings.append({
                        "kind": "similar-facts", "severity": "warning",
                        "detail": f"{s} {p}: {texts[i][:50]!r} ≈ {texts[j][:50]!r}",
                    })

    # 4. node properties for nodes no triple mentions
    linked = {x for t in db for x in (t.s, t.o)}
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

    return findings
