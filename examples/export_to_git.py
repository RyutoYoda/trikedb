#!/usr/bin/env python3
"""Turn a day of writing into one pull request.

This is the other half of ``examples/streamlit_app.py``. People curate the
graph through a screen that has no git in it — it writes straight to a row in
a warehouse, because that is the only write surface a non-engineer will
actually use. Once a day this reads that row back, writes it out as YAML in a
repo, and opens a pull request with whatever accumulated.

What moves is *when* review happens, not whether::

    before:  write -> pull request -> review -> the fact is in the graph
    here:    write -> the fact is in the graph -> pull request -> review

The half you keep is the half that catches the dangerous mistakes: the
ontology guard runs on every write, so an undeclared predicate, an edge
written backwards and an action whose precondition never happened are all
refused at the screen and never reach the table. What review adds on top is
judgement — *is this true?* — and that can be read once a day without much
harm for a curated graph. If a wrong-but-well-formed fact is expensive for
some predicate (who owns what, which service is live, who may read a table),
that predicate is the one to keep behind a gate instead.

Run it::

    export TRIKEDB_GRAPH=snowflake://DB.SCHEMA.TABLE/sales/crm
    uv run --with 'trikedb[snowflake]' examples/export_to_git.py \\
        --into ontology/graph.yaml

Warehouse credentials come from the environment the connector already reads
(SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, and a key or password) — nothing is
configured here and nothing is stored. ``--dry-run`` prints the diff and
writes nothing.

One thing to know before the first run: the export is generated from the
graph, so if the file in the repo was hand-written, the first pull request
reflows it and drops any comments in it. Land that once as its own commit and
every run after it is an honest diff.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from trikedb import TrikeDB


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def run(repo: Path, *args: str) -> str:
    """A git command that has to work, so a failure stops the run."""
    r = git(repo, *args)
    if r.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed:\n{r.stderr or r.stdout}")
    return r.stdout.strip()


def compare_url(repo: Path, branch: str, base: str) -> str | None:
    """Where a person would open the pull request by hand, if `gh` is absent."""
    remote = git(repo, "remote", "get-url", "origin").stdout.strip()
    m = re.match(r"(?:git@|https://)([^:/]+)[:/](.+?)(?:\.git)?$", remote)
    if not m:
        return None
    host, slug = m.groups()
    return f"https://{host}/{slug}/compare/{base}...{branch}?expand=1"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--graph", default=os.environ.get("TRIKEDB_GRAPH"),
                    help="the graph to export, e.g. "
                         "snowflake://DB.SCHEMA.TABLE/sales/crm "
                         "(default: $TRIKEDB_GRAPH)")
    ap.add_argument("--into", default=os.environ.get("TRIKEDB_EXPORT",
                                                     "ontology/graph.yaml"),
                    help="where to write it inside the repo")
    ap.add_argument("--repo", default=None,
                    help="the git repository (default: wherever --into is)")
    ap.add_argument("--base", default="main", help="branch the PR targets")
    ap.add_argument("--branch", default=None,
                    help="branch to push (default: graph/<today>)")
    ap.add_argument("--dry-run", action="store_true",
                    help="write the file, show the diff, commit nothing")
    args = ap.parse_args(argv)

    if not args.graph:
        ap.error("no graph given — pass --graph or set TRIKEDB_GRAPH")

    into = Path(args.into)
    repo = Path(args.repo) if args.repo else into.resolve().parent
    if git(repo, "rev-parse", "--is-inside-work-tree").returncode != 0:
        sys.exit(f"{repo} is not a git repository")

    # autosave=False because this direction is read-only in spirit: nothing
    # here should ever write back to the row people are still typing into.
    into.parent.mkdir(parents=True, exist_ok=True)
    db = TrikeDB(args.graph, autosave=False)
    path = str(into.resolve())

    if args.dry_run:
        db.save(into)
        print(run(repo, "diff", "--", path) or "no change since the last export")
        return 0

    today = dt.date.today().isoformat()
    branch = args.branch or f"graph/{today}"

    # Cut the branch from --base, not from wherever HEAD happens to sit: each
    # pull request should be the base plus today's curation and nothing else.
    # -C rather than -c because the branch is named after the day, so a second
    # run on the same day replaces its own work instead of failing on the name.
    start = run(repo, "rev-parse", "--abbrev-ref", "HEAD")
    run(repo, "switch", "-C", branch, args.base)
    db.save(into)
    facts, objects = len(db), len(db.nodes())

    if git(repo, "diff", "--quiet", "--", path).returncode == 0:
        run(repo, "switch", start)
        print(f"{into}: no change since the last export — nothing to review")
        return 0

    title = f"graph: curation through {today}"
    body = (
        f"Exported from `{args.graph}` by `examples/export_to_git.py`.\n\n"
        f"The graph now holds **{facts} facts** across **{objects} objects**. "
        "Every line below was written through the curation screen and passed "
        "the ontology guard on the way in; what is left to check is whether "
        "it is *true*.\n"
    )

    run(repo, "add", "--", path)
    run(repo, "commit", "-m", title)
    run(repo, "push", "--force-with-lease", "-u", "origin", branch)

    if shutil.which("gh"):
        pr = subprocess.run(
            ["gh", "pr", "create", "--base", args.base, "--head", branch,
             "--title", title, "--body", body],
            cwd=repo, capture_output=True, text=True,
        )
        # An existing PR for this branch is the normal case on a second run
        # of the same day, and it already points at the new commit.
        if pr.returncode == 0:
            print(pr.stdout.strip())
            return 0
        print(pr.stderr.strip(), file=sys.stderr)

    url = compare_url(repo, branch, args.base)
    print(f"pushed {branch}. Open the pull request here:\n  {url}" if url
          else f"pushed {branch} — open a pull request against {args.base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
