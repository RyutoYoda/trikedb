"""The three holes in the outside world. `service` knows only these types.

They are Protocols, so implementations do not subclass anything. A test
passes any object with the right shape and touches no network.

**Note that a token never appears here.** "Whose credentials do we write
with" is a question the GraphSource implementation answers privately.
The service layer knows who wrote a proposal and stops there; it never
handles that person's credentials.
"""
from __future__ import annotations

from typing import Protocol, Sequence

from .domain import Proposal


class ProposalQueue(Protocol):
    """Where proposals pile up (a Snowflake table, in the real adapter)."""

    def pending(self, target_yaml: str) -> Sequence[Proposal]:
        """Proposals not yet carried by a PR, oldest first."""

    def mark_queued(self, ids: Sequence[str], pr_url: str) -> None:
        """Record the PR URL against the proposals it carried."""

    def mark_refused(self, refusals: Sequence[tuple[str, str]]) -> None:
        """Record why a proposal was refused. Pairs of (id, reason)."""


class GraphSource(Protocol):
    """The repository that owns the graph (GitHub, in the real adapter).

    `write` takes `as_author` so the commit belongs to the person who made
    the proposal. Which credentials make that possible is the
    implementation's business: if they have linked an account, theirs; if
    not, `can_write` returns False and the proposal waits.
    """

    def read(self, path: str, *, ref: str = "") -> str:
        """The current content — from `ref` if given, else from the base.

        `ref` exists because drain can run more than once in a day. Reading
        from the base each time would silently **drop** everything the
        earlier run already wrote: those proposals are no longer pending,
        so they are not in hand to re-apply, and the full file we write
        back would not contain them. Reading from the branch accumulates.

        **A file that does not exist yet is the empty string,** not an
        error. Proposing a brand new graph file goes through this path, so
        "not there" is a starting point rather than a failure.
        """

    def can_write(self, author: str) -> bool:
        """Can we commit under this person's name (have they linked one)?"""

    def ensure_branch(self, branch: str) -> None:
        """Branch from base. If it already exists, leave it alone."""

    def write(self, path: str, content: str, *, branch: str, message: str,
              as_author: str) -> None:
        """Add one commit to `branch`, authored by `as_author`."""

    def open_pr(self, *, branch: str, title: str, body: str) -> str:
        """Open the PR (or update the body of the existing one); return URL."""


class Clock(Protocol):
    """Only the date, for the branch name. A port so tests can freeze it."""

    def today(self) -> str:
        ...
