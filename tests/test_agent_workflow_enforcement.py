"""Programmatic gates for skill reads and exact CI jobs."""

import asyncio
import base64
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path
from urllib.error import HTTPError

import pytest

from trikedb import agent_workflow
from trikedb import TrikeDB
from trikedb.mcp_server import build_server


GRAPH = """
ontology:
  predicates:
    HAS_STEP: workflow to step
    USES: step to skill
nodes:
  example-skill:
    type: skill
    label: Example checking skill
    path: skills/example/SKILL.md
workflows:
  check-example:
    label: Check an example
    steps:
      - id: verify-example
        label: Verify an example
        agent:
          outputs: [commit-sha]
          gates:
            - {id: tests, kind: test, description: Run tests, verifier: github_actions,
               repository: example-org/example-repo, subject_artifact: commit-sha,
               workflow_id: 42, required_jobs: [unit-tests, browser-e2e]}
triples:
  - {s: verify-example, p: USES, o: example-skill}
"""


def _call(server, action, **kwargs):
    result = asyncio.run(server.call_tool("agent_workflow", {"action": action, **kwargs}))
    blocks = result[0] if isinstance(result, tuple) else result
    return json.loads(blocks[0].text)


def _fixture(tmp_path):
    graph = tmp_path / "graph.yaml"
    graph.write_text(GRAPH, encoding="utf-8")
    skill = tmp_path / "skills" / "example" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: example\ndescription: Check a fictional item.\n---\n\nRun the checks.\n", encoding="utf-8")
    server = build_server(graph, workflow_state_dir=tmp_path / "state")
    return graph, skill, server


def test_skill_must_be_delivered_before_step_completion_and_survives_restart(tmp_path):
    graph, skill, server = _fixture(tmp_path)
    run = _call(server, "start", workflow_id="check-example")
    run_id = run["run_id"]
    assert run["ready"][0]["skills"][0]["id"] == "example-skill"
    assert run["ready"][0]["skills"][0]["path"] == "skills/example/SKILL.md"
    with pytest.raises(Exception, match="skill"):
        _call(server, "complete", run_id=run_id, step_id="verify-example",
              artifacts={"commit-sha": "a" * 40}, evidence=[])
    delivered = _call(server, "read_skill", run_id=run_id,
                      step_id="verify-example", skill_id="example-skill")
    assert delivered["content"] == skill.read_text(encoding="utf-8")
    assert delivered["sha256"] == hashlib.sha256(skill.read_bytes()).hexdigest()
    assert "content" not in _call(server, "resume", run_id=run_id)["ready"][0]["skills"][0]
    reopened = build_server(graph, workflow_state_dir=tmp_path / "state")
    assert _call(reopened, "resume", run_id=run_id)["ready"][0]["skills"][0]["read"] is True
    ledger = next((tmp_path / "state").glob("*.sqlite3"))
    assert b"Run the checks." not in ledger.read_bytes()


def test_skill_path_cannot_escape_graph_directory(tmp_path):
    graph, _, _ = _fixture(tmp_path)
    graph.write_text(GRAPH.replace("skills/example/SKILL.md", "../outside/SKILL.md"), encoding="utf-8")
    server = build_server(graph, workflow_state_dir=tmp_path / "state")
    with pytest.raises(Exception, match="skill path"):
        _call(server, "start", workflow_id="check-example")


def test_skill_symlink_escape_and_unpinned_github_url_are_rejected(tmp_path):
    graph, skill, _ = _fixture(tmp_path)
    outside = tmp_path.parent / "outside-skill" / "SKILL.md"
    outside.parent.mkdir(exist_ok=True)
    outside.write_text(skill.read_text(encoding="utf-8"), encoding="utf-8")
    skill.unlink()
    skill.symlink_to(outside)
    server = build_server(graph, workflow_state_dir=tmp_path / "state")
    with pytest.raises(Exception, match="skill path"):
        _call(server, "start", workflow_id="check-example")
    graph.write_text(GRAPH.replace("path: skills/example/SKILL.md",
        "url: https://github.com/example-org/example-repo/blob/main/skills/example/SKILL.md"),
        encoding="utf-8")
    server = build_server(graph, workflow_state_dir=tmp_path / "state")
    with pytest.raises(Exception, match="full commit SHA"):
        _call(server, "start", workflow_id="check-example")


