"""A declared action is dispatched only through the selected ready step."""

import asyncio
import json

import pytest

from trikedb import TrikeDB
from trikedb.mcp_server import build_server
from trikedb.workflows import validate_agent_spec


GRAPH = """
ontology:
  predicates:
    HAS_STEP: workflow to step
    NEXT_STEP: step to next step
nodes:
  example-record: {type: concept, label: Example record}
workflows:
  example-flow:
    label: Example flow
    steps:
      - id: make-record
        label: Make record
        agent:
          affects:
            - {concept: example-record, operation: create}
          executor:
            kind: mcp
            server: example-service
            tool: create_record
            parameter_map: {name: record_name}
        next: [check-record]
      - id: check-record
        label: Check record
"""


def call(server, action, **kwargs):
    result = asyncio.run(server.call_tool("agent_workflow", {"action": action, **kwargs}))
    blocks = result[0] if isinstance(result, tuple) else result
    return json.loads(blocks[0].text)


def test_action_must_use_declared_binding_and_cannot_be_repeated(tmp_path):
    path = tmp_path / "graph.yaml"
    path.write_text(GRAPH, encoding="utf-8")
    calls = []

    def executor(server, tool, arguments, owner):
        calls.append((server, tool, arguments))
        return True

    server = build_server(path, workflow_state_dir=tmp_path / "state", workflow_executor=executor)
    run = call(server, "start", workflow_id="example-flow")["run_id"]
    with pytest.raises(Exception, match="execute the declared tool"):
        call(server, "complete", run_id=run, step_id="make-record", artifacts={}, evidence=[])
    with pytest.raises(Exception, match="declared names"):
        call(server, "execute_step", run_id=run, step_id="make-record", inputs={"password": "no"})
    with pytest.raises(Exception, match="not ready"):
        call(server, "execute_step", run_id=run, step_id="check-record", inputs={})
    result = call(server, "execute_step", run_id=run, step_id="make-record",
                  inputs={"record_name": "Example"})
    assert calls == [("example-service", "create_record", {"name": "Example"})]
    assert result["executions"]["make-record"]["status"] == "succeeded"
    with pytest.raises(Exception, match="already recorded"):
        call(server, "execute_step", run_id=run, step_id="make-record",
             inputs={"record_name": "Again"})
    assert calls == [("example-service", "create_record", {"name": "Example"})]
    result = call(server, "complete", run_id=run, step_id="make-record", artifacts={}, evidence=[])
    assert [step["id"] for step in result["ready"]] == ["check-record"]


def test_unconfigured_executor_and_uncertain_failure_fail_closed(tmp_path):
    path = tmp_path / "graph.yaml"
    path.write_text(GRAPH, encoding="utf-8")
    server = build_server(path, workflow_state_dir=tmp_path / "state")
    run = call(server, "start", workflow_id="example-flow")["run_id"]
    with pytest.raises(Exception, match="no trusted action executor"):
        call(server, "execute_step", run_id=run, step_id="make-record",
             inputs={"record_name": "Example"})

    def interrupted(*_):
        raise RuntimeError("connection lost after dispatch")

    server = build_server(path, workflow_state_dir=tmp_path / "state",
                          workflow_executor=interrupted)
    with pytest.raises(Exception, match="connection lost"):
        call(server, "execute_step", run_id=run, step_id="make-record",
             inputs={"record_name": "Example"})
    result = call(server, "resume", run_id=run)
    assert result["executions"]["make-record"]["status"] == "uncertain"
    with pytest.raises(Exception, match="already recorded"):
        call(server, "execute_step", run_id=run, step_id="make-record",
             inputs={"record_name": "Example"})


def test_action_contract_validates_shape_and_concept(tmp_path):
    spec = {"affects": [{"concept": "example-record", "operation": "delete", "fields": ["name"]}]}
    with pytest.raises(ValueError, match="invalid fields"):
        validate_agent_spec(spec, "step")
    with pytest.raises(ValueError, match="duplicate effect"):
        validate_agent_spec({"affects": [{"concept": "example-record", "operation": "update"}] * 2}, "step")
    with pytest.raises(ValueError, match="agent.executor"):
        validate_agent_spec({"executor": {"kind": "http", "url": "https://example.com"}}, "step")
    with pytest.raises(ValueError, match="agent.executor"):
        validate_agent_spec({"executor": {"kind": "mcp", "server": "example-service",
            "tool": "create_record", "parameter_map": {"api_key": "token"}}}, "step")
    path = tmp_path / "graph.yaml"
    path.write_text(GRAPH.replace("concept: example-record", "concept: unknown-record"), encoding="utf-8")
    db = TrikeDB(path)
    with pytest.raises(ValueError, match="unknown affects concept"):
        from trikedb.agent_workflow import AgentWorkflow
        AgentWorkflow(db, tmp_path / "state").handle("start", "actor", workflow_id="example-flow")
