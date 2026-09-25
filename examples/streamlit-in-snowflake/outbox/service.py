"""The drain use case. Only the sequence of steps lives here.

One PR per graph file. Inside it, one commit per proposer, each made with
that person's own credentials (which credentials those are is decided by the
GraphSource implementation, so it never appears in this file).

One PR per person was considered and dropped. This path rewrites the whole
YAML file, so two PRs both branch from main and whichever merges second
erases what the first one added. Stacking commits on one branch cannot do
that.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from trikedb import TrikeDB

from . import domain
from .ports import Clock, GraphSource, ProposalQueue


@dataclass
class DrainResult:
    target_yaml: str
    applied: int = 0
    refused: int = 0
    deferred: int = 0
    #: Deferred proposals broken down as [(author, count), ...]. A bare
    #: count cannot tell the screen **whose** proposals are waiting, and the
    #: screen then explains the person's own proposals to them as "somebody
    #: else's" — which is exactly what it used to do. Only the screen knows
    #: who is looking, so hand it what it needs to decide.
    deferred_by_author: list[tuple[str, int]] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)
    pr_url: Optional[str] = None
    #: The graph file that was created, if one was. The screen says so
    #: explicitly, because unlike adding to an existing file this is not
    #: easy to walk back.
    created: Optional[str] = None
    message: str = ""

    def as_dict(self) -> dict:
        return {
            "target_yaml": self.target_yaml,
            "applied": self.applied,
            "refused": self.refused,
            "deferred": self.deferred,
            "deferred_by_author": self.deferred_by_author,
            "authors": self.authors,
            "pr_url": self.pr_url,
            "created": self.created,
            "message": self.message,
        }


def drain(
    *,
    target_yaml: str,
    queue: ProposalQueue,
    source: GraphSource,
    clock: Clock,
    load: Callable[[str], TrikeDB],
    dump: Callable[[TrikeDB], str],
) -> DrainResult:
    """Turn the queued proposals into one pull request.

    `load`/`dump` convert between a YAML string and a TrikeDB; the adapter
    layer supplies them. Pulling that boundary out into two functions is
    what lets this file stop caring which of the two it is holding.
    """
    result = DrainResult(target_yaml=target_yaml)

    proposals = list(queue.pending(target_yaml))
    if not proposals:
        result.message = "nothing proposed"
        return result

    # Split on credentials first. Applying a proposal from somebody we
    # cannot commit as would fold their change into another person's commit
    # — if it cannot carry their name, leave it pending for now.
    writable, deferred = [], []
    for author, group in domain.group_by_author(proposals):
        (writable if source.can_write(author) else deferred).append((author, group))

    result.deferred_by_author = [(a, len(g)) for a, g in deferred]
    result.deferred = sum(n for _, n in result.deferred_by_author)
    if not writable:
        result.message = (
            f"all {result.deferred} waiting: no proposer has linked an account"
        )
        return result

    domain.check_target_name(target_yaml)   # is the name usable at all?
    path = f"ontology/{target_yaml}"
    branch = f"kg/{target_yaml.removesuffix('.yaml')}-{clock.today()}"
    # Start from today's branch. If it does not exist yet the adapter falls
    # back to the base. Do not read from the base instead: proposals carried
    # by an earlier run today are no longer pending, so they would not be
    # re-applied, and writing the whole file back would delete them.
    before = source.read(path, ref=branch)
    # Empty means the file does not exist yet. This proposal creates a new
    # graph file, so start from an empty graph and register it in
    # workspace.yaml further down.
    creating = not before.strip()
    db = load(before)

    # After each person's proposals are applied, snapshot the whole file as
    # a commit candidate. They accumulate, so a later commit contains the
    # earlier people's changes too — that is what "stacking" means, and
    # GitHub works out the diffs.
    outcome = domain.Outcome()
    commits: list[tuple[str, str, list[domain.Proposal]]] = []
    for author, group in writable:
        mine = domain.apply(db, group)
        outcome.extend(mine)
        if mine.changed:
            commits.append((author, dump(db), mine.applied))

    result.applied = len(outcome.applied)
    result.refused = len(outcome.refused)
    result.authors = [a for a, _, _ in commits]

    # Write refusals back first, whether or not a PR happens. Failing to do
    # that leaves the proposer looking at a queue where their proposal
    # simply vanished.
    if outcome.refused:
        queue.mark_refused([(p.id, why) for p, why in outcome.refused])

    if not commits:
        result.message = (f"all {len(outcome.refused)} refused by the guard; "
                          "no PR")
        return result

    source.ensure_branch(branch)
    for author, content, applied in commits:
        source.write(path, content, branch=branch, as_author=author,
                     message=domain.commit_message(author, applied, target_yaml))

    # A new graph file is invisible until workspace.yaml points at it. An
    # unregistered file is read by nobody while the PR still says "done",
    # so the registration goes in the same PR, always. It is committed under
    # the last author's name because it is part of their proposal.
    if creating:
        ws = "ontology/workspace.yaml"
        registrar = commits[-1][0]
        source.write(
            ws, domain.register_in_workspace(source.read(ws, ref=branch),
                                             target_yaml),
            branch=branch, as_author=registrar,
            message=f"kg(workspace): register {target_yaml}")
        result.created = target_yaml

    title, body = domain.describe(outcome, target_yaml, deferred=deferred)
    pr_url = source.open_pr(branch=branch, title=title, body=body)

    # A proposal has only been carried once its PR URL is written back. If
    # anything above fails it stays pending and the next run picks it up.
    # Being read twice is safer than being carried twice, hence this order —
    # and re-reading cannot duplicate anything: the starting point is the
    # previous branch, and adding the same triple twice collapses into one.
    queue.mark_queued([p.id for p in outcome.applied], pr_url)

    result.pr_url = pr_url
    result.message = (f"carried {result.applied} in {len(commits)} commit(s)")
    if result.deferred:
        result.message += f" ({result.deferred} waiting on account linking)"
    return result