def test_github_skill_fetch_uses_runtime_token_and_pinned_commit(tmp_path, monkeypatch):
    graph, _, _ = _fixture(tmp_path)
    commit = "b" * 40
    graph.write_text(GRAPH.replace("path: skills/example/SKILL.md",
        f"url: https://github.com/example-org/example-repo/blob/{commit}/skills/example/SKILL.md"),
        encoding="utf-8")
    server = build_server(graph, workflow_state_dir=tmp_path / "state")
    run_id = _call(server, "start", workflow_id="check-example")["run_id"]
    monkeypatch.setenv("TRIKEDB_GITHUB_TOKEN", "fixture-token")
    requests = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self, _limit):
            content = b"---\nname: example\ndescription: Fictional.\n---\nUse this."
            return json.dumps({"type": "file", "encoding": "base64",
                               "path": "skills/example/SKILL.md", "size": len(content),
                               "content": base64.b64encode(content).decode()}).encode()

    def fake_open(request, timeout):
        requests.append(request)
        return Response()

    monkeypatch.setattr(agent_workflow, "urlopen", fake_open)
    delivered = _call(server, "read_skill", run_id=run_id,
                      step_id="verify-example", skill_id="example-skill")
    assert "Use this" in delivered["content"]
    assert requests[0].full_url.endswith(f"/skills/example/SKILL.md?ref={commit}")
    assert requests[0].get_header("Authorization") == "Bearer fixture-token"
    assert "fixture-token" not in graph.read_text(encoding="utf-8")


def test_private_skill_can_use_authenticated_gh_cli_without_storing_token(tmp_path, monkeypatch):
    graph, _, _ = _fixture(tmp_path)
    commit = "b" * 40
    graph.write_text(GRAPH.replace("path: skills/example/SKILL.md",
        f"url: https://github.com/example-org/example-repo/blob/{commit}/skills/example/SKILL.md"),
        encoding="utf-8")
    server = build_server(graph, workflow_state_dir=tmp_path / "state")
    run_id = _call(server, "start", workflow_id="check-example")["run_id"]
    monkeypatch.delenv("TRIKEDB_GITHUB_TOKEN", raising=False)

    def denied(*_args, **_kwargs):
        raise HTTPError("https://api.github.com", 404, "not found", {}, None)

    commands = []
    content = b"---\nname: example\ndescription: Private example.\n---\nRead me."
    payload = json.dumps({"type": "file", "encoding": "base64",
                          "path": "skills/example/SKILL.md", "size": len(content),
                          "content": base64.b64encode(content).decode()}).encode()

    def fake_run(command, **kwargs):
        commands.append(command)
        return type("Result", (), {"returncode": 0, "stdout": payload})()

    monkeypatch.setattr(agent_workflow, "urlopen", denied)
    monkeypatch.setattr(agent_workflow.subprocess, "run", fake_run)
    delivered = _call(server, "read_skill", run_id=run_id,
                      step_id="verify-example", skill_id="example-skill")
    assert delivered["content"] == content.decode()
    assert commands[0][:4] == ["gh", "api", "-X", "GET"]
    assert "token" not in str(commands)


def test_exact_github_workflow_and_required_jobs_are_enforced(tmp_path, monkeypatch):
    _, _, server = _fixture(tmp_path)
    run_id = _call(server, "start", workflow_id="check-example")["run_id"]
    _call(server, "read_skill", run_id=run_id,
          step_id="verify-example", skill_id="example-skill")
    sha = "a" * 40
    run = {"id": 123, "status": "completed", "conclusion": "success",
           "head_sha": sha, "repository": {"full_name": "example-org/example-repo"},
           "workflow_id": 99, "run_attempt": 1}
    jobs = {"total_count": 2, "jobs": [
        {"name": "unit-tests", "status": "completed", "conclusion": "success", "run_attempt": 1},
        {"name": "browser-e2e", "status": "completed", "conclusion": "success", "run_attempt": 1},
    ]}

    class Response:
        def __init__(self, payload): self.payload = payload
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self, _limit): return json.dumps(self.payload).encode()

    def fake_open(request, timeout):
        return Response(jobs if "/jobs?" in request.full_url else run)

    monkeypatch.setattr(agent_workflow, "urlopen", fake_open)
    args = dict(run_id=run_id, step_id="verify-example",
                artifacts={"commit-sha": sha},
                evidence=[{"gate": "tests", "result": "pass",
                           "reference": "https://github.com/example-org/example-repo/actions/runs/123"}])
    with pytest.raises(Exception, match="workflow"):
        _call(server, "complete", **args)
    run["workflow_id"] = 42
    jobs["jobs"][1]["conclusion"] = "skipped"
    with pytest.raises(Exception, match="required jobs"):
        _call(server, "complete", **args)
    jobs["jobs"][1]["conclusion"] = "success"
    completed = _call(server, "complete", **args)
    assert completed["finished"]
    assert completed["completed"]["verify-example"]["verification"] == "verified_report"


