"""Agent workflow planning and a separate, durable execution ledger.

Workflow definitions remain ordinary TrikeDB nodes and edges. Runs are kept
out of the canonical graph, so a work session never becomes an ontology edit.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .workflows import _validate_workflows, validate_agent_spec


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _definition(db, workflow_id: str) -> dict:
    if db.node(workflow_id).get("type") != "workflow":
        raise ValueError(f"{workflow_id!r} is not a declared workflow")
    members = list(db.triples(s=workflow_id, p="HAS_STEP"))
    if not members:
        raise ValueError(f"{workflow_id!r} has no HAS_STEP relations")
    all_members = [t.to_dict() for t in db.triples(p="HAS_STEP")]
    all_edges = [t.to_dict() for t in db.triples(p="NEXT_STEP")]
    _validate_workflows(all_members + all_edges, {"NEXT_STEP"}, "HAS_STEP")
    ids = {t.o for t in members}
    incoming = {step: set() for step in ids}
    outgoing = {step: set() for step in ids}
    for edge in db.triples(p="NEXT_STEP"):
        if edge.s in ids and edge.o in ids:
            incoming[edge.o].add(edge.s)
            outgoing[edge.s].add(edge.o)
    steps = []
    for membership in sorted(members, key=lambda t: (t.attrs.get("order", 0), t.o)):
        meta = db.node(membership.o)
        spec = validate_agent_spec(meta.get("agent", {}), f"node {membership.o}")
        steps.append({
            "id": membership.o,
            "label": meta.get("label", membership.o),
            "description": meta.get("description", ""),
            "order": membership.attrs.get("order"),
            "predecessors": sorted(incoming[membership.o]),
            "next": sorted(outgoing[membership.o]),
            "agent": spec,
        })
    meta = db.node(workflow_id)
    plan = {"id": workflow_id, "label": meta.get("label", workflow_id),
            "summary": meta.get("summary", ""), "steps": steps}
    return plan


def _fingerprint(plan: dict) -> str:
    payload = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _state_path(graph_path, state_dir=None) -> Path:
    root = Path(state_dir or os.environ.get("TRIKEDB_AGENT_WORKFLOW_STATE_DIR")
                or Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
                / "trikedb" / "agent-workflow")
    identity = str(graph_path.resolve()) if isinstance(graph_path, Path) else str(graph_path)
    return root / (hashlib.sha256(identity.encode()).hexdigest() + ".sqlite3")


class RunStore:
    """SQLite transaction boundary; safe across server restarts and processes."""

    def __init__(self, path: Path):
        self.path = path

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        os.chmod(self.path, 0o600)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("""CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL, owner TEXT NOT NULL,
            plan TEXT NOT NULL, fingerprint TEXT NOT NULL,
            completed TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        return conn

    @contextmanager
    def transaction(self):
        conn = self.connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def create(self, plan: dict, owner: str) -> dict:
        now = _stamp()
        run = {"run_id": secrets.token_urlsafe(24), "workflow_id": plan["id"],
               "owner": owner, "plan": plan, "fingerprint": _fingerprint(plan),
               "completed": {}, "created_at": now, "updated_at": now}
        with self.transaction() as conn:
            conn.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (run["run_id"], run["workflow_id"], owner,
                          json.dumps(plan, ensure_ascii=False), run["fingerprint"],
                          "{}", now, now))
        return run

    @staticmethod
    def _load(conn, run_id: str, owner: str) -> dict:
        row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None or row["owner"] != owner:
            raise ValueError("workflow run not found for this caller")
        run = dict(row)
        run["plan"] = json.loads(run["plan"])
        run["completed"] = json.loads(run["completed"])
        return run

    def get(self, run_id: str, owner: str) -> dict:
        with self.transaction() as conn:
            return self._load(conn, run_id, owner)

    def complete(self, run_id: str, owner: str, step_id: str, artifacts: dict,
                 evidence: list[dict], current_fingerprint: str) -> dict:
        with self.transaction() as conn:
            conn.execute("BEGIN IMMEDIATE")
            run = self._load(conn, run_id, owner)
            if run["fingerprint"] != current_fingerprint:
                raise ValueError("workflow definition changed; start a new run")
            step = next((s for s in run["plan"]["steps"] if s["id"] == step_id), None)
            if step is None:
                raise ValueError(f"step {step_id!r} is not in this workflow")
            if step_id in run["completed"]:
                raise ValueError(f"step {step_id!r} is already complete")
            missing = set(step["predecessors"]) - set(run["completed"])
            if missing:
                raise ValueError(f"finish predecessor step(s) first: {', '.join(sorted(missing))}")
            required = set(step["agent"]["outputs"])
            if not isinstance(artifacts, dict) or set(artifacts) != required or any(
                not isinstance(v, str) or not v.strip() for v in artifacts.values()
            ):
                raise ValueError(f"artifacts must name every declared output: {sorted(required)}")
            gates = {g["id"]: g for g in step["agent"]["gates"]}
            if not isinstance(evidence, list) or any(not isinstance(e, dict) for e in evidence):
                raise ValueError("evidence must be a list of gate results")
            if any(not isinstance(e.get("gate"), str) for e in evidence):
                raise ValueError("each evidence item needs a gate id")
            reported = {e["gate"]: e for e in evidence}
            if len(reported) != len(evidence) or set(reported) != set(gates):
                raise ValueError(f"evidence must cover every declared gate: {sorted(gates)}")
            for gate_id, item in reported.items():
                if (set(item) != {"gate", "result", "reference"}
                        or item["result"] != "pass"
                        or not isinstance(item["reference"], str)
                        or not item["reference"].strip()):
                    raise ValueError(f"gate {gate_id!r} needs a passing result and evidence reference")
            run["completed"][step_id] = {
                "at": _stamp(), "artifacts": artifacts, "evidence": evidence,
                "verification": "reported_by_agent",
            }
            run["updated_at"] = _stamp()
            conn.execute("UPDATE runs SET completed=?, updated_at=? WHERE run_id=?",
                         (json.dumps(run["completed"], ensure_ascii=False),
                          run["updated_at"], run_id))
            return run


