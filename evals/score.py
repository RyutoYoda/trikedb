#!/usr/bin/env python3
"""Measure an extraction against a hand-written answer, on purpose-built cases.

Why this exists as a file in the repository rather than a number in a
README: a claim about extraction quality that nobody can re-run is a
claim about the person making it. Everything needed to reproduce a
figure is here — the documents, the starting graphs, the answer a careful
person would write, the scorer, and the baseline prompt being compared
against. Bring your own model.

    python evals/score.py --llm examples.extract_providers:anthropic
    python evals/score.py --llm examples.extract_providers:anthropic --baseline
    python evals/score.py --record out/          # prompts to answer by hand
    python evals/score.py --answers out/         # score what came back

`--baseline` swaps the graph-constrained prompt for `triples-naive`,
which asks for the same table and supplies no vocabulary. Running both
is the comparison: every difference is what the graph contributed.

No numbers are committed here. The cases are small and adversarial by
construction — each one is built around a specific way extraction goes
wrong — so treat the output as a diagnostic, not a leaderboard.

## What is counted, and why each one

precision/recall  (s, p, o, at) against the gold answer. `at` is part of
                  the tuple because it is part of a triple's identity in
                  trikedb: two failures of the same job on different days
                  are two facts, and a scorer that ignored the date would
                  mark the right answer as a duplicate.

invented          rows using a predicate the ontology does not declare.
                  The write refuses these, so every one is a row that had
                  to be found and dropped by someone. The constrained
                  prompt is handed the list; this should be zero.

split             pairs of names that look like one thing written two
                  ways — against the graph ("Tamaki Metals Co., Ltd."
                  where the graph says "Tamaki Metals") and within the
                  answer itself ("田中" beside "田中 亮"). The most
                  expensive error in the set: each row is true, passes
                  every check, and quietly becomes a second node that no
                  query joins back together. The substring half of the
                  rule can be wrong — "Osaka" and "Osaka Bay" are two
                  places — so every pair it found is listed under
                  `split_pairs` in `--json` to be read rather than
                  trusted.

unquotable        rows whose `prov` is missing or is not a verbatim span
                  of the document. This is the cheap, deterministic
                  hallucination check that verbatim provenance buys: no
                  judge model, no embedding threshold, just a substring
                  test against the source. A row nobody can trace to a
                  sentence is a row nobody should have to argue about.

blocked           rows `merge.preview` would stop before the write —
                  contradictions of a `functional` predicate, violations
                  of a declared domain or range. Not a defect of the
                  model: work the graph did instead of the reviewer.

review            rows a person has to read. Recall bought with fifty
                  speculative rows is not the same product as recall
                  bought with eight.
"""
from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from trikedb import TrikeDB, merge                      # noqa: E402
from trikedb import extract as extract_mod              # noqa: E402

CASES = Path(__file__).resolve().parent / "extract"

#: Stripped before comparing two names for the same thing. Legal forms and
#: honorific suffixes are the variation that actually shows up; anything
#: cleverer than this belongs in a linking step, not in a scorer.
LEGAL_FORMS = ("株式会社", "有限会社", "合同会社", "co., ltd.", "co.,ltd.",
               "co. ltd.", "company limited", "corporation", "incorporated",
               "inc.", "inc", "corp.", "corp", "ltd.", "ltd", "llc", "plc",
               "gmbh", "社")


def cases() -> list:
    return sorted(p for p in CASES.iterdir() if (p / "document.md").exists())


def load(case: Path) -> tuple:
    db = TrikeDB(case / "graph.yaml", read_only=True)
    document = (case / "document.md").read_text(encoding="utf-8")
    gold = extract_mod.parse((case / "gold.md").read_text(encoding="utf-8"))
    return db, document, gold


# ------------------------------------------------------------------ scoring


def key(row: dict) -> tuple:
    """A fact's identity for scoring: subject, predicate, object, date."""
    return tuple(str(row.get(f, "") or "").strip() for f in ("s", "p", "o", "at"))


def fold(name) -> str:
    """One name for the same thing, however it was written."""
    text = str(name).strip().lower()
    for form in LEGAL_FORMS:
        text = text.replace(form, "")
    return re.sub(r"[\s　.,\-_'\"()（）・]", "", text)


def score(db, document: str, gold: list, answer: list) -> dict:
    got, want = [key(r) for r in answer], [key(r) for r in gold]
    hit = _overlap(got, want)
    body = _searchable(document)
    # Predicates and the owl# URIs an OWL declaration leaves behind are
    # nodes too, and neither is a name a document can spell differently.
    folded = {fold(n): n for n in db.nodes()
              if n not in db.ontology and "://" not in str(n)}

    invented = [r for r in answer
                if db.ontology and r.get("p") not in db.ontology]
    pairs = _splits(answer, folded)
    unquotable = [r for r in answer if not _quoted(r.get("prov"), body)]
    blocked = merge.blocking(merge.preview(db, answer))

    return {
        "rows": len(answer),
        "gold": len(gold),
        "hit": hit,
        "precision": _ratio(hit, len(got)),
        "recall": _ratio(hit, len(want)),
        "f1": _f1(_ratio(hit, len(got)), _ratio(hit, len(want))),
        "invented": len(invented),
        "split": len(pairs),
        "split_pairs": pairs,
        "unquotable": len(unquotable),
        "blocked": len(blocked),
        "review": len(answer),
        "misses": [w for w in want if w not in got],
        "extras": [g for g in got if g not in want],
    }


