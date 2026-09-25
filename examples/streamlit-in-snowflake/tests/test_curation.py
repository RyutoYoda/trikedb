"""The parts of the screen that can be checked without running Streamlit.

Mostly: how the target YAML is chosen (which file, and whether it is new),
and that the rehearsal applies to **that one file** (an empty graph when it
is new). When this lies, you get the most confusing failure there is -- the
screen accepts a proposal and the PR builder refuses it.

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import datetime
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

# `curation` imports streamlit, but nothing called here draws anything. Put
# an empty module in its place so the rules can be tested without Streamlit
# in Snowflake anywhere near.
_stub = types.ModuleType("streamlit")
_stub.caption = lambda *a, **k: None
sys.modules.setdefault("streamlit", _stub)

import curation  # noqa: E402
import graph_store  # noqa: E402

WORKSPACE = """\
# union view
graphs:
  warehouse: warehouse.yaml
  sources: data_sources.yaml
  dbt: dbt.yaml
  workspace: workspace.yaml
"""


class TestTargets(unittest.TestCase):

    def setUp(self) -> None:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.path = str(pathlib.Path(d.name) / "workspace.yaml")
        pathlib.Path(self.path).write_text(WORKSPACE, encoding="utf-8")

    def test_comes_from_the_workspace(self) -> None:
        # File names, not keys: `sources` -> data_sources.yaml
        self.assertEqual(
            curation.targets(self.path),
            ["warehouse.yaml", "data_sources.yaml", "dbt.yaml"])

    def test_workspace_itself_is_not_offered(self) -> None:
        self.assertNotIn("workspace.yaml", curation.targets(self.path))

    def test_missing_file_is_empty(self) -> None:
        # The screen still opens with no staged copy; only "create new" is
        # left.
        self.assertEqual(curation.targets(self.path + ".nope"), [])


class TestPickOrType(unittest.TestCase):
    """One field. Two side-by-side fields for "pick" and "type" are gone."""

    class _Widget:
        def __init__(self, value):
            self.value, self.kw, self.calls = value, {}, 0

        def selectbox(self, label, options, **kw):
            self.calls += 1
            self.kw = kw
            return self.value

    def test_one_widget(self) -> None:
        w = self._Widget("dbt")
        got = curation._pick_or_type(w, "which", ["dbt"], "k", "pick or type")
        self.assertEqual(got, "dbt")
        self.assertEqual(w.calls, 1)

    def test_new_options_are_allowed(self) -> None:
        # Flip this back to False and the screen can no longer add anything
        # that is not already in the graph -- which is its whole purpose.
        # It is also why environment.yml pins streamlit >= 1.47.
        w = self._Widget("")
        curation._pick_or_type(w, "which", [], "k", "pick or type")
        self.assertIs(w.kw.get("accept_new_options"), True)

    def test_nothing_chosen_is_empty(self) -> None:
        # A selectbox with nothing chosen returns None.
        w = self._Widget(None)
        self.assertEqual(curation._pick_or_type(w, "which", [], "k", "…"), "")

    def test_surrounding_space_is_dropped(self) -> None:
        w = self._Widget("  dbt  ")
        self.assertEqual(curation._pick_or_type(w, "which", [], "k", "…"), "dbt")


class TestTargetChoice(unittest.TestCase):
    """Which YAML to propose into. One field; an unlisted name creates it."""

    KNOWN = ["dbt.yaml", "warehouse.yaml"]

    def choose(self, name):
        return curation._target(name, self.KNOWN)

    def test_picked(self) -> None:
        self.assertEqual(self.choose("dbt.yaml"), ("dbt.yaml", None))

    def test_a_name_not_in_the_list_is_new(self) -> None:
        self.assertEqual(self.choose("cost.yaml"), ("cost.yaml", None))

    def test_extension_is_optional(self) -> None:
        self.assertEqual(self.choose("cost"), ("cost.yaml", None))

    def test_nothing_chosen(self) -> None:
        # There is no default selection any more, so an empty choice must
        # not go through.
        target, problem = self.choose("  ")
        self.assertEqual(target, "")
        self.assertTrue(problem)

    def test_workspace_is_refused(self) -> None:
        target, problem = self.choose("workspace.yaml")
        self.assertEqual(target, "")
        # Straight from `domain`, so it stays English whatever the screen
        # is set to -- the same sentence goes into the PR body.
        self.assertIn("union", problem.text)
        self.assertEqual(problem.field, "yaml")

    def test_bad_shape_is_refused(self) -> None:
        for bad in ("Cost.yaml", "cost-ops", "../../etc/passwd"):
            target, problem = self.choose(bad)
            self.assertEqual(target, "", bad)
            self.assertTrue(problem, bad)

    def test_an_existing_name_is_not_new(self) -> None:
        target, problem = self.choose("dbt.yaml")
        self.assertEqual((target, problem), ("dbt.yaml", None))
        self.assertIn(target, self.KNOWN)   # this is what `fresh` reads


class TestEventProposal(unittest.TestCase):
    """Event proposals: what a date in the form actually does.

    Recording a permanent change as a dated event used to require the CLI.
    If the people who know and the people who can write stay separate, the
    screen has not achieved anything.
    """

    def bundle(self, **kw):
        kw.setdefault("s_name", "demo-repo")
        kw.setdefault("s_props", None)
        kw.setdefault("predicate", "AFFECTED_BY")
        kw.setdefault("is_new_pred", False)
        kw.setdefault("p_desc", "")
        kw.setdefault("o_name", "demo-repo-2026-09-25-x")
        kw.setdefault("o_props", None)
        return curation._bundle(
            kw.pop("s_name"), kw.pop("s_props"), kw.pop("predicate"),
            kw.pop("is_new_pred"), kw.pop("p_desc"), kw.pop("o_name"),
            kw.pop("o_props"), **kw)

    def test_a_date_makes_the_object_an_event(self) -> None:
        ops, bad = self.bundle(at="2026-09-25")
        self.assertIsNone(bad)
        self.assertEqual(
            ops,
            [("set_node", {"name": "demo-repo-2026-09-25-x",
                           "props": {"type": "event"}}),
             ("add_triple", {"s": "demo-repo", "p": "AFFECTED_BY",
                             "o": "demo-repo-2026-09-25-x",
                             "at": "2026-09-25"})])

    def test_the_node_comes_before_the_triple(self) -> None:
        # The other order gets refused by a guard that wants type:event.
        ops, _ = self.bundle(at="2026-09-25")
        self.assertEqual([op for op, _ in ops], ["set_node", "add_triple"])

    def test_an_existing_node_is_not_retyped(self) -> None:
        # Using an existing node as the event name must not rewrite its type.
        ops, bad = self.bundle(at="2026-09-25", known_nodes=["dbt-prod"],
                               o_name="dbt-prod")
        self.assertIsNone(bad)
        self.assertEqual([op for op, _ in ops], ["add_triple"])

    def test_the_date_joins_the_typed_properties(self) -> None:
        # Attributes typed at the same time collapse into one set_node.
        ops, bad = self.bundle(
            at="2026-09-25",
            o_props=[{"name": "label", "value": "2026-09-25 something"}])
        self.assertIsNone(bad)
        self.assertEqual([op for op, _ in ops], ["set_node", "add_triple"])
        self.assertEqual(ops[0][1]["props"],
                         {"label": "2026-09-25 something", "type": "event"})

    def test_without_a_date_nothing_becomes_an_event(self) -> None:
        ops, bad = self.bundle()
        self.assertIsNone(bad)
        self.assertEqual([op for op, _ in ops], ["add_triple"])
        self.assertNotIn("at", ops[0][1])

    def test_a_date_alone_is_refused(self) -> None:
        ops, bad = self.bundle(at="2026-09-25", predicate="")
        self.assertEqual(ops, [])
        self.assertTrue(bad)


class TestAt(unittest.TestCase):

    def test_a_date_object(self) -> None:
        self.assertEqual(curation._at(datetime.date(2026, 9, 25)), "2026-09-25")

    def test_empty(self) -> None:
        self.assertEqual(curation._at(None), "")

    def test_a_string_passes_through(self) -> None:
        self.assertEqual(curation._at(" 2026-09-25 "), "2026-09-25")


class TestDryRun(unittest.TestCase):
    """The rehearsal: one existing YAML, or an empty graph when it is new.

    The screen reads a read-only union of every graph, so rehearsing against
    the union directly cannot write at all -- that was the bug, and every
    proposal into an existing YAML failed with `read-only workspace union`.
    Rehearsing against the single target YAML is both writable and the same
    thing the PR will land in.
    """

    def setUp(self) -> None:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = pathlib.Path(d.name)

        dbt = graph_store.trikedb.TrikeDB(str(self.dir / "dbt.yaml"))
        dbt.declare_link("BUILT_BY", domain="model", range="team")
        dbt.set_node("model-a", type="model")
        dbt.set_node("team-x", type="team")
        dbt.save()

        # A different YAML. A predicate only declared here is unusable in
        # dbt.yaml.
        org = graph_store.trikedb.TrikeDB(str(self.dir / "org.yaml"))
        org.declare_link("WORKS_IN", domain="person", range="team")
        org.set_node("p-1", type="person")
        org.save()

        ws = self.dir / "workspace.yaml"
        ws.write_text("graphs:\n  dbt: dbt.yaml\n  org: org.yaml\n",
                      encoding="utf-8")
        self.db = graph_store.trikedb.TrikeDB(str(ws))
        self.assertTrue(self.db.read_only)   # a union is read-only
        self.op = [("add_triple", {"s": "model-a", "p": "BUILT_BY",
                                   "o": "team-x"})]

    def try_ops(self, ops, **kw):   # not `run` -- TestCase already has one
        return curation.dry_run(self.db, ops, session=None, author="someone",
                                target=kw.pop("target", "dbt.yaml"),
                                note="stocktake",
                                prov="https://example.invalid/1", **kw)

    def test_existing_passes(self) -> None:
        self.assertIsNone(self.try_ops(self.op))

    def test_union_is_left_alone(self) -> None:
        # The rehearsal applies to a copy. If the graph being read grows,
        # the screen is one step away from writing the derived table.
        before = len(self.db)
        self.try_ops(self.op)
        self.assertEqual(len(self.db), before)

    def test_refusal_reason_comes_back(self) -> None:
        why = self.try_ops([("add_triple", {"s": "team-x", "p": "BUILT_BY",
                                            "o": "model-a"})])
        self.assertTrue(why)   # wrong direction

    def test_another_yamls_vocabulary_is_not_borrowed(self) -> None:
        # This passes against the union (org.yaml declares WORKS_IN) but the
        # PR only lands in dbt.yaml. If it will be refused there, refuse here.
        why = self.try_ops([("set_node", {"name": "p-1",
                                          "props": {"type": "person"}}),
                            ("add_triple", {"s": "p-1", "p": "WORKS_IN",
                                            "o": "team-x"})])
        self.assertTrue(why)
        self.assertIn("WORKS_IN", why)

    def test_new_yaml_has_no_vocabulary(self) -> None:
        # Even a predicate you can pick from the list is undeclared in a new
        # file. An empty graph does not engage trikedb's own guard, so
        # `domain` is what stops it.
        why = self.try_ops(self.op, target="cost.yaml", fresh=True)
        self.assertTrue(why)
        self.assertIn("BUILT_BY", why)

    def test_new_yaml_accepts_what_it_declares_first(self) -> None:
        ops = [("declare_link", {"name": "COSTS", "domain": "warehouse",
                                 "range": "money",
                                 "description": "monthly spend"}),
               ("set_node", {"name": "wh-a", "props": {"type": "warehouse"}}),
               ("set_node", {"name": "money-1", "props": {"type": "money"}}),
               ("add_triple", {"s": "wh-a", "p": "COSTS", "o": "money-1"})]
        self.assertIsNone(self.try_ops(ops, target="cost.yaml", fresh=True))


class TestMemberPath(unittest.TestCase):
    """Finding one target YAML inside the union."""

    class _Union:
        def __init__(self, workspace, path=None):
            self.workspace, self.path = workspace, path

    def test_key_and_filename_differ(self) -> None:
        db = self._Union({"cost": "snowflake://T/p/cost_ops"})
        self.assertEqual(curation._member_path(db, "cost_ops.yaml"),
                         "snowflake://T/p/cost_ops")
        self.assertIsNone(curation._member_path(db, "cost.yaml"))

    def test_relative_member_is_resolved_from_the_union(self) -> None:
        # Resolving from the working directory points, locally, at a file
        # that does not exist.
        db = self._Union({"dbt": "dbt.yaml"}, path="/tmp/ws/workspace.yaml")
        self.assertEqual(curation._member_path(db, "dbt.yaml"),
                         "/tmp/ws/dbt.yaml")

    def test_unknown_target(self) -> None:
        self.assertIsNone(curation._member_path(self._Union({}), "cost.yaml"))


class TestBrief(unittest.TestCase):

    def test_long_internal_error_is_cut(self) -> None:
        short = curation._brief(ValueError("x" * 500))
        self.assertLess(len(short), 210)
        self.assertTrue(short.endswith("…"))

    def test_short_error_is_left_alone(self) -> None:
        self.assertEqual(curation._brief(ValueError("wrong direction")),
                         "wrong direction")


class TestPropsFromRows(unittest.TestCase):
    """The attribute fields. Is a half-typed row silently discarded?"""

    def test_empty_table_is_not_an_error(self):
        self.assertEqual(curation._props_from_rows([{"name": "", "value": ""}]),
                         ({}, None))

    def test_none_is_not_an_error(self):
        self.assertEqual(curation._props_from_rows(None), ({}, None))

    def test_pairs(self):
        props, bad = curation._props_from_rows(
            [{"name": "owner", "value": "team-x"},
             {"name": "freshness", "value": "daily"}])
        self.assertIsNone(bad)
        self.assertEqual(props, {"owner": "team-x", "freshness": "daily"})

    def test_value_may_contain_colon(self):
        # The clearest payoff from dropping the free-text `name: value` box:
        # a value containing a colon no longer splits.
        props, bad = curation._props_from_rows(
            [{"name": "doc", "value": "https://example.com/a:b"}])
        self.assertIsNone(bad)
        self.assertEqual(props, {"doc": "https://example.com/a:b"})

    def test_blank_rows_between_entries_are_skipped(self):
        props, bad = curation._props_from_rows(
            [{"name": "owner", "value": "team-x"},
             {"name": "", "value": ""},
             {"name": "freshness", "value": "daily"}])
        self.assertIsNone(bad)
        self.assertEqual(props, {"owner": "team-x", "freshness": "daily"})

    def test_name_without_value_is_refused(self):
        # Silently dropping a half-typed row produces "the attribute I
        # entered isn't there".
        _, bad = curation._props_from_rows(
            [{"name": "owner", "value": ""}], "Subject attribute")
        self.assertIn("Subject attribute", bad.text)
        self.assertIn("row 1", bad.text)
        self.assertIn("no value", bad.text)
        self.assertEqual(bad.field, "attribute")

    def test_value_without_name_is_refused(self):
        _, bad = curation._props_from_rows(
            [{"name": "", "value": "team-x"}], "Object attribute")
        self.assertIn("Object attribute", bad.text)
        self.assertIn("no name", bad.text)

    def test_whitespace_only_counts_as_empty(self):
        self.assertEqual(
            curation._props_from_rows([{"name": "  ", "value": " "}]),
            ({}, None))


class TestLogin(unittest.TestCase):
    """Choosing the GitHub username used as the commit author."""

    def test_keeps_the_registered_name_when_nothing_typed(self):
        # This line is what "register once and stop retyping" means.
        self.assertEqual(curation._login("octocat", "", "ALICE"), "octocat")

    def test_typed_wins(self):
        self.assertEqual(curation._login("octocat", "hubot", "ALICE"), "hubot")

    def test_whitespace_is_not_a_name(self):
        self.assertEqual(curation._login("octocat", "   ", "ALICE"), "octocat")

    def test_falls_back_to_the_snowflake_user(self):
        # It will not resolve to a GitHub account, but the history still
        # says whose proposal it was.
        self.assertEqual(curation._login("", "", "ALICE"), "ALICE")

    def test_strips(self):
        self.assertEqual(curation._login("", " hubot ", "ALICE"), "hubot")


class _Recorder:
    """Pretends to be a Streamlit column; records what was called."""

    def __init__(self, typed=()):
        self.typed = list(typed)
        self.text_inputs = []
        self._calls = []

    def calls(self, name):
        return [c for c in self._calls if c[0] == name]

    def columns(self, n):
        return [self for _ in range(n)]

    def text_input(self, label, **kw):
        self.text_inputs.append((label, kw))
        return self.typed.pop(0) if self.typed else ""

    def __getattr__(self, name):
        def rec(*a, **k):
            self._calls.append((name, a, k))
        return rec


class _Slot:
    """A reserved slot inside a form; keeps whatever was written into it."""

    def __init__(self):
        self.shown = []

    def error(self, msg):
        self.shown.append(msg)


class TestPropsField(unittest.TestCase):
    """Attributes are plain inputs like every other field, not a table."""

    def test_uses_plain_text_inputs_not_a_table(self):
        col = _Recorder()
        rows = curation._props_field(col, "Subject attributes", "s")
        self.assertEqual(col.calls("data_editor"), [])
        self.assertEqual(len(col.text_inputs), 2 * curation._PROP_ROWS)
        self.assertEqual(len(rows), curation._PROP_ROWS)
        self.assertEqual(sorted(rows[0]), ["name", "value"])

    def test_labels_only_on_the_first_pair(self):
        # The same word repeated down a column reads as a different thing.
        col = _Recorder()
        curation._props_field(col, "Subject attributes", "s")
        vis = [kw.get("label_visibility") for _, kw in col.text_inputs]
        self.assertEqual(vis[:2], ["visible", "visible"])
        self.assertEqual(set(vis[2:]), {"collapsed"})

    def test_keys_are_distinct_per_side(self):
        s, o = _Recorder(), _Recorder()
        curation._props_field(s, "Subject attributes", "s")
        curation._props_field(o, "Object attributes", "o")
        keys = [kw["key"] for _, kw in s.text_inputs + o.text_inputs]
        self.assertEqual(len(keys), len(set(keys)))

    def test_what_is_typed_survives_the_round_trip(self):
        col = _Recorder(typed=["owner", "team-x", "", ""])
        rows = curation._props_field(col, "Subject attributes", "s")
        props, bad = curation._props_from_rows(rows)
        self.assertIsNone(bad)
        self.assertEqual(props, {"owner": "team-x"})


class TestShowProblem(unittest.TestCase):
    """A refusal is printed under the field that caused it."""

    def setUp(self):
        self.p, self.t, self.props = _Slot(), _Slot(), _Slot()
        self.slots = (("test-add", "predicate", self.p),
                      ("cost.yaml", "yaml", self.t),
                      ("", "attribute", self.props))

    def test_predicate_refusal_lands_under_the_predicate_field(self):
        curation._show_problem(
            "predicate name 'test-add' is not UPPER_SNAKE_CASE", self.slots)
        self.assertEqual(len(self.p.shown), 1)
        self.assertEqual(self.t.shown, [])

    def test_target_refusal_lands_under_the_target_field(self):
        curation._show_problem("that yaml name is not allowed", self.slots)
        self.assertEqual(self.t.shown, ["that yaml name is not allowed"])
        self.assertEqual(self.p.shown, [])

    def test_quoted_value_routes_even_without_the_keyword(self):
        curation._show_problem("'cost.yaml' cannot be accepted", self.slots)
        self.assertEqual(len(self.t.shown), 1)

    def test_unroutable_problem_still_gets_shown(self):
        # Silently dropping a reason that matches no field is the worst case.
        with mock.patch.object(curation.st, "error", create=True) as err:
            curation._show_problem("Nothing was filled in.", self.slots)
        err.assert_called_once_with("Nothing was filled in.")
        self.assertEqual(self.p.shown + self.t.shown + self.props.shown, [])

    def test_a_problem_routes_on_its_field_not_its_words(self):
        # The whole reason `Problem` exists. Once the screen can be in
        # Japanese, no English keyword appears in the message at all, so
        # routing has to happen on something language-independent.
        curation._show_problem(
            curation.Problem("yaml", "このファイル名は使えません"), self.slots)
        self.assertEqual(self.t.shown, ["このファイル名は使えません"])
        self.assertEqual(self.p.shown, [])

    def test_a_problem_with_no_field_goes_to_the_bottom(self):
        with mock.patch.object(curation.st, "error", create=True) as err:
            curation._show_problem(curation.Problem("", "何も入力されていません"),
                                   self.slots)
        err.assert_called_once_with("何も入力されていません")
        self.assertEqual(self.p.shown + self.t.shown + self.props.shown, [])

    def test_a_field_tag_never_matches_by_accident(self):
        # A Japanese message that happens to sit in a Problem tagged
        # "attribute" must not land under the predicate field just because
        # the substring path would have found nothing.
        curation._show_problem(
            curation.Problem("attribute", "主語の属性の1行目"), self.slots)
        self.assertEqual(len(self.props.shown), 1)
        self.assertEqual(self.p.shown + self.t.shown, [])

    def test_a_missing_slot_is_skipped_not_crashed(self):
        with mock.patch.object(curation.st, "error", create=True) as err:
            curation._show_problem("bad predicate name",
                                   (("x", "predicate", None),
                                    ("y", "yaml", self.t)))
        err.assert_called_once()
        self.assertEqual(self.t.shown, [])


class TestReopenWhatWasTyped(unittest.TestCase):
    """After submitting, a section that was typed into stays open."""

    def test_prop_keys_match_the_widgets_that_are_actually_drawn(self):
        # Drift here means the section collapses after a refusal, hiding
        # both what was typed and the error. It fails silently, so pin it.
        drawn = []
        for side in ("s", "o"):
            col = _Recorder()
            curation._props_field(col, "Attributes", side)
            drawn += [kw["key"] for _, kw in col.text_inputs]
        self.assertEqual(sorted(drawn), sorted(curation._prop_keys()))

    def test_typed_is_true_when_something_was_left_in_the_box(self):
        with mock.patch.object(curation.st, "session_state",
                               {"pn_s0": "owner"}, create=True):
            self.assertTrue(curation._typed(*curation._prop_keys()))

    def test_typed_is_false_when_everything_is_empty(self):
        with mock.patch.object(curation.st, "session_state",
                               {"pn_s0": "", "at_event": None}, create=True):
            self.assertFalse(curation._typed(*curation._prop_keys()))
            self.assertFalse(curation._typed("at_event"))


class TestWhoIsLooking(unittest.TestCase):
    """Whose name to queue under. Returning the string "None" here is where
    the whole incident started.

    `SELECT CURRENT_USER()` issued from inside the app returns **NULL**.
    This used to pass that through `str()`, so "None" was stored as an
    identity -- as the AUTHOR of proposals and as the SF_USER on stored
    tokens. The row access policy is `CURRENT_USER() = SF_USER`, and *that
    expression sees the real name*, so it evaluated `'real name' = 'None'`,
    never true, and left **rows their own author could not read**. The
    screen just said "not registered", so registering again only added more
    unreadable rows.

    That is the cost of returning something when you don't know. Return None.
    """

    def _null_from_sql(self):
        return mock.patch.object(curation, "_exec", return_value=[(None,)])

    def test_null_current_user_is_not_a_name(self):
        with self._null_from_sql():
            self.assertIsNone(curation.current_user(object()))

    def test_the_string_none_is_not_a_name(self):
        # Even if one of the old rows comes back, do not pick it up.
        with mock.patch.object(curation, "_exec", return_value=[("None",)]):
            self.assertIsNone(curation.current_user(object()))

    def test_current_user_is_used_when_it_has_a_value(self):
        # Over DB-API from a laptop, this path returns the real name.
        with mock.patch.object(curation, "_exec", return_value=[("ALICE",)]):
            self.assertEqual(curation.current_user(object()), "ALICE")

    def test_streamlit_knows_the_viewer(self):
        viewer = types.SimpleNamespace(user_name="ALICE")
        with mock.patch.object(curation.st, "user", viewer, create=True), \
                self._null_from_sql():
            self.assertEqual(curation.current_user(object()), "ALICE")

    def test_older_streamlit_keeps_it_under_experimental_user(self):
        viewer = types.SimpleNamespace(user_name="ALICE")
        with mock.patch.object(curation.st, "experimental_user", viewer,
                               create=True), self._null_from_sql():
            self.assertEqual(curation.current_user(object()), "ALICE")

    def test_the_viewer_wins_over_current_user(self):
        # In Streamlit in Snowflake the SQL side is NULL, so they rarely
        # disagree. If a release ever makes both answer, the name that
        # matters is the person looking at the page, not the app's owner.
        viewer = types.SimpleNamespace(user_name="viewer")
        with mock.patch.object(curation.st, "user", viewer, create=True), \
                mock.patch.object(curation, "_exec", return_value=[("owner",)]):
            self.assertEqual(curation.current_user(object()), "viewer")

    def test_a_proxy_that_raises_does_not_take_the_page_down(self):
        # On releases that do not support it, `st.user` raises on access.
        class Angry:
            def __getattr__(self, name):
                raise RuntimeError("not in this release")

        with mock.patch.object(curation.st, "user", Angry(), create=True), \
                mock.patch.object(curation, "_exec", return_value=[("ALICE",)]):
            self.assertEqual(curation.current_user(object()), "ALICE")

    def test_no_session_and_no_viewer_is_nobody(self):
        with mock.patch.object(curation, "_exec", side_effect=RuntimeError):
            self.assertIsNone(curation.current_user(None))


class TestTimesAreLocalised(unittest.TestCase):
    """Timestamps on screen.

    The columns are TIMESTAMP_LTZ, so a bare SELECT renders them in the
    session timezone -- the account default, which for us was
    `America/Los_Angeles`. Every time on the screen was 16 hours off.
    Shifting the whole session would change what the *write* side means, so
    only the SELECTs that display convert.
    """

    def test_history_is_converted(self):
        with mock.patch.object(curation, "_exec", return_value=[]) as ex:
            curation.mine(object(), "ALICE")
        self.assertIn(
            f"CONVERT_TIMEZONE('{curation.DISPLAY_TIMEZONE}', CREATED_AT)",
            ex.call_args[0][1])

    def test_token_status_is_converted(self):
        with mock.patch.object(curation, "_exec", return_value=[]) as ex:
            curation.token_status(object(), "ALICE")
        self.assertIn(
            f"CONVERT_TIMEZONE('{curation.DISPLAY_TIMEZONE}', LAST_USED_AT)",
            ex.call_args[0][1])

    def test_the_token_value_is_still_never_selected(self):
        # Make sure adding the conversion did not also add TOKEN.
        with mock.patch.object(curation, "_exec", return_value=[]) as ex:
            curation.token_status(object(), "ALICE")
        self.assertNotIn("TOKEN,", ex.call_args[0][1])

    def test_a_datetime_is_shortened(self):
        self.assertEqual(
            curation._when(datetime.datetime(2026, 9, 25, 13, 4)),
            "09/25 13:04")

    def test_anything_else_is_passed_through(self):
        self.assertEqual(curation._when(None), "None")


class TestDeferredNote(unittest.TestCase):
    """The deferral message must not get **whose** proposals wrong.

    Deferred means "proposed by someone with no GitHub credential", and that
    someone is not necessarily another person: queue proposals before
    registering, then press, and your own are deferred. This used to receive
    only a count and called all of them "other people's proposals".
    """

    def _captions(self, result, author="me"):
        said = []
        with mock.patch.object(curation.st, "caption", said.append,
                               create=True):
            curation._deferred_note(result, author)
        return said

    def test_my_own_pending_proposals_are_not_called_someone_elses(self):
        said = self._captions({"deferred": 2,
                               "deferred_by_author": [("me", 2)]})
        self.assertEqual(len(said), 1)
        self.assertIn("2 of your proposals", said[0])
        self.assertNotIn("other people", said[0])

    def test_other_peoples_are_still_called_that(self):
        said = self._captions({"deferred": 1,
                               "deferred_by_author": [("bob", 1)]})
        self.assertEqual(len(said), 1)
        self.assertIn("1 proposals from other people", said[0])

    def test_both_are_counted_separately(self):
        said = self._captions({"deferred": 4,
                               "deferred_by_author": [("me", 1), ("bob", 2),
                                                      ("carol", 1)]})
        self.assertEqual(len(said), 2)
        self.assertIn("1 of your proposals", said[0])
        self.assertIn("3 proposals from other people", said[1])

    def test_nothing_deferred_says_nothing(self):
        self.assertEqual(self._captions({"deferred": 0,
                                         "deferred_by_author": []}), [])

    def test_the_two_numbers_add_up_to_what_service_counted(self):
        # The breakdown must total `deferred`; do not lose anyone by
        # folding them into one side.
        result = {"deferred": 4,
                  "deferred_by_author": [("me", 1), ("bob", 2), ("carol", 1)]}
        said = self._captions(result)
        self.assertEqual(sum(int(w) for line in said for w in line.split()
                             if w.isdigit()), result["deferred"])


if __name__ == "__main__":
    unittest.main()
