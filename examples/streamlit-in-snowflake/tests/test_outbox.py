"""The rules and the procedure in `outbox`, under test.

Nothing here touches Snowflake, or GitHub, or even Streamlit. Being able
to write these tests *at all* is the proof of the claim that `domain` and
`service` know nothing about the outside world (`TestLayering` at the
bottom states that in so many words).

    cd examples/streamlit-in-snowflake
    uv run --with trikedb python -m unittest discover -s tests -v
"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import types
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from trikedb import TrikeDB  # noqa: E402

from outbox import domain, service  # noqa: E402
from outbox.adapters import graph_codec  # noqa: E402


def a_graph() -> str:
    """A small graph file with two predicates declared.

    BUILT_BY only allows model -> team, so it can be used to test an edge
    pointing the wrong way.
    """
    with tempfile.TemporaryDirectory() as d:
        path = pathlib.Path(d) / "graph.yaml"
        db = TrikeDB(path)
        db.declare_link("BUILT_BY", domain="model", range="team",
                        description="the team that owns this model")
        db.declare_link("READS_FROM", domain="model", range="table",
                        description="the table it reads from")
        db.set_node("model-a", type="model")
        db.set_node("model-b", type="model")
        db.set_node("team-x", type="team")
        db.set_node("table-1", type="table")
        db.save(path)
        return path.read_text(encoding="utf-8")


WORKSPACE = "ontology/workspace.yaml"

#: The same shape as a real one. The point is that the leading comment and
#: the ordering survive, so it is copied as-is rather than tidied up.
A_WORKSPACE = """\
# Knowledge graph union view (read-only union)
# Regenerate: uvx --from trikedb trikedb html ontology/workspace.yaml -o docs/index.html
graphs:
  snowflake: snowflake.yaml
  dbt: dbt.yaml
