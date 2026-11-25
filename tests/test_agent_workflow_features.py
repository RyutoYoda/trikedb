"""MCP-level contracts for workflow selection, decisions, and checked evidence."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from trikedb import agent_workflow
from trikedb import TrikeDB
from trikedb.mcp_server import build_server


FLOW = """
ontology:
  predicates:
    HAS_STEP: workflow to step
    NEXT_STEP: step to next step
workflows:
  publish-report:
    label: Publish an example report
    summary: Check example orders and publish a report.
    steps:
      - id: check-orders
        label: Check orders
        agent:
          outputs: [checked-orders]
          gates:
            - {id: checks, kind: test, description: Run checks, verifier: junit}
        next: [publish, request-fix]
        next_mode: choose_one
      - id: publish
        label: Publish report
        next: [finish]
      - id: request-fix
        label: Request corrections
        next: [finish]
      - id: finish
        label: Close request
        agent:
          skippable: true
  catalog-review:
    label: Review example catalog
    summary: Check catalog entries.
    steps:
      - id: inspect-catalog
        label: Inspect catalog
"""


def call(server, action, **kwargs):
    result = asyncio.run(server.call_tool("agent_workflow", {"action": action, **kwargs}))
    blocks = result[0] if isinstance(result, tuple) else result
    return json.loads(blocks[0].text)


def server_for(tmp_path, *, evidence_dir=None):
    path = tmp_path / "graph.yaml"
    path.write_text(FLOW, encoding="utf-8")
    return build_server(path, workflow_state_dir=tmp_path / "state",
                        workflow_evidence_dir=evidence_dir), path


def test_select_returns_ranked_explainable_candidates_without_starting_run(tmp_path):
    server, _ = server_for(tmp_path)
    result = call(server, "select", query="publish example report")
    assert result["candidates"][0]["id"] == "publish-report"
    assert result["candidates"][0]["matched_terms"]
    assert "run_id" not in result
    assert call(server, "select", query="unknown phrase")["candidates"] == []
    assert call(server, "select", query="注文を確認")["candidates"] == []
    with pytest.raises(Exception, match="query"):
        call(server, "select")

    japanese = tmp_path / "japanese.yaml"
    japanese.write_text(FLOW.replace("Publish an example report", "架空の注文レポートを公開"),
                        encoding="utf-8")
    localized = build_server(japanese, workflow_state_dir=tmp_path / "localized-state")
    assert call(localized, "select", query="注文レポート")["candidates"][0]["id"] == "publish-report"


def test_explicit_choice_skip_and_join_survive_restart(tmp_path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "checks.xml").write_text(
        '<testsuite tests="1" failures="0" errors="0"><testcase name="orders"/></testsuite>',
        encoding="utf-8",
    )
    server, path = server_for(tmp_path, evidence_dir=evidence_dir)
    run_id = call(server, "start", workflow_id="publish-report")["run_id"]
    result = call(server, "complete", run_id=run_id, step_id="check-orders",
                  artifacts={"checked-orders": "example://orders"},
                  evidence=[{"gate": "checks", "result": "pass", "reference": "checks.xml"}])
    assert result["ready"] == []  # A choice is required before either route is ready.
    assert result["completed"]["check-orders"]["verification"] == "verified_report"
    with pytest.raises(Exception, match="skippable"):
        call(server, "skip", run_id=run_id, step_id="publish", reason="Not needed")
    with pytest.raises(Exception, match="reason"):
        call(server, "choose", run_id=run_id, step_id="check-orders", target_id="publish")
    with pytest.raises(Exception, match="successor"):
        call(server, "choose", run_id=run_id, step_id="check-orders",
             target_id="finish", reason="Wrong target")
    result = call(server, "choose", run_id=run_id, step_id="check-orders",
                  target_id="publish", reason="Checks passed")
    with pytest.raises(Exception, match="already recorded"):
        call(server, "choose", run_id=run_id, step_id="check-orders",
             target_id="request-fix", reason="Changed mind")
    assert [step["id"] for step in result["ready"]] == ["publish"]
    assert result["completed"]["request-fix"]["status"] == "skipped"
    assert result["completed"]["request-fix"]["reason"] == "Checks passed"
    server = build_server(path, workflow_state_dir=tmp_path / "state",
                          workflow_evidence_dir=evidence_dir)
    assert [step["id"] for step in call(server, "resume", run_id=run_id)["ready"]] == ["publish"]
    result = call(server, "complete", run_id=run_id, step_id="publish",
                  artifacts={}, evidence=[])
    assert [step["id"] for step in result["ready"]] == ["finish"]
    result = call(server, "skip", run_id=run_id, step_id="finish",
                  reason="Example is already closed")
    assert result["finished"]
    assert result["completed"]["finish"]["status"] == "skipped"


@pytest.mark.parametrize("xml", [
    '<testsuite tests="1"><testcase name="orders"><failure/></testcase></testsuite>',
    '<testsuite tests="0"/>',
    '<not-a-test-report/>',
])
def test_junit_verifier_rejects_failed_or_empty_reports(tmp_path, xml):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "checks.xml").write_text(xml, encoding="utf-8")
    server, _ = server_for(tmp_path, evidence_dir=evidence_dir)
    run_id = call(server, "start", workflow_id="publish-report")["run_id"]
    with pytest.raises(Exception, match="JUnit"):
        call(server, "complete", run_id=run_id, step_id="check-orders",
             artifacts={"checked-orders": "example://orders"},
             evidence=[{"gate": "checks", "result": "pass", "reference": "checks.xml"}])


def test_junit_verifier_rejects_untrusted_paths_and_unconfigured_root(tmp_path):
    server, _ = server_for(tmp_path)
    run_id = call(server, "start", workflow_id="publish-report")["run_id"]
    evidence = [{"gate": "checks", "result": "pass", "reference": "checks.xml"}]
    with pytest.raises(Exception, match="evidence directory"):
        call(server, "complete", run_id=run_id, step_id="check-orders",
             artifacts={"checked-orders": "example://orders"}, evidence=evidence)
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    server, _ = server_for(tmp_path, evidence_dir=evidence_dir)
    run_id = call(server, "start", workflow_id="publish-report")["run_id"]
    for reference in ("../secret.xml", "/etc/passwd"):
        with pytest.raises(Exception, match="reference"):
            call(server, "complete", run_id=run_id, step_id="check-orders",
                 artifacts={"checked-orders": "example://orders"},
                 evidence=[{"gate": "checks", "result": "pass", "reference": reference}])
    outside = tmp_path / "outside.xml"
    outside.write_text('<testsuite><testcase name="x"/></testsuite>', encoding="utf-8")
    (evidence_dir / "linked.xml").symlink_to(outside)
    with pytest.raises(Exception, match="reference"):
        call(server, "complete", run_id=run_id, step_id="check-orders",
             artifacts={"checked-orders": "example://orders"},
             evidence=[{"gate": "checks", "result": "pass", "reference": "linked.xml"}])


def test_unselected_route_cascades_to_join_without_running_it(tmp_path):
    content = FLOW.replace("      - id: finish", "      - id: request-fix-detail\n        label: Send detail\n        next: [finish]\n      - id: finish")
    content = content.replace("label: Request corrections\n        next: [finish]", "label: Request corrections\n        next: [request-fix-detail]")
    path = tmp_path / "graph.yaml"
    path.write_text(content, encoding="utf-8")
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "checks.xml").write_text(
        '<testsuite><testcase name="orders"/></testsuite>', encoding="utf-8")
    server = build_server(path, workflow_state_dir=tmp_path / "state",
                          workflow_evidence_dir=evidence_dir)
    run_id = call(server, "start", workflow_id="publish-report")["run_id"]
    call(server, "complete", run_id=run_id, step_id="check-orders",
         artifacts={"checked-orders": "example://orders"},
         evidence=[{"gate": "checks", "result": "pass", "reference": "checks.xml"}])
    result = call(server, "choose", run_id=run_id, step_id="check-orders",
                  target_id="publish", reason="Checks passed")
    assert result["completed"]["request-fix-detail"]["status"] == "skipped"
    assert [step["id"] for step in result["ready"]] == ["publish"]
    result = call(server, "complete", run_id=run_id, step_id="publish",
                  artifacts={}, evidence=[])
    assert [step["id"] for step in result["ready"]] == ["finish"]


def test_github_actions_verifier_binds_run_to_declared_repo_and_commit(tmp_path, monkeypatch):
    content = FLOW.replace(
        "outputs: [checked-orders]",
        "outputs: [checked-orders, commit-sha]",
    ).replace(
        "description: Run checks, verifier: junit",
        "description: Run checks, verifier: github_actions, "
        "repository: example-org/example-repo, subject_artifact: commit-sha",
    )
    path = tmp_path / "graph.yaml"
    path.write_text(content, encoding="utf-8")
    server = build_server(path, workflow_state_dir=tmp_path / "state")
    run_id = call(server, "start", workflow_id="publish-report")["run_id"]
    sha = "a" * 40
    payload = {"id": 123, "status": "completed", "conclusion": "success",
               "head_sha": sha,
               "repository": {"full_name": "example-org/example-repo"}}
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, _limit):
            return json.dumps(payload).encode()

    def fake_open(request, timeout):
        requests.append(request.full_url)
        return Response()

    monkeypatch.setattr(agent_workflow, "urlopen", fake_open)
    args = dict(run_id=run_id, step_id="check-orders",
                artifacts={"checked-orders": "example://orders", "commit-sha": sha},
                evidence=[{"gate": "checks", "result": "pass",
                           "reference": "https://github.com/example-org/example-repo/actions/runs/123"}])
    payload["head_sha"] = "b" * 40
    with pytest.raises(Exception, match="commit"):
        call(server, "complete", **args)
    payload["head_sha"] = sha
    result = call(server, "complete", **args)
    assert result["completed"]["check-orders"]["verification"] == "verified_report"
    assert requests == ["https://api.github.com/repos/example-org/example-repo/actions/runs/123"] * 2


def test_github_actions_verifier_rejects_other_hosts_before_request(tmp_path, monkeypatch):
    content = FLOW.replace("outputs: [checked-orders]", "outputs: [checked-orders, commit-sha]")
    content = content.replace(
        "description: Run checks, verifier: junit",
        "description: Run checks, verifier: github_actions, "
        "repository: example-org/example-repo, subject_artifact: commit-sha",
    )
    path = tmp_path / "graph.yaml"
    path.write_text(content, encoding="utf-8")
    server = build_server(path, workflow_state_dir=tmp_path / "state")
    run_id = call(server, "start", workflow_id="publish-report")["run_id"]
    monkeypatch.setattr(agent_workflow, "urlopen", lambda *_args, **_kwargs: pytest.fail("network called"))
    with pytest.raises(Exception, match="GitHub Actions reference"):
        call(server, "complete", run_id=run_id, step_id="check-orders",
             artifacts={"checked-orders": "example://orders", "commit-sha": "a" * 40},
             evidence=[{"gate": "checks", "result": "pass",
                        "reference": "https://example.com/example-org/example-repo/actions/runs/123"}])


def test_real_stdio_mcp_process_selects_routes_verifies_and_resumes(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    path = tmp_path / "graph.yaml"
    path.write_text(FLOW, encoding="utf-8")
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "checks.xml").write_text(
        '<testsuite tests="1"><testcase name="orders"/></testsuite>', encoding="utf-8")
    env = {**os.environ,
           "TRIKEDB_AGENT_WORKFLOW_STATE_DIR": str(tmp_path / "state"),
           "TRIKEDB_AGENT_WORKFLOW_EVIDENCE_DIR": str(evidence_dir)}
    params = StdioServerParameters(
        command=str(Path(sys.executable).with_name("trikedb")),
        args=["mcp", str(path)], env=env,
    )

    async def session_run(resume_id=None):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                async def step(action, **kwargs):
                    result = await session.call_tool("agent_workflow", {"action": action, **kwargs})
                    assert not result.isError, result.content
                    return json.loads(result.content[0].text)

                if resume_id:
                    restored = await step("resume", run_id=resume_id)
                    assert [item["id"] for item in restored["ready"]] == ["publish"]
                    advanced = await step("complete", run_id=resume_id, step_id="publish",
                                          artifacts={}, evidence=[])
                    assert [item["id"] for item in advanced["ready"]] == ["finish"]
                    return await step("skip", run_id=resume_id, step_id="finish",
                                      reason="Already closed")
                selected = await step("select", query="publish example report")
                assert selected["candidates"][0]["id"] == "publish-report"
                run = await step("start", workflow_id=selected["candidates"][0]["id"])
                run_id = run["run_id"]
                run = await step("complete", run_id=run_id, step_id="check-orders",
                                 artifacts={"checked-orders": "example://orders"},
                                 evidence=[{"gate": "checks", "result": "pass",
                                            "reference": "checks.xml"}])
                assert not run["ready"]
                run = await step("choose", run_id=run_id, step_id="check-orders",
                                 target_id="publish", reason="Checks passed")
                assert [item["id"] for item in run["ready"]] == ["publish"]
                return run

    run = asyncio.run(session_run())
    resumed = asyncio.run(session_run(run["run_id"]))
    assert resumed["finished"]
    assert resumed["completed"]["check-orders"]["verification"] == "verified_report"
    assert "example://" not in path.read_text(encoding="utf-8")


def test_decision_shorthand_roundtrips_as_canonical_graph(tmp_path):
    source = Path(__file__).resolve().parents[1] / "examples" / "agent_workflow_decision.yaml"
    path = tmp_path / "graph.yaml"
    path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    graph = TrikeDB(path)
    assert graph.node("inspect-orders")["next_mode"] == "choose_one"
    graph.save()
    reopened = TrikeDB(path)
    assert reopened.node("inspect-orders")["next_mode"] == "choose_one"
    assert reopened.node("close-request")["agent"]["skippable"] is True


@pytest.mark.parametrize("old,replacement,message", [
    ("next_mode: choose_one", "next_mode: invalid", "next_mode"),
    ("skippable: true", "skippable: perhaps", "boolean"),
    ("verifier: junit", "verifier: shell", "unsupported verifier"),
])
def test_invalid_decision_and_verifier_specs_fail_on_load(tmp_path, old, replacement, message):
    path = tmp_path / "graph.yaml"
    path.write_text(FLOW.replace(old, replacement), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        TrikeDB(path)
