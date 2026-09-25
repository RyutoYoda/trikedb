"""The proposal queue: a Snowflake table.

State is one column, STATUS:

    pending   saved from the screen, not carried by a PR yet
    queued    carried; PR_URL points at the PR
    refused   the guard would not take it; ERROR says why

There is no `merged`. Whether a PR was merged is something GitHub knows;
copying it here would only be a second copy to keep correct. Follow PR_URL.
"""
from __future__ import annotations

import json
from typing import Sequence

from ..domain import Proposal
from .sql import execute


class SnowflakeQueue:
    def __init__(self, session, table: str) -> None:
        self._session = session
        self._table = table

    def pending(self, target_yaml: str) -> Sequence[Proposal]:
        rows = execute(
            self._session,
            f"SELECT ID, AUTHOR, TARGET_YAML, OP, TO_JSON(PAYLOAD), NOTE, PROV "
            f"FROM {self._table} "
            f"WHERE STATUS = 'pending' AND TARGET_YAML = ? "
            f"ORDER BY CREATED_AT",
            [target_yaml],
        )
        return [
            Proposal(
                id=str(r[0]), author=r[1], target_yaml=r[2], op=r[3],
                payload=json.loads(r[4]) if r[4] else {},
                note=r[5] or "", prov=r[6] or "",
            )
            for r in rows
        ]

    def mark_queued(self, ids: Sequence[str], pr_url: str) -> None:
        if not ids:
            return
        holes = ", ".join(["?"] * len(ids))
        execute(
            self._session,
            f"UPDATE {self._table} SET STATUS = 'queued', PR_URL = ?, "
            f"PROCESSED_AT = CURRENT_TIMESTAMP() WHERE ID IN ({holes})",
            [pr_url, *ids],
        )

    def mark_refused(self, refusals: Sequence[tuple[str, str]]) -> None:
        # The reason differs per proposal, so one statement each. A day's
        # proposals number in the tens at most, and a readable loop beats a
        # CASE expression assembled to save round trips.
        for pid, why in refusals:
            execute(
                self._session,
                f"UPDATE {self._table} SET STATUS = 'refused', ERROR = ?, "
                f"PROCESSED_AT = CURRENT_TIMESTAMP() WHERE ID = ?",
                [why[:4000], pid],
            )