"""


def proposal(**kw) -> domain.Proposal:
    base = dict(
        id="p1", author="someone", target_yaml="dbt.yaml", op="add_triple",
        payload={"s": "model-a", "p": "BUILT_BY", "o": "team-x"},
        note="confirmed the owner during an inventory review",
        prov="https://example.invalid/ticket/1",
    )
    base.update(kw)
    return domain.Proposal(**base)


# --------------------------------------------------------------------- domain

class TestApply(unittest.TestCase):

    def setUp(self) -> None:
        self.db = graph_codec.load(a_graph())

    def test_add_triple_lands_with_prov_and_note(self):
        out = domain.apply(self.db, [proposal()])

        self.assertEqual(len(out.applied), 1)
        self.assertEqual(out.refused, [])
        hits = self.db.query(["model-a BUILT_BY ?team"])
        self.assertEqual([h["team"] for h in hits], ["team-x"])
        # The why and the source come off the proposal automatically. The
        # screen is given no opportunity to leave them out.
        triple = next(self.db.triples(s="model-a", p="BUILT_BY"))
        self.assertEqual(triple.attrs.get("note"),
                         "confirmed the owner during an inventory review")
        self.assertEqual(triple.attrs.get("prov"),
                         "https://example.invalid/ticket/1")

    def test_set_node_lands(self):
        out = domain.apply(self.db, [proposal(
            op="set_node",
            payload={"name": "model-a", "props": {"owner_team": "team-x"}},
        )])

        self.assertEqual(len(out.applied), 1)
        self.assertEqual(self.db.node("model-a").get("owner_team"), "team-x")

    def test_undeclared_predicate_is_refused(self):
        out = domain.apply(self.db, [proposal(
            payload={"s": "model-a", "p": "INVENTED_BY", "o": "team-x"})])

        self.assertEqual(out.applied, [])
        self.assertEqual(len(out.refused), 1)
        self.assertIn("INVENTED_BY", out.refused[0][1])

    def test_backwards_edge_is_refused(self):
        """team BUILT_BY model points the wrong way. This is what the guard
        is looking at."""
        out = domain.apply(self.db, [proposal(
            payload={"s": "team-x", "p": "BUILT_BY", "o": "model-a"})])

        self.assertEqual(out.applied, [])
        self.assertEqual(len(out.refused), 1)

    def test_blank_note_is_refused(self):
        out = domain.apply(self.db, [proposal(note="   ")])
        self.assertIn("note", out.refused[0][1])

    def test_blank_prov_is_refused(self):
        out = domain.apply(self.db, [proposal(prov="")])
        self.assertIn("prov", out.refused[0][1])

    def test_a_new_predicate_can_be_declared(self):
        out = domain.apply(self.db, [proposal(
            op="declare_link",
            payload={"name": "OWNED_BY", "description": "table -> owning team"})])

        self.assertEqual(len(out.applied), 1, out.refused)
        self.assertIn("OWNED_BY", self.db.ontology)

    def test_a_new_predicate_can_be_used_in_the_same_batch(self):
        """A declaration and a triple that uses it arrive together, because
        that is how the screen submits them."""
        out = domain.apply(self.db, [
            proposal(id="decl", op="declare_link",
                     payload={"name": "OWNED_BY", "description": "table -> team"}),
            proposal(id="use", payload={"s": "table-1", "p": "OWNED_BY",
                                        "o": "team-x"}),
        ])

        self.assertEqual([p.id for p in out.applied], ["decl", "use"])

    def test_a_lowercase_predicate_is_refused(self):
        """Spelling drift is the whole reason for keeping the vocabulary
        narrow."""
        out = domain.apply(self.db, [proposal(
            op="declare_link",
            payload={"name": "owned_by", "description": "table -> team"})])
        self.assertIn("UPPER_SNAKE", out.refused[0][1])

    def test_a_predicate_without_a_description_is_refused(self):
        out = domain.apply(self.db, [proposal(
            op="declare_link", payload={"name": "OWNED_BY"})])
        self.assertIn("description", out.refused[0][1])

    def test_redeclaring_an_existing_predicate_is_refused(self):
        """An existing predicate quietly changing meaning is worse than not
        being able to say something."""
        out = domain.apply(self.db, [proposal(
            op="declare_link",
            payload={"name": "BUILT_BY", "description": "something else entirely"})])
        self.assertIn("already exists", out.refused[0][1])

    def test_path_in_target_yaml_is_refused(self):
        out = domain.apply(self.db, [proposal(target_yaml="../../etc/passwd")])
        self.assertEqual(out.applied, [])

    def test_one_bad_proposal_does_not_stop_the_rest(self):
        out = domain.apply(self.db, [
            proposal(id="bad", payload={"s": "model-a", "p": "NOPE", "o": "team-x"}),
            proposal(id="good", payload={"s": "model-b", "p": "READS_FROM",
                                         "o": "table-1"}),
        ])

        self.assertEqual([p.id for p in out.applied], ["good"])
        self.assertEqual([p.id for p, _ in out.refused], ["bad"])


class TestEmptyOntology(unittest.TestCase):
    """A graph with no vocabulary at all = the starting point of a new file.

    trikedb lets any predicate through while the ontology is empty
    (measured, not assumed). A brand new graph file starts in exactly that
    state, so letting it past here would produce one graph file with no
    working guard. Unioned into the workspace it looks correct, because the
    other files supply vocabulary — which means it is noticed much later.
    """

    def setUp(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "empty.yaml"
            TrikeDB(path).save(path)
            self.db = graph_codec.load(path.read_text(encoding="utf-8"))
        self.assertEqual(self.db.ontology, {})

    def test_add_triple_is_refused(self) -> None:
        out = domain.apply(self.db, [proposal()])
        self.assertFalse(out.applied)
        self.assertIn("BUILT_BY", out.refused[0][1])

    def test_declare_then_use(self) -> None:
        out = domain.apply(self.db, [
            proposal(id="decl", op="declare_link",
                     payload={"name": "COSTS",
                              "description": "monthly cost of that warehouse"}),
            proposal(id="use", payload={"s": "wh-a", "p": "COSTS",
                                        "o": "money-1"}),
        ])
        self.assertEqual(len(out.applied), 2, out.refused)


class TestDescribe(unittest.TestCase):

    def test_body_carries_the_why_and_the_source(self):
        db = graph_codec.load(a_graph())
        out = domain.apply(db, [
            proposal(id="ok", author="someone"),
            proposal(id="ng", author="other", note=""),
        ])
        title, body = domain.describe(out, "dbt.yaml")

        self.assertIn("dbt.yaml", title)
        self.assertIn("1 proposal(s)", title)
        self.assertIn("confirmed the owner during an inventory review", body)
        self.assertIn("https://example.invalid/ticket/1", body)
        self.assertIn("### 1 proposal(s) refused", body)

    def test_a_vocabulary_change_is_called_out_separately(self):
        """Adding a fact and adding a word are not the same weight of
        review."""
        db = graph_codec.load(a_graph())
        out = domain.apply(db, [
            proposal(id="decl", op="declare_link",
                     payload={"name": "OWNED_BY", "description": "table -> team"}),
            proposal(id="fact"),
        ])
        _, body = domain.describe(out, "dbt.yaml")

        self.assertIn("1 proposal(s) add to the vocabulary", body)
        self.assertIn("`OWNED_BY`", body)
        # It has not disappeared from the main table (it is in both)
        self.assertIn("### The proposals", body)

    def test_a_pipe_in_a_note_does_not_break_the_table(self):
        db = graph_codec.load(a_graph())
        out = domain.apply(db, [proposal(note="a | b\nc")])
        _, body = domain.describe(out, "dbt.yaml")

        row = [ln for ln in body.splitlines() if "a \\| b" in ln]
        self.assertEqual(len(row), 1)
        self.assertEqual(row[0].count("|"), 8)  # 6 columns of separators + 2 escaped


# ---------------------------------------------------------------------- fakes

class FakeQueue:
    """Like the real one: once a proposal is queued it never comes back as
    pending.

    Returning everything every time would let a second drain on the same
    day re-apply the first drain's proposals, which hides the defect.
    """

    def __init__(self, proposals=()):
        self._proposals = list(proposals)
        self.queued: list[tuple[list[str], str]] = []
        self.refused: list[tuple[str, str]] = []
        self._done: set[str] = set()

    def pending(self, target_yaml):
        return [p for p in self._proposals
                if p.target_yaml == target_yaml and p.id not in self._done]

    def add(self, *proposals):
        """Proposals piled on later the same day."""
        self._proposals.extend(proposals)

    def mark_queued(self, ids, pr_url):
        self.queued.append((list(ids), pr_url))
        self._done.update(ids)

    def mark_refused(self, refusals):
        self.refused.extend(refusals)
        self._done.update(pid for pid, _ in refusals)


class FakeSource:
    """Stands in for GitHub. `registered` decides whose credentials exist.

    None means "everybody is registered". Like the real one, commits stack,
    so commits[i]["content"] contains every change up to and including i.
    """

    def __init__(self, text=None, *, fail=False, registered=None, files=None):
        #: Contents per path. A path that is not here does not exist yet,
        #: and reads back as an empty string.
        self.files = dict(files or {})
        #: The contents of any ontology/*.yaml not named explicitly. The
        #: older tests only ever look at one target file, so that one stays
        #: a positional argument.
        self._default = text
        self.fail = fail
        self._registered = registered
        self.branches: list[str] = []
        self.commits: list[dict] = []
        self.prs: list[dict] = []

    def read(self, path, *, ref=""):
        """Like the real one: if the branch already exists, read from it.

        Pinning this to `text` would keep the defect in the twice-in-one-day
        path out of the tests. A missing path returns an empty string rather
        than raising — creating a new graph file starts from exactly that.
        """
        if ref and ref in self.branches:
            for c in reversed(self.commits):
                if c["branch"] == ref and c["path"] == path:
                    return c["content"]
        if path in self.files:
            return self.files[path]
        if self._default is not None and path != WORKSPACE:
            return self._default
        return ""

    def can_write(self, author):
        return self._registered is None or author in self._registered

    def ensure_branch(self, branch):
        # Like the real one: if it exists, do nothing (never rewind)
        if branch not in self.branches:
            self.branches.append(branch)

    def write(self, path, content, *, branch, message, as_author):
        assert self.can_write(as_author), as_author
        self.commits.append({"path": path, "content": content, "branch": branch,
                             "message": message, "author": as_author})

    def open_pr(self, *, branch, title, body):
        if self.fail:
            raise RuntimeError("GitHub is down")
        self.prs.append({"branch": branch, "title": title, "body": body})
        return "https://example.invalid/pr/1"


class FrozenClock:
    def today(self):
        return "2026-09-23"


def drain(queue, source, target_yaml="dbt.yaml"):
    return service.drain(
        target_yaml=target_yaml, queue=queue, source=source, clock=FrozenClock(),
        load=graph_codec.load, dump=graph_codec.dump,
    )


# -------------------------------------------------------------------- service

class TestDrain(unittest.TestCase):

    def test_no_proposals_opens_no_pull_request(self):
        source = FakeSource(a_graph())
        result = drain(FakeQueue(), source)

        self.assertIsNone(result.pr_url)
        self.assertEqual(source.commits, [])
        self.assertEqual(result.message, "nothing proposed")

    def test_all_refused_opens_no_pull_request_but_writes_back_why(self):
        queue = FakeQueue([proposal(note="")])
        source = FakeSource(a_graph())
        result = drain(queue, source)

        self.assertIsNone(result.pr_url)
        self.assertEqual(source.commits, [])
        self.assertEqual(result.refused, 1)
        self.assertEqual(queue.refused[0][0], "p1")
        self.assertEqual(queue.queued, [])

    def test_happy_path(self):
        queue = FakeQueue([proposal()])
        source = FakeSource(a_graph())
        result = drain(queue, source)

        self.assertEqual(result.applied, 1)
        self.assertEqual(result.pr_url, "https://example.invalid/pr/1")
        self.assertEqual(source.branches, ["kg/dbt-2026-09-23"])

        commit = source.commits[0]
        self.assertEqual(commit["path"], "ontology/dbt.yaml")
        self.assertEqual(commit["branch"], "kg/dbt-2026-09-23")
        self.assertEqual(commit["author"], "someone")
        # The why goes in the commit as well as the PR body. A PR can be
        # deleted; the history stays.
        self.assertIn("confirmed the owner during an inventory review",
                      commit["message"])
        # What lands in the PR is the graph, not the body. Read it back and
        # check the fact is in there.
        self.assertEqual(
            [h["team"] for h in graph_codec.load(commit["content"])
             .query(["model-a BUILT_BY ?team"])],
            ["team-x"],
        )
        self.assertEqual(queue.queued, [(["p1"], "https://example.invalid/pr/1")])

    def test_a_failed_pull_request_leaves_the_proposal_pending(self):
        """On a day where no PR was opened, do not mark anything queued.

        Being picked up again on the next run is the correct outcome: read
        twice is safer than carried twice.
        """
        queue = FakeQueue([proposal()])
        with self.assertRaises(RuntimeError):
            drain(queue, FakeSource(a_graph(), fail=True))

        self.assertEqual(queue.queued, [])

    def test_the_graph_is_not_rewritten_when_nothing_is_applied(self):
        source = FakeSource(a_graph())
        drain(FakeQueue([proposal(op="declare_link", payload={})]), source)
        self.assertEqual(source.commits, [])
        self.assertEqual(source.branches, [])


# --------------------------------------------------------- one commit each

class TestTwiceInOneDay(unittest.TestCase):
    """Draining twice in one day must not lose the first drain's change.

    This is what was broken. The whole file is rewritten on every run, yet
    the starting point was re-read from the base every time, and the branch
    was force-reset back to the base — so the second PR contained "main
    plus the second proposal" and nothing else. The first proposal was no
    longer pending, so it was never re-applied either, while its row kept
    claiming it had been carried. From the proposer's side their proposal
    simply vanished.
    """

    def setUp(self):
        self.queue = FakeQueue([proposal(id="first", author="alice")])
        self.source = FakeSource(a_graph())
        drain(self.queue, self.source)           # first run
        self.queue.add(proposal(id="second", author="bob",
                                payload={"s": "model-b", "p": "READS_FROM",
                                         "o": "table-1"}))
        self.result = drain(self.queue, self.source)   # second run, same day

    def test_the_second_run_keeps_the_first_runs_change(self):
        last = graph_codec.load(self.source.commits[-1]["content"])
        pairs = {(t.s, t.p, t.o) for t in last.triples()}

        self.assertIn(("model-a", "BUILT_BY", "team-x"), pairs)     # first run
        self.assertIn(("model-b", "READS_FROM", "table-1"), pairs)  # second run

    def test_the_second_run_does_not_re_apply_the_first(self):
        """The first proposal is queued, so it is not carried twice."""
        self.assertEqual(self.result.applied, 1)
        self.assertEqual([c["author"] for c in self.source.commits],
                         ["alice", "bob"])

    def test_the_branch_is_not_recreated(self):
        self.assertEqual(self.source.branches, ["kg/dbt-2026-09-23"])

    def test_it_stays_one_pull_request(self):
        self.assertEqual({pr["branch"] for pr in self.source.prs},
                         {"kg/dbt-2026-09-23"})


class TestPerAuthorCommits(unittest.TestCase):
    """One PR, one commit per person.

    The reason not to split into one PR per person is how the graph is
    stored: this path rewrites the whole YAML, so two PRs would both branch
    off main and whichever merged second would **erase** the one that
    merged first. Stacked onto one branch in order, GitHub works out the
    diffs and the problem does not arise.
    """

    def test_each_author_gets_their_own_commit_in_order(self):
        queue = FakeQueue([
            proposal(id="p1", author="alice"),
            proposal(id="p2", author="bob",
                     payload={"s": "model-b", "p": "READS_FROM", "o": "table-1"}),
            proposal(id="p3", author="alice",
                     payload={"s": "model-b", "p": "BUILT_BY", "o": "team-x"}),
        ])
        source = FakeSource(a_graph())
        result = drain(queue, source)

        # alice proposed twice, but it collapses into one commit per person.
        self.assertEqual([c["author"] for c in source.commits], ["alice", "bob"])
        self.assertEqual(result.authors, ["alice", "bob"])
        self.assertEqual(len(source.prs), 1)
        self.assertEqual(result.applied, 3)

    def test_a_later_commit_keeps_the_earlier_authors_change(self):
        """That the commits stack. If this breaks, later people erase
        earlier ones."""
        queue = FakeQueue([
            proposal(id="p1", author="alice"),
            proposal(id="p2", author="bob",
                     payload={"s": "model-b", "p": "READS_FROM", "o": "table-1"}),
        ])
        source = FakeSource(a_graph())
        drain(queue, source)

        last = graph_codec.load(source.commits[-1]["content"])
        self.assertEqual(len(last.query(["model-a BUILT_BY ?t"])), 1)
        self.assertEqual(len(last.query(["model-b READS_FROM ?t"])), 1)

    def test_an_unregistered_author_is_left_pending_not_refused(self):
        """A proposal from someone with no linked account is not deleted,
        not refused, and never carried under another person's name."""
        queue = FakeQueue([
            proposal(id="p1", author="alice"),
            proposal(id="p2", author="bob",
                     payload={"s": "model-b", "p": "READS_FROM", "o": "table-1"}),
        ])
        source = FakeSource(a_graph(), registered={"alice"})
        result = drain(queue, source)

        self.assertEqual([c["author"] for c in source.commits], ["alice"])
        self.assertEqual(result.deferred, 1)
        # Whose proposals are waiting comes back too. With only a count the
        # screen has to guess "somebody else's", and then says that about
        # the viewer's own proposals as well.
        self.assertEqual(result.deferred_by_author, [("bob", 1)])
        # bob is neither queued nor refused = still pending
        self.assertEqual(queue.queued, [(["p1"], "https://example.invalid/pr/1")])
        self.assertEqual(queue.refused, [])
        # bob's proposal has not leaked into the graph
        graph = graph_codec.load(source.commits[-1]["content"])
        self.assertEqual(graph.query(["model-b READS_FROM ?t"]), [])
        # The PR body says it is waiting, so bob can find out
        self.assertIn("bob", source.prs[0]["body"])
        self.assertIn("not linked a GitHub account", source.prs[0]["body"])

    def test_nobody_registered_means_no_branch_and_nothing_lost(self):
        queue = FakeQueue([proposal(author="alice")])
        source = FakeSource(a_graph(), registered=set())
        result = drain(queue, source)

        self.assertEqual(source.branches, [])
        self.assertEqual(source.commits, [])
        self.assertIsNone(result.pr_url)
        self.assertEqual(result.deferred, 1)
        self.assertEqual(result.deferred_by_author, [("alice", 1)])
        self.assertEqual(queue.queued, [])
        self.assertEqual(queue.refused, [])
        self.assertIn("no proposer has linked an account", result.message)

    def test_group_by_author_keeps_the_order_people_wrote_in(self):
        groups = domain.group_by_author([
            proposal(id="1", author="bob"),
            proposal(id="2", author="alice"),
            proposal(id="3", author="bob"),
        ])
        self.assertEqual([a for a, _ in groups], ["bob", "alice"])
        self.assertEqual([p.id for p in groups[0][1]], ["1", "3"])