def _result(run: dict, current_fingerprint: str) -> dict:
    plan = run["plan"]
    completed = run["completed"]
    ready = [step for step in plan["steps"] if step["id"] not in completed
             and all(p in completed for p in step["predecessors"])]
    return {
        "run_id": run["run_id"], "workflow_id": run["workflow_id"],
        "workflow": {"label": plan["label"], "summary": plan["summary"]},
        "ready": ready, "completed": completed,
        "finished": len(completed) == len(plan["steps"]),
        "definition_changed": run["fingerprint"] != current_fingerprint,
        "updated_at": run["updated_at"],
        "evidence_note": "References are agent-reported; this tool does not execute or verify external tools.",
    }


class AgentWorkflow:
    """The single MCP-facing use case; it never executes external systems."""

    def __init__(self, db, state_dir=None):
        self.db = db
        self.store = RunStore(_state_path(db.path, state_dir))

    def handle(self, action: str, owner: str, workflow_id: str | None = None,
               run_id: str | None = None, step_id: str | None = None,
               artifacts: dict | None = None, evidence: list[dict] | None = None) -> dict:
        if action == "list":
            workflows = []
            for node in self.db.nodes():
                if self.db.node(node).get("type") == "workflow":
                    plan = _definition(self.db, node)
                    workflows.append({"id": node, "label": plan["label"],
                                      "summary": plan["summary"],
                                      "step_count": len(plan["steps"])})
            return {"workflows": sorted(workflows, key=lambda w: w["id"])}
        if action == "start":
            if not workflow_id:
                raise ValueError("start requires workflow_id")
            plan = _definition(self.db, workflow_id)
            run = self.store.create(plan, owner)
            return _result(run, run["fingerprint"])
        if action not in {"next", "resume", "complete"}:
            raise ValueError("action must be list, start, next, complete or resume")
        if not run_id:
            raise ValueError(f"{action} requires run_id")
        run = self.store.get(run_id, owner)
        try:
            current = _fingerprint(_definition(self.db, run["workflow_id"]))
        except ValueError:
            current = "missing"
        if action == "complete":
            if not step_id:
                raise ValueError("complete requires step_id")
            run = self.store.complete(run_id, owner, step_id, artifacts or {},
                                      evidence or [], current)
        return _result(run, current)
