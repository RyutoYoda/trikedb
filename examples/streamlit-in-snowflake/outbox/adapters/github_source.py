"""The source of truth: GitHub, reached over the REST API only.

There is no git binary inside a Streamlit in Snowflake app, so cloning is
not an option. It would not be worth it anyway: the whole job is "read one
file, make a branch, write, open a PR", and four API calls are smaller than
shipping git would be.

Each person's commits are made with **the token they registered**. GitHub
treats them as commits that person made themselves, so who proposed what
survives in the history, not only in the PR body. The author email is
`<login>@users.noreply.github.com` — GitHub's standard form for attributing
a commit to an account without putting a real address in public.
"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

from .tokens import Credential

_API = "https://api.github.com"


class GitHubSource:
    def __init__(self, repo: str,
                 credentials: Callable[[str], Optional[Credential]],
                 *, base: str = "main") -> None:
        self._repo = repo            # "owner/name"
        self._credentials = credentials
        self._base = base
        #: Used for operations where any one person's credential will do —
        #: read, ensure_branch, open_pr. Filled in as soon as the first
        #: person who can write is identified.
        self._acting: Optional[Credential] = None

    # ------------------------------------------------------------ GraphSource

    def can_write(self, author: str) -> bool:
        cred = self._credentials(author)
        if cred and self._acting is None:
            self._acting = cred
        return cred is not None

    def read(self, path: str, *, ref: str = "") -> str:
        """From `ref` if given, otherwise (if not branched yet) from base.

        On the second run of a day, `ref` is that day's branch. Reading from
        the base again would drop what the first run wrote, so when the
        branch exists it is the correct starting point.

        Absent from both, the empty string. For a proposal that creates a
        new graph file that is the correct starting point: an empty graph.
        """
        blob = None
        if ref:
            blob = self._maybe("GET", f"/repos/{self._repo}/contents/{path}"
                                      f"?ref={ref}")
        if blob is None:
            blob = self._maybe("GET", f"/repos/{self._repo}/contents/{path}"
                                      f"?ref={self._base}")
        if blob is None:
            return ""
        return base64.b64decode(blob["content"]).decode("utf-8")

    def ensure_branch(self, branch: str) -> None:
        """Branch from base. If it exists already, leave it alone.

        This used to force the branch back to base, on the theory that a
        second run in one day would otherwise duplicate the first run's
        work. It would not: adding the same triple twice collapses into
        one. What the reset actually did was **delete the commits the first
        run made that day.** Those proposals are no longer pending, so they
        are not re-applied either; they disappear from the PR while their
        queue rows go on claiming they were carried. Now it only ever adds,
        and the starting point is lined up by `read(ref=branch)` instead.
        """
        try:
            head = self._call("GET", f"/repos/{self._repo}/git/ref/heads/{self._base}")
            self._call("POST", f"/repos/{self._repo}/git/refs",
                       {"ref": f"refs/heads/{branch}", "sha": head["object"]["sha"]})
        except urllib.error.HTTPError as exc:
            if exc.code != 422:          # 422 = already there, which is fine
                raise

    def write(self, path: str, content: str, *, branch: str, message: str,
              as_author: str) -> None:
        cred = self._credentials(as_author)
        if cred is None:                 # service checks can_write first
            raise RuntimeError(f"{as_author} has not linked a GitHub account")
        login = cred.gh_login or as_author
        payload: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch,
            "author": {
                "name": login,
                "email": f"{login}@users.noreply.github.com",
            },
        }
        existing = self._maybe("GET", f"/repos/{self._repo}/contents/{path}"
                                      f"?ref={branch}", cred=cred)
        if existing:                      # updating needs the old blob sha
            payload["sha"] = existing["sha"]
        self._call("PUT", f"/repos/{self._repo}/contents/{path}", payload, cred=cred)

    def open_pr(self, *, branch: str, title: str, body: str) -> str:
        try:
            pr = self._call("POST", f"/repos/{self._repo}/pulls", {
                "title": title, "body": body,
                "head": branch, "base": self._base,
            })
            return pr["html_url"]
        except urllib.error.HTTPError as exc:
            if exc.code != 422:
                raise
            # Second run of the same day. The existing PR already points at
            # this branch, so do not reopen it; refresh the body instead.
            open_prs = self._call(
                "GET", f"/repos/{self._repo}/pulls"
                       f"?head={self._repo.split('/')[0]}:{branch}&state=open")
            if not open_prs:
                raise
            pr = open_prs[0]
            self._call("PATCH", f"/repos/{self._repo}/pulls/{pr['number']}",
                       {"body": body})
            return pr["html_url"]

    # ------------------------------------------------------------------- http

    def _maybe(self, method: str, path: str, *,
               cred: Optional[Credential] = None) -> Optional[dict]:
        try:
            return self._call(method, path, cred=cred)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def _call(self, method: str, path: str, payload: Optional[dict] = None,
              *, cred: Optional[Credential] = None):
        cred = cred or self._acting
        if cred is None:
            raise RuntimeError("no usable GitHub credential")
        req = urllib.request.Request(
            _API + path, method=method,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={
                "Authorization": f"Bearer {cred.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "kg-outbox",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or b"null")