class TestCredentialDoesNotLeak(unittest.TestCase):
    """Printing a credential by accident must not print the value.

    This is the adapter layer, so it sits apart from the domain tests.
    Application logs land outside Snowflake, where the masking policy does
    not reach, so every "print it by mistake" route gets closed one at a
    time.
    """

    def test_repr_hides_the_token(self):
        from outbox.adapters.tokens import Credential

        cred = Credential(token="zzprobe-not-a-real-token", gh_login="someone")
        self.assertNotIn("zzprobe", repr(cred))
        self.assertNotIn("zzprobe", f"{cred}")
        self.assertIn("someone", repr(cred))


class _FakeSession:
    """Pretends to be Snowpark. Having no `cursor` is the condition that
    matters (see adapters/sql.py)."""

    def __init__(self, rows: dict | None = None) -> None:
        self.rows = rows or {}
        self.queries: list[tuple[str, list]] = []

    def sql(self, sql: str, params=None):
        bound = list(params or [])
        self.queries.append((sql, bound))
        rows = ([self.rows[bound[-1]]]
                if "SELECT TOKEN" in sql and bound and bound[-1] in self.rows
                else [])
        return types.SimpleNamespace(collect=lambda: rows)


class TestTokensOnlyServeTheViewer(unittest.TestCase):
    """Nobody else's token is ever within reach.

    Snowflake's row access policy already guarantees this: the condition is
    `CURRENT_USER() = SF_USER`, and a policy expression is evaluated with
    the real user name even inside the app. This class is the second layer
    on purpose — it holds **one** identity and returns None for any other
    name **without querying at all**, so "tried to read someone else's row"
    can never be confused with "this person has no linked account".

    The overlap is deliberate. Reasoning about `CURRENT_USER()` inside a
    Streamlit in Snowflake app has already been gotten wrong here once
    (see adapters/tokens.py), and an invariant the SQL is assumed to be
    holding is exactly the kind that breaks without anyone noticing. It is
    pinned here instead.
    """

    def setUp(self):
        from outbox.adapters.tokens import SnowflakeTokens

        self.session = _FakeSession({
            "alice": ("alice-token", "alice-gh"),
            "bob": ("bob-token", "bob-gh"),
        })
        self.creds = SnowflakeTokens(self.session, "T", "alice")

    def test_the_viewer_gets_their_own(self):
        cred = self.creds.for_author("alice")
        self.assertIsNotNone(cred)
        self.assertEqual(cred.gh_login, "alice-gh")

    def test_someone_else_is_never_looked_up(self):
        self.assertIsNone(self.creds.for_author("bob"))
        # Not "the row came back empty" but "no query was made". This is a
        # place where the query would have worked.
        self.assertEqual(self.session.queries, [])

    def test_nobody_is_refused_outright(self):
        from outbox.adapters.tokens import SnowflakeTokens

        for nobody in ("", None):
            with self.assertRaises(ValueError):
                SnowflakeTokens(self.session, "T", nobody)

    def test_mark_used_does_not_touch_other_rows(self):
        from outbox.adapters.tokens import OtherPersonsToken

        with self.assertRaises(OtherPersonsToken):
            self.creds.mark_used("bob")
        self.assertEqual(self.session.queries, [])
        self.creds.mark_used("alice")
        self.assertTrue(any("LAST_USED_AT" in q for q, _ in self.session.queries))

    def test_a_masked_value_is_not_a_credential(self):
        from outbox.adapters.tokens import SnowflakeTokens

        session = _FakeSession({"alice": ("***", "alice-gh")})
        self.assertIsNone(
            SnowflakeTokens(session, "T", "alice").for_author("alice"))