def _splits(answer: list, folded: dict) -> list:
    """Name pairs that are probably one entity written two ways.

    Two rules, in order of how much they can be trusted. An exact match
    after folding is not a judgement call: the graph says "Tamaki Metals"
    and the answer says "Tamaki Metals Co., Ltd.", and those are one
    vendor. A folded name contained in another is a guess — a good one for
    "田中" inside "田中 亮", a bad one for "Osaka" inside "Osaka Bay" — so
    the pairs are reported and not just counted.
    """
    names = []
    for row in answer:
        for name in (row.get("s"), row.get("o")):
            if name and str(name).strip() and name not in names:
                names.append(str(name).strip())

    pairs, seen = [], set()

    def note(written: str, other: str) -> None:
        pair = tuple(sorted((written, other)))
        if written != other and pair not in seen:
            seen.add(pair)
            pairs.append([pair[0], pair[1]])

    for name in names:                       # against what the graph holds
        existing = folded.get(fold(name))
        if existing is not None:
            note(name, existing)

    for i, one in enumerate(names):          # and against each other
        for other in names[i + 1:]:
            a, b = fold(one), fold(other)
            if not a or not b:
                continue
            if a == b or (len(a) >= 2 and a in b) or (len(b) >= 2 and b in a):
                note(one, other)
    return pairs


def _overlap(got: list, want: list) -> int:
    """Matches counted as multisets — a repeated fact is not two matches."""
    pool = list(want)
    found = 0
    for item in got:
        if item in pool:
            pool.remove(item)
            found += 1
    return found


def _searchable(text: str) -> str:
    """The document with whitespace flattened, so a quote wrapped across
    lines still matches the line it was wrapped from."""
    return re.sub(r"\s+", "", text)


def _quoted(prov, body: str) -> bool:
    if not prov:
        return False
    return re.sub(r"\s+", "", str(prov)) in body


def _ratio(part: int, whole: int) -> float:
    return round(part / whole, 3) if whole else 0.0


def _f1(p: float, r: float) -> float:
    return round(2 * p * r / (p + r), 3) if p + r else 0.0


# ------------------------------------------------------------------- running


def resolve(spec: str):
    """`module:factory` -> the llm callable it builds."""
    module, _, attr = spec.partition(":")
    factory = getattr(importlib.import_module(module), attr or "llm")
    return factory() if callable(factory) and not _takes_prompt(factory) else factory


def _takes_prompt(fn) -> bool:
    """A callable taking one required argument is already the llm itself."""
    import inspect

    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.default is inspect.Parameter.empty
               and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
               for p in params)


def prompt_for(db, document: str, baseline: bool) -> str:
    if baseline:
        from trikedb import prompts
        return prompts.render("triples-naive", text=document)
    return db.extract_prompt(document)


def report(rows: list, baseline: bool) -> None:
    head = ("case", "rows", "hit/gold", "prec", "rec", "f1",
            "invent", "split", "unquot", "blocked")
    width = [max(len(str(r[i])) for r in [head] + rows) for i in range(len(head))]
    for line in [head, tuple("-" * w for w in width)] + rows:
        print("  ".join(str(c).ljust(w) for c, w in zip(line, width)).rstrip())
    print(f"\nprompt: {'triples-naive (baseline)' if baseline else 'triples (graph-constrained)'}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--llm", metavar="MODULE:FACTORY",
                    help="e.g. examples.extract_providers:anthropic")
    ap.add_argument("--answers", metavar="DIR", type=Path,
                    help="score <DIR>/<case>.md instead of calling a model")
    ap.add_argument("--record", metavar="DIR", type=Path,
                    help="write <DIR>/<case>.prompt.txt and stop")
    ap.add_argument("--baseline", action="store_true",
                    help="use the unconstrained prompt instead")
    ap.add_argument("--case", action="append", help="run only this case")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    chosen = [c for c in cases() if not args.case or c.name in args.case]
    if not chosen:
        print("no cases", file=sys.stderr)
        return 2

    if args.record:
        args.record.mkdir(parents=True, exist_ok=True)
        for case in chosen:
            db, document, _ = load(case)
            out = args.record / f"{case.name}.prompt.txt"
            out.write_text(prompt_for(db, document, args.baseline), encoding="utf-8")
            print(f"{out}  — answer it into {args.record / (case.name + '.md')}")
        return 0

    if not args.llm and not args.answers:
        ap.error("pass --llm MODULE:FACTORY, or --answers DIR, or --record DIR.\n"
                 "There is no built-in model: the point of the adapter is that "
                 "the model is yours.")

    llm = resolve(args.llm) if args.llm else None
    table, results = [], {}
    for case in chosen:
        db, document, gold = load(case)
        if llm is not None:
            answer = extract_mod.parse(llm(prompt_for(db, document, args.baseline)))
        else:
            path = args.answers / f"{case.name}.md"
            if not path.exists():
                print(f"{path} missing — skipping {case.name}", file=sys.stderr)
                continue
            answer = extract_mod.parse(path.read_text(encoding="utf-8"))
        s = score(db, document, gold, answer)
        results[case.name] = s
        table.append((case.name, s["rows"], f"{s['hit']}/{s['gold']}",
                      s["precision"], s["recall"], s["f1"], s["invented"],
                      s["split"], s["unquotable"], s["blocked"]))

    if not results:
        # Every case was skipped. An empty table and a zero exit is the one
        # outcome an eval must never produce: it reads as "nothing wrong"
        # from CI while having measured nothing at all.
        print(f"scored no cases of {len(chosen)} — nothing was measured",
              file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0
    report(table, args.baseline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