def test_strict_github_gate_rejects_incomplete_declarations(tmp_path):
    graph, _, _ = _fixture(tmp_path)
    graph.write_text(GRAPH.replace(
        "workflow_id: 42, required_jobs: [unit-tests, browser-e2e]",
        "workflow_id: 42"), encoding="utf-8")
    with pytest.raises(ValueError, match="declared together"):
        build_server(graph, workflow_state_dir=tmp_path / "state")


def test_preexisting_run_ledger_migrates_and_resumes(tmp_path):
    graph = tmp_path / "graph.yaml"
    graph.write_text("""ontology:
  predicates: {HAS_STEP: workflow to step}
workflows:
  simple:
    steps:
      - {id: one, label: One}
""", encoding="utf-8")
    db = TrikeDB(graph)
    plan = agent_workflow._definition(db, "simple")
    assert "skills" not in plan["steps"][0]
    ledger = agent_workflow._state_path(graph, tmp_path / "state")
    ledger.parent.mkdir(parents=True)
    with sqlite3.connect(ledger) as conn:
        conn.execute("""CREATE TABLE runs (
            run_id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL, owner TEXT NOT NULL,
            plan TEXT NOT NULL, fingerprint TEXT NOT NULL, completed TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        conn.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     ("legacy-run", "simple", "", json.dumps(plan),
                      agent_workflow._fingerprint(plan), "{}", "earlier", "earlier"))
    server = build_server(graph, workflow_state_dir=tmp_path / "state")
    resumed = _call(server, "resume", run_id="legacy-run")
    assert resumed["ready"][0]["id"] == "one"
    assert _call(server, "complete", run_id="legacy-run", step_id="one",
                 artifacts={}, evidence=[])["finished"]


def test_real_stdio_agent_receives_skill_and_cannot_finish_without_reading(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    graph, skill, _ = _fixture(tmp_path)
    graph.write_text(GRAPH.replace("""          outputs: [commit-sha]
          gates:
            - {id: tests, kind: test, description: Run tests, verifier: github_actions,
               repository: example-org/example-repo, subject_artifact: commit-sha,
               workflow_id: 42, required_jobs: [unit-tests, browser-e2e]}""",
        "          outputs: []"), encoding="utf-8")
    params = StdioServerParameters(
        command=str(Path(sys.executable).with_name("trikedb")),
        args=["mcp", str(graph)],
        env={**os.environ, "TRIKEDB_AGENT_WORKFLOW_STATE_DIR": str(tmp_path / "stdio-state")},
    )

    async def run_agent():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                async def act(action, **kwargs):
                    result = await session.call_tool("agent_workflow", {"action": action, **kwargs})
                    return result

                started = await act("start", workflow_id="check-example")
                run_id = json.loads(started.content[0].text)["run_id"]
                premature = await act("complete", run_id=run_id, step_id="verify-example",
                                    artifacts={}, evidence=[])
                assert premature.isError
                delivered = await act("read_skill", run_id=run_id,
                                      step_id="verify-example", skill_id="example-skill")
                assert not delivered.isError
                body = json.loads(delivered.content[0].text)["content"]
                assert body == skill.read_text(encoding="utf-8")
                finished = await act("complete", run_id=run_id, step_id="verify-example",
                                     artifacts={}, evidence=[])
                assert not finished.isError
                assert json.loads(finished.content[0].text)["finished"]

    asyncio.run(run_agent())