# ------------------------------------------------------------------- layering

class TestTargetName(unittest.TestCase):
    """Which graph file names may be created."""

    def test_workspace_is_refused(self) -> None:
        # Writing straight to the union would flatten every graph it
        # unions into one file.
        with self.assertRaises(domain.Refused):
            domain.check_target_name("workspace.yaml")

    def test_existing_names_pass(self) -> None:
        for name in ("dbt.yaml", "cost_ops.yaml", "data_sources.yaml"):
            domain.check_target_name(name)

    def test_shape(self) -> None:
        for bad in ("Dbt.yaml", "9dbt.yaml", "dbt-ops.yaml", "../etc/passwd",
                    "dbt ops.yaml", ".yaml"):
            with self.assertRaises(domain.Refused, msg=bad):
                domain.check_target_name(bad)

    def test_key_is_the_stem(self) -> None:
        self.assertEqual(domain.graph_key("cost_ops.yaml"), "cost_ops")


class TestRegisterInWorkspace(unittest.TestCase):

    def test_appends_to_graphs(self) -> None:
        out = domain.register_in_workspace(A_WORKSPACE, "cost.yaml")
        self.assertIn("  cost: cost.yaml", out.splitlines())

    def test_keeps_comments_and_order(self) -> None:
        """That it splices a string in rather than round-tripping the YAML.

        The comment at the top carries the regeneration command; lose it and
        nobody knows how docs/index.html is built any more. The ordering is
        first-one-wins for attributes, so it means something too.
        """
        out = domain.register_in_workspace(A_WORKSPACE, "cost.yaml")
        lines = out.splitlines()
        self.assertTrue(lines[0].startswith("# Knowledge graph union view"))
        self.assertIn("Regenerate", lines[1])
        self.assertEqual(
            [ln.split(":")[0].strip() for ln in lines if ln.startswith("  ")],
            ["snowflake", "dbt", "cost"])

    def test_idempotent(self) -> None:
        # Draining twice in one day does not produce two lines.
        once = domain.register_in_workspace(A_WORKSPACE, "cost.yaml")
        self.assertEqual(domain.register_in_workspace(once, "cost.yaml"), once)

    def test_already_there_is_untouched(self) -> None:
        self.assertEqual(
            domain.register_in_workspace(A_WORKSPACE, "dbt.yaml"), A_WORKSPACE)

    def test_no_graphs_block(self) -> None:
        with self.assertRaises(domain.Refused):
            domain.register_in_workspace("# empty\n", "cost.yaml")


