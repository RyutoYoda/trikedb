"""Agent-facing workflow gates through the real MCP tool boundary."""

import asyncio
import json
from pathlib import Path

import pytest

from trikedb import TrikeDB


FLOW = """
ontology:
  predicates:
    HAS_STEP: workflow to step
    NEXT_STEP: step to next step
workflows:
  publish-report:
    label: Publish a report
    summary: Extract, transform, test and present sample data.
    steps:
      - id: extract
        label: Extract data
        agent:
          tools: [snowflake.query]
          entry: [Check source access]
          outputs: [query-result]
          gates:
            - {id: source-check, kind: test, description: Confirm expected columns}
        next: [transform, profile]
      - id: transform
        label: Transform data
        agent:
          tools: [dbt.run]
          outputs: [model]
          gates:
            - {id: unit-tests, kind: test, description: Run model tests}
        next: [present]
      - id: profile
        label: Profile data
        agent:
          outputs: [profile]
          gates:
            - {id: quality-check, kind: test, description: Check nulls}
        next: [present]
      - id: present
        label: Present dashboard
        agent:
          tools: [tableau.view]
          outputs: [dashboard]
          gates:
            - {id: browser-e2e, kind: e2e, description: Open and verify dashboard}
"""


def _call(server, action, **kwargs):
    result = asyncio.run(server.call_tool("agent_workflow", {"action": action, **kwargs}))
    blocks = result[0] if isinstance(result, tuple) else result
    return json.loads(blocks[0].text)


def _finish(server, run_id, step_id, artifact, gate):
    return _call(server, "complete", run_id=run_id, step_id=step_id,
                 artifacts={artifact: f"example://{artifact}"},
                 evidence=[{"gate": gate, "result": "pass",
                            "reference": f"example://{gate}"}])


def test_agent_workflow_mcp_branch_join_gates_and_restart(tmp_path):
    pytest.importorskip("mcp")
    from trikedb.mcp_server import build_server

    path = tmp_path / "graph.yaml"
    path.write_text(FLOW, encoding="utf-8")
    server = build_server(path, workflow_state_dir=tmp_path / "state")
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert names == {
        "agent_workflow", "sparql", "search", "find", "match", "add_triple",
        "act", "history", "remove_triples", "set_node", "get_node",
        "ontology", "stats", "extraction_prompt", "preview_triples",
        "add_triples", "import_source",
    }

    listed = _call(server, "list")
    assert listed["workflows"] == [{"id": "publish-report", "label": "Publish a report",
                                    "summary": "Extract, transform, test and present sample data.",
                                    "step_count": 4}]
    started = _call(server, "start", workflow_id="publish-report")
    run_id = started["run_id"]
    assert [step["id"] for step in started["ready"]] == ["extract"]
    assert started["ready"][0]["agent"]["tools"] == ["snowflake.query"]

    with pytest.raises(Exception, match="predecessor"):
        _finish(server, run_id, "present", "dashboard", "browser-e2e")
    with pytest.raises(Exception, match="artifacts"):
        _call(server, "complete", run_id=run_id, step_id="extract",
              evidence=[{"gate": "source-check", "result": "pass",
                         "reference": "example://check"}])
    with pytest.raises(Exception, match="evidence"):
        _call(server, "complete", run_id=run_id, step_id="extract",
              artifacts={"query-result": "example://query"})

    after_extract = _finish(server, run_id, "extract", "query-result", "source-check")
    assert {step["id"] for step in after_extract["ready"]} == {"transform", "profile"}
    assert after_extract["completed"]["extract"]["verification"] == "reported_by_agent"
    _finish(server, run_id, "transform", "model", "unit-tests")
    server = build_server(path, workflow_state_dir=tmp_path / "state")
    resumed = _call(server, "resume", run_id=run_id)
    assert [step["id"] for step in resumed["ready"]] == ["profile"]
    _finish(server, run_id, "profile", "profile", "quality-check")
    assert [step["id"] for step in _call(server, "next", run_id=run_id)["ready"]] == ["present"]
    finished = _finish(server, run_id, "present", "dashboard", "browser-e2e")
    assert finished["finished"] and not finished["ready"]
    assert "agent-reported" in finished["evidence_note"]
    assert not path.read_text(encoding="utf-8").count("example://")


