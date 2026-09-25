"""Composition root. **Every proper noun in this package is in this file.**

domain and service get to know nothing about the outside world because every
"which one do we use" decision has been pulled up here. Read this file and
you have seen the complete list of external things this path touches.

If you are copying this example, this is the file you edit. Nothing else in
`outbox/` mentions your database, your schema, or your repository.

The app talks to GitHub directly from the user's own session. That is not
just one fewer moving part than a scheduled job would be — it means there is
**no shared token and no shared role**: the PR is opened by whoever pressed
the button, using the one credential they registered themselves.

Getting out of Snowflake at all needs exactly one hole, which you create
once (see setup.sql):

    NETWORK RULE  GITHUB_NETWORK_RULE          api.github.com:443
    INTEGRATION   GITHUB_ACCESS_INTEGRATION    (that rule and nothing else)

Without it the app cannot reach the network. With it, it can reach
api.github.com on 443 and nowhere else.
"""
from __future__ import annotations

from . import service
from .adapters import graph_codec
from .adapters.clock import SystemClock
from .adapters.github_source import GitHubSource
from .adapters.queue import SnowflakeQueue
from .adapters.tokens import SnowflakeTokens

# --------------------------------------------------------------- change these
TABLE = "DEMO_DB.KG.KG_OUTBOX"
TOKEN_TABLE = "DEMO_DB.KG.KG_OUTBOX_TOKEN"
REPO = "your-org/your-graph-repo"
BASE = "main"
# -----------------------------------------------------------------------------


def drain(session, target_yaml: str, *, author: str) -> dict:
    """Turn the queued proposals into one PR. Runs in the presser's session.

    `author` is **the person who pressed the button.** It is required
    because this is the only place it can be supplied from.

    That the run is not limited to *their* proposals is deliberate. If other
    people have proposals queued against the same file, the service asks
    whether we can write as them — and the answer is always no, so their
    proposals stay pending until they press the button on their own screen.
    In other words, **you cannot push somebody else's work out under your
    own credentials, and the fact that you could not shows up in the PR
    body** as a deferral.

    That "always no" is guaranteed both by the row access policy and by this
    `author` being handed to `SnowflakeTokens`. Why both, in adapters/tokens.py.
    """
    creds = SnowflakeTokens(session, TOKEN_TABLE, author)
    result = service.drain(
        target_yaml=target_yaml,
        queue=SnowflakeQueue(session, TABLE),
        source=GitHubSource(REPO, creds.for_author, base=BASE),
        clock=SystemClock(),
        load=graph_codec.load,
        dump=graph_codec.dump,
    )
    # Stamp the row of everyone whose credential was used, so the screen can
    # show "last used". An expired token shows up as this going stale.
    for used in result.authors:
        creds.mark_used(used)
    return result.as_dict()
