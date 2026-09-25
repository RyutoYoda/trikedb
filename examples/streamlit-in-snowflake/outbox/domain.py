"""Proposals, and the rules for applying one to a graph. This is the centre.

It knows nothing about the outside world. No files, no network: it mutates
the TrikeDB it is handed and returns what happened, so the tests run in a
second.

The rules live here for one reason: **do not trust the screen.** The screen
runs the same guard before it saves anything, but the outbox is a table and
a table can be written to from elsewhere. So everything goes through the
guard again, right before the PR is assembled. The duplication is the
point — if one side is bypassed the other still holds.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from trikedb import OntologyError, TrikeDB

#: What the screen is allowed to propose.
#:
#: `declare_link` (adding a predicate) was left out for a long time. A small
#: vocabulary is the entire point of the guard — once `USES_ROLE`,
#: `uses_role` and `USE_ROLE` all exist, no SPARQL query returns the right
#: answer any more. But **that argues for preventing spelling drift, not for
#: preventing people from expressing a new relationship.** When they cannot,
#: they either force the fact into an existing predicate where it does not
#: belong, or give up on proposing it. Both are worse for the vocabulary
#: than the thing being guarded against.
#:
#: So it is allowed, and the drift is stopped separately: UPPER_SNAKE names
#: only, a description is mandatory, and re-declaring an existing predicate
#: is refused (that would change a meaning silently). On top of that the PR
#: body lists vocabulary changes separately, above the facts, so a reviewer
#: cannot skim past them.
SUPPORTED_OPS = ("add_triple", "set_node", "declare_link")

#: Predicate names. Same shape as the existing vocabulary (USES_ROLE, ...).
_PREDICATE_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


class Refused(Exception):
    """This proposal cannot be applied. str() carries the reason."""


@dataclass(frozen=True)
class Proposal:
    """One row of the outbox table."""

    id: str
    author: str
    target_yaml: str
    op: str
    payload: Mapping[str, Any]
    note: str
    prov: str

    def check(self) -> None:
        """Shape only. Everything knowable without looking at the graph."""
        if self.op not in SUPPORTED_OPS:
            raise Refused(
                f"op {self.op!r} is not accepted "
                f"(supported: {', '.join(SUPPORTED_OPS)})"
            )
        # House rule: why a fact was added survives nowhere but the graph,
        # so a proposal without a note is not accepted. Same for its
        # source. The table declares both NOT NULL, but a string of spaces
        # passes that, so check it here too.
        if not self.note.strip():
            raise Refused("note (why you are proposing this) is empty")
        if not self.prov.strip():
            raise Refused("prov (where this came from) is empty")
        if not str(self.target_yaml).endswith(".yaml") or "/" in self.target_yaml:
            raise Refused(f"target_yaml {self.target_yaml!r} is not a file name")


@dataclass
class Outcome:
    """What one drain did."""

    applied: list[Proposal] = field(default_factory=list)
    refused: list[tuple[Proposal, str]] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.applied)

    def extend(self, other: "Outcome") -> None:
        """Fold a per-author apply back into the run as a whole."""
        self.applied.extend(other.applied)
        self.refused.extend(other.refused)


def group_by_author(proposals: Sequence[Proposal]) -> list[tuple[str, list[Proposal]]]:
    """Group proposals by who made them, keeping first-seen order.

    One PR per graph file, with the commits inside it split per author.
    The other shape — one PR per person — was tried and dropped: this path
    rewrites the whole YAML file, so two PRs both branch from main and
    whichever merges second erases what the first one added. Stacking
    commits on one branch cannot do that.
    """
    order: list[str] = []
    groups: dict[str, list[Proposal]] = {}
    for p in proposals:
        if p.author not in groups:
            order.append(p.author)
            groups[p.author] = []
        groups[p.author].append(p)
    return [(a, groups[a]) for a in order]


def apply(db: TrikeDB, proposals: Sequence[Proposal]) -> Outcome:
    """Apply proposals to `db` in order; return what stuck and what did not.

    One refusal does not stop the rest. Letting a single mistake hold up a
    day of proposals is too harsh for something that has not been reviewed
    yet — the reason is written back onto that proposal, so it finds its
    way to the person who wrote it.
    """
    outcome = Outcome()
    for p in proposals:
        try:
            p.check()
            _apply_one(db, p)
        except (Refused, OntologyError, TypeError, ValueError) as exc:
            outcome.refused.append((p, str(exc)))
        else:
            outcome.applied.append(p)
    return outcome


def _apply_one(db: TrikeDB, p: Proposal) -> None:
    payload = dict(p.payload or {})
    if p.op == "add_triple":
        try:
            s, pred, o = payload.pop("s"), payload.pop("p"), payload.pop("o")
        except KeyError as exc:
            raise Refused(f"add_triple has no {exc.args[0]}") from exc
        attrs = dict(payload.pop("attrs", None) or {})
        attrs.setdefault("prov", p.prov)
        attrs.setdefault("note", p.note)
        if payload.get("at"):
            attrs.setdefault("at", payload["at"])
        if not db.ontology:
            # With no declared vocabulary, trikedb's guard has nothing to
            # check against and any predicate at all goes through. **A brand
            # new graph file starts in exactly that state,** so skipping
            # this creates one file where nothing is ever checked, and every
            # fact that lands in it afterwards is unguarded. Merged into a
            # workspace it looks fine, because the other files supply
            # plausible vocabulary — which is why it would be found late.
            raise Refused(
                f"declare {pred!r} in this graph file before using it "
                "(a new file starts with an empty vocabulary; fill in "
                "'new predicate' in the same proposal and it will be "
                "declared first, then used)")
        # Undeclared predicate, edge written backwards, or an action whose
        # precondition never happened: all come back as OntologyError.
        db.add(str(s), str(pred), str(o), **attrs)
    elif p.op == "set_node":
        name = payload.get("name")
        if not name:
            raise Refused("set_node has no name")
        props = dict(payload.get("props") or {})
        if not props:
            raise Refused("set_node has no props")
        props.setdefault("prov", p.prov)
        db.set_node(str(name), **props)
    elif p.op == "declare_link":
        name = str(payload.get("name") or "").strip()
        if not name:
            raise Refused("declare_link has no name")
        if not _PREDICATE_NAME.match(name):
            raise Refused(
                f"predicate name {name!r} is not UPPER_SNAKE_CASE "
                "(matching the existing vocabulary is what keeps two "
                "spellings of the same relationship from coexisting and "
                "making every query wrong)")
        description = str(payload.get("description") or "").strip()
        if not description:
            raise Refused(
                "declare_link has no description "
                "(a predicate that does not say what it connects to what "
                "cannot be used correctly by the next person)")
        # db.ontology is the declared vocabulary. db.predicates() is what is
        # actually used, which excludes predicates that were only declared
        # (and is always empty on an empty graph).
        if name in db.ontology:
            raise Refused(
                f"predicate {name!r} already exists; the meaning of an "
                "existing predicate cannot be changed silently (do that in "
                "a PR against the ontology itself)")
        kw = {k: payload[k] for k in ("domain", "range") if payload.get(k)}
        db.declare_link(name, description=description, **kw)
    else:  # check() refuses this first, so it does not get here
        raise Refused(f"op {p.op!r} is not accepted")


#: The name of a new graph file. It becomes a file name, so only the shape
#: the existing files already use.
_GRAPH_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def graph_key(target_yaml: str) -> str:
    """The key this file gets in workspace.yaml, derived from the name.

    The key ends up as the `graph` attribute on every triple, so it wants to
    be readable. Asking the proposer for it separately would add a field
    without adding much: there is rarely a reason for it to differ from the
    file name, and a PR can change it if there is.
    """
    return target_yaml.removesuffix(".yaml")


def check_target_name(target_yaml: str) -> None:
    """Is this acceptable as a graph file name? Refused if not.

    Existing files go through this too. They pass, obviously — but making
    it a new-files-only check would let a proposal aimed at
    **workspace.yaml** through, and that file is a union: writing to it
    would flatten every graph it unions into one file.
    """
    name = graph_key(target_yaml)
    if not _GRAPH_NAME.match(name):
        raise Refused(
            f"graph file name {target_yaml!r} must be lowercase and "
            "underscores, to match the files already there")
    if name == "workspace":
        raise Refused("workspace.yaml is a read-only union; it cannot be a target")


def register_in_workspace(text: str, target_yaml: str) -> str:
    """Add one line to `graphs:` in workspace.yaml. No-op if already there.

    This inserts **a line of text** rather than loading and dumping the
    YAML, because a round trip loses the comment at the top of the file
    (which is where the regeneration command is written down) and the
    ordering. The ordering decides which graph wins when two of them give a
    node the same attribute, so it means something.

    New graphs go at the end: lowest precedence of anything present, which
    is better than a newcomer silently overriding an established graph.
    """
    key = graph_key(target_yaml)
    lines = text.splitlines()
    try:
        head = next(i for i, ln in enumerate(lines)
                    if ln.rstrip() == "graphs:" or ln.startswith("graphs:"))
    except StopIteration:
        raise Refused("workspace.yaml has no graphs:") from None

    last = head
    for i in range(head + 1, len(lines)):
        ln = lines[i]
        if not ln.strip():                 # blank lines belong to the block
            continue
        if not ln[:1].isspace():           # dedent means the block ended
            break
        if ln.split(":", 1)[0].strip() == key:
            return text                    # already registered
        last = i

    indent = lines[last][:len(lines[last]) - len(lines[last].lstrip())] or "  "
    lines.insert(last + 1, f"{indent}{key}: {target_yaml}")
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def commit_message(author: str, applied: Sequence[Proposal], target_yaml: str) -> str:
    """The message for one person's commit.

    Count on the first line, the notes underneath. It repeats the PR body,
    deliberately: the PR may eventually go away, the commit will not, and
    "why" is the part worth keeping in both places.
    """
    head = (f"kg({target_yaml.removesuffix('.yaml')}): "
            f"{len(applied)} proposal(s) from {author}")
    body = [f"- {_summarize(p)} — {_cell(p.note)}" for p in applied]
    return "\n".join([head, ""] + body)


def describe(outcome: Outcome, target_yaml: str,
             deferred: Sequence[tuple[str, Sequence[Proposal]]] = ()) -> tuple[str, str]:
    """Title and body for the PR.

    The body lists the notes because what a reviewer needs is **why** each
    fact was added, not what changed. GitHub already shows what changed.
    """
    n = len(outcome.applied)
    authors = sorted({p.author for p in outcome.applied})
    title = f"kg: {n} proposal(s) for {target_yaml} from the curation screen"

    lines = [
        f"Proposals for `{target_yaml}`, collected from the curation screen "
        "(Streamlit in Snowflake) and rolled into one PR.",
        "",
        "Every one of them passed the ontology guard twice: once when it "
        "was saved, once just before this PR was assembled. **A machine has "
        "already checked that the predicates, directions and preconditions "
        "are valid, so the only question left for you is whether the facts "
        "are true.**",
        "",
        f"Proposed by: {', '.join(authors) if authors else '(nobody)'} "
        "(one commit per person)",
        "",
        "| # | op | what | why | source | by |",
        "|---|---|---|---|---|---|",
    ]

    vocab = [p for p in outcome.applied if p.op == "declare_link"]
    if vocab:
        # Adding a fact and adding a word are not the same weight of
        # review. Inside the same table they look the same, so they are
        # pulled out and put first.
        head = [
            "",
            f"### ⚠ {len(vocab)} proposal(s) add to the vocabulary",
            "",
            "These do not add facts. They change **what this graph is able "
            "to say.** Once a predicate is in, other people start using it, "
            "so settle its name and meaning here.",
            "",
            "| predicate | meaning | why it is needed | by |",
            "|---|---|---|---|",
        ]
        for p in vocab:
            d = p.payload or {}
            head.append(
                f"| `{d.get('name')}` | {_cell(d.get('description') or '')} "
                f"| {_cell(p.note)} | {p.author} |")
        lines = lines[:-2] + head + ["", "### The proposals", ""] + lines[-2:]
    for i, p in enumerate(outcome.applied, 1):
        lines.append(
            f"| {i} | `{p.op}` | {_summarize(p)} | {_cell(p.note)} "
            f"| {_cell(p.prov)} | {p.author} |"
        )

    if deferred:
        waiting = ", ".join(f"{a} ({len(ps)})" for a, ps in deferred)
        lines += [
            "",
            "### Proposals not carried yet",
            "",
            f"Proposals from {waiting} are not in this PR because they have "
            "not linked a GitHub account. Once they do so from the screen, "
            "the next run picks them up — the proposals are still queued, "
            "so nothing has to be re-entered.",
        ]

    if outcome.refused:
        lines += [
            "",
            f"### {len(outcome.refused)} proposal(s) refused",
            "",
            "These hit the guard and are not in this PR.",
            "",
            "| what | why | by |",
            "|---|---|---|",
        ]
        for p, why in outcome.refused:
            lines.append(f"| {_summarize(p)} | {_cell(why)} | {p.author} |")

    return title, "\n".join(lines)


def _summarize(p: Proposal) -> str:
    d = p.payload or {}
    if p.op == "add_triple":
        return f"`{d.get('s')} {d.get('p')} {d.get('o')}`"
    if p.op == "set_node":
        return f"`{d.get('name')}` gets {', '.join(sorted((d.get('props') or {})))}"
    if p.op == "declare_link":
        where = ""
        if d.get("domain") or d.get("range"):
            where = f" ({d.get('domain') or '?'} → {d.get('range') or '?'})"
        return f"new relationship `{d.get('name')}`{where}"
    return f"`{p.op}`"


def _cell(text: str) -> str:
    """Flatten to something that survives a markdown table cell."""
    return str(text).replace("|", "\\|").replace("\n", " ").strip()