class TestNewGraph(unittest.TestCase):
    """Targeting a graph file that does not exist yet.

    A new one is a PR that writes **two files**. Creating the body alone
    leaves it out of the union in workspace.yaml, so neither the screen nor
    anything else can see it — "created but invisible" is the worst of the
    outcomes, so half of it is never allowed through on its own.
    """

    def setUp(self) -> None:
        self.source = FakeSource(files={WORKSPACE: A_WORKSPACE})
        self.queue = FakeQueue([proposal(
            id="p1", author="alice", target_yaml="cost.yaml",
            op="declare_link",
            payload={"name": "COSTS", "domain": "warehouse", "range": "money",
                     "description": "monthly cost of that warehouse"})])
        self.out = drain(self.queue, self.source, target_yaml="cost.yaml")

    def paths(self):
        return [c["path"] for c in self.source.commits]

    def test_writes_both_files(self) -> None:
        self.assertEqual(sorted(self.paths()),
                         ["ontology/cost.yaml", WORKSPACE])

    def test_reports_what_it_created(self) -> None:
        self.assertEqual(self.out.created, "cost.yaml")
        self.assertEqual(self.out.as_dict()["created"], "cost.yaml")

    def test_registers_in_the_union(self) -> None:
        ws = [c for c in self.source.commits if c["path"] == WORKSPACE][-1]
        self.assertIn("  cost: cost.yaml", ws["content"].splitlines())

    def test_body_starts_empty(self) -> None:
        """It starts from an empty graph. No existing file's contents have
        been mixed in."""
        body = [c for c in self.source.commits
                if c["path"] == "ontology/cost.yaml"][-1]
        db = graph_codec.load(body["content"])
        self.assertEqual(sorted(db.ontology), ["COSTS"])

    def test_registration_is_attributed_to_a_person(self) -> None:
        # Written with the proposer's credentials. No commit belonging to
        # nobody.
        ws = [c for c in self.source.commits if c["path"] == WORKSPACE][-1]
        self.assertEqual(ws["author"], "alice")

    def test_existing_yaml_touches_only_itself(self) -> None:
        source = FakeSource(a_graph(), files={WORKSPACE: A_WORKSPACE})
        out = drain(FakeQueue([proposal()]), source)
        self.assertEqual([c["path"] for c in source.commits],
                         ["ontology/dbt.yaml"])
        self.assertIsNone(out.created)

    def test_second_run_same_day_does_not_re_register(self) -> None:
        """It reads from that day's branch, so the second run sees it as
        already registered."""
        self.queue.add(proposal(id="p2", author="alice",
                                target_yaml="cost.yaml",
                                payload={"s": "wh-a", "p": "COSTS",
                                         "o": "money-1"}))
        drain(self.queue, self.source, target_yaml="cost.yaml")
        ws = [c for c in self.source.commits if c["path"] == WORKSPACE]
        self.assertEqual(len(ws), 1, "workspace.yaml was written twice")


class TestLayering(unittest.TestCase):
    """That the inner layers import nothing from the outside world, checked
    as plain text.

    Whoever wrote it meant to keep it that way, but breaking it later takes
    exactly one import line. Failing here puts that one line in front of a
    reviewer.
    """

    #: streamlit is on the list because this package now lives inside the
    #: app. One `st.*` in an inner layer and the rules for opening a PR can
    #: only run inside the screen — which makes this very test unwritable.
    FORBIDDEN = ("boto3", "snowflake", "urllib", "requests", "streamlit")

    def test_domain_and_service_and_ports_touch_nothing_outside(self):
        root = pathlib.Path(__file__).resolve().parent.parent / "outbox"
        for name in ("domain.py", "service.py", "ports.py"):
            src = (root / name).read_text(encoding="utf-8")
            for line in src.splitlines():
                line = line.strip()
                if not line.startswith(("import ", "from ")):
                    continue
                for bad in self.FORBIDDEN:
                    self.assertNotIn(bad, line, f"{name}: {line}")


if __name__ == "__main__":
    unittest.main()
