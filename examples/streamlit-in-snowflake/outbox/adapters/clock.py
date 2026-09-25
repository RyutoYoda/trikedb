"""The date. It only reaches a branch name, but tests want it frozen."""
from __future__ import annotations

import datetime as _dt

#: Dates in branch names should match the "today" of the people reading
#: them. Set this to the timezone your reviewers live in.
TIMEZONE = _dt.timezone(_dt.timedelta(hours=9))


class SystemClock:
    def today(self) -> str:
        return _dt.datetime.now(TIMEZONE).date().isoformat()