def test_shipped_example_can_run_through_mcp(tmp_path):
    pytest.importorskip("mcp")
    from trikedb.mcp_server import build_server

    path = Path(__file__).resolve().parents[1] / "examples" / "agent_workflow.yaml"
    server = build_server(path, workflow_state_dir=tmp_path)
    run = _call(server, "start", workflow_id="example-analytics")
    assert [step["id"] for step in run["ready"]] == ["query-source"]
    run_id = run["run_id"]
    for step, output, gate in (
        ("query-source", "query-result", "source-test"),
        ("build-model", "model", "model-tests"),
        ("verify-dashboard", "dashboard", "dashboard-e2e"),
    ):
        run = _finish(server, run_id, step, output, gate)
    assert run["finished"]


def test_agent_workflow_can_read_separate_workspace_members(tmp_path):
    pytest.importorskip("mcp")
    from trikedb.mcp_server import build_server

    first = tmp_path / "finance.yaml"
    first.write_text(FLOW, encoding="utf-8")
    second = tmp_path / "platform.yaml"
    platform_flow = FLOW.replace("publish-report", "platform-report")
    for step_id in ("extract", "transform", "profile", "present"):
        platform_flow = platform_flow.replace(step_id, f"platform-{step_id}")
    second.write_text(platform_flow, encoding="utf-8")
    workspace = tmp_path / "workspace.yaml"
    workspace.write_text("graphs:\n  finance: finance.yaml\n  platform: platform.yaml\n",
                         encoding="utf-8")
    server = build_server(workspace, workflow_state_dir=tmp_path / "state")
    listed = _call(server, "list")
    assert {item["id"] for item in listed["workflows"]} == {
        "publish-report", "platform-report",
    }
    run = _call(server, "start", workflow_id="platform-report")
    assert [step["id"] for step in run["ready"]] == ["platform-extract"]
    assert not (tmp_path / "workspace.yaml").read_text().count("run_id")


def test_agent_workflow_rejects_changed_definition_and_caller(tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    from trikedb import mcp_server

    path = tmp_path / "graph.yaml"
    path.write_text(FLOW, encoding="utf-8")
    monkeypatch.setattr(mcp_server, "_identity", lambda claim=None: "alice")
    server = mcp_server.build_server(path, workflow_state_dir=tmp_path / "state")
    run_id = _call(server, "start", workflow_id="publish-report")["run_id"]
    monkeypatch.setattr(mcp_server, "_identity", lambda claim=None: "bob")
    with pytest.raises(Exception, match="not found"):
        _call(server, "resume", run_id=run_id)
    monkeypatch.setattr(mcp_server, "_identity", lambda claim=None: "alice")

    graph = TrikeDB(path)
    graph.set_node("extract", description="Definition changed after the run started")
    resumed = _call(server, "resume", run_id=run_id)
    assert resumed["definition_changed"]
    with pytest.raises(Exception, match="definition changed"):
        _finish(server, run_id, "extract", "query-result", "source-check")


@pytest.mark.parametrize("old, replacement, message", [
    ("tools: [snowflake.query]", "unknown: x", "unknown agent field"),
    ("tools: [snowflake.query]", "tools: [snowflake.query, snowflake.query]", "duplicate values"),
    ("kind: test", "kind: unknown", "invalid kind"),
])
def test_agent_step_contract_rejects_bad_yaml(tmp_path, old, replacement, message):
    path = tmp_path / "graph.yaml"
    path.write_text(FLOW.replace(old, replacement, 1),
                    encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        TrikeDB(path)
