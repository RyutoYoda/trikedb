"""A declared action is dispatched only through the selected ready step."""

import asyncio
import json
import os
import sys
from pathlib import Path
from textwrap import dedent

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


def test_real_stdio_agent_dispatches_to_real_downstream_mcp_once(tmp_path):
    """Agent -> TrikeDB MCP -> trusted adapter -> downstream MCP -> artifact."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    graph = tmp_path / "graph.yaml"
    graph.write_text(GRAPH, encoding="utf-8")
    downstream = tmp_path / "downstream.py"
    downstream.write_text(dedent("""
        import json
        import os
        from pathlib import Path
        from mcp.server.fastmcp import FastMCP

        server = FastMCP("example-service")

        @server.tool()
        def create_record(name: str) -> dict:
            path = Path(os.environ["E2E_OUTPUT"])
            values = json.loads(path.read_text()) if path.exists() else []
            values.append(name)
            path.write_text(json.dumps(values))
            return {"created": name}

        server.run(transport="stdio")
    """), encoding="utf-8")
    upstream = tmp_path / "upstream.py"
    upstream.write_text(dedent("""
        import asyncio
        import os
        import sys
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from trikedb.mcp_server import build_server

        def dispatch(server, tool, arguments, owner):
            if server != "example-service" or tool != "create_record":
                raise ValueError("downstream binding is not allowlisted")

            async def invoke():
                params = StdioServerParameters(
                    command=sys.executable, args=[os.environ["E2E_DOWNSTREAM"]],
                    env=dict(os.environ))
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as client:
                        await client.initialize()
                        return await client.call_tool(tool, arguments)

            return asyncio.run(invoke())

        server = build_server(os.environ["E2E_GRAPH"],
            workflow_state_dir=os.environ["E2E_STATE"], workflow_executor=dispatch)
        server.run(transport="stdio")
    """), encoding="utf-8")
    output = tmp_path / "records.json"
    env = {**os.environ, "E2E_GRAPH": str(graph), "E2E_STATE": str(tmp_path / "state"),
           "E2E_DOWNSTREAM": str(downstream), "E2E_OUTPUT": str(output),
           "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}

    async def run_agent():
        params = StdioServerParameters(command=sys.executable, args=[str(upstream)], env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()

                async def act(action, **kwargs):
                    return await client.call_tool("agent_workflow", {"action": action, **kwargs})

                started = await act("start", workflow_id="example-flow")
                assert not started.isError
                run_id = json.loads(started.content[0].text)["run_id"]
                premature = await act("complete", run_id=run_id, step_id="make-record",
                                      artifacts={}, evidence=[])
                assert premature.isError
                executed = await act("execute_step", run_id=run_id, step_id="make-record",
                                     inputs={"record_name": "Example"})
                assert not executed.isError, executed.content
                assert json.loads(executed.content[0].text)["executions"]["make-record"]["status"] == "succeeded"
                repeated = await act("execute_step", run_id=run_id, step_id="make-record",
                                     inputs={"record_name": "Again"})
                assert repeated.isError
                advanced = await act("complete", run_id=run_id, step_id="make-record",
                                     artifacts={}, evidence=[])
                assert not advanced.isError
                assert [step["id"] for step in json.loads(advanced.content[0].text)["ready"]] == ["check-record"]

    asyncio.run(run_agent())
    assert json.loads(output.read_text()) == ["Example"]
