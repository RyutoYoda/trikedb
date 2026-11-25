"""Agent workflow planning and a separate, durable execution ledger.

Workflow definitions remain ordinary TrikeDB nodes and edges. Runs are kept
out of the canonical graph, so a work session never becomes an ontology edit.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree

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
        step = {
            "id": membership.o,
            "label": meta.get("label", membership.o),
            "description": meta.get("description", ""),
            "order": membership.attrs.get("order"),
            "predecessors": sorted(incoming[membership.o]),
            "next": sorted(outgoing[membership.o]),
            "agent": spec,
        }
        if meta.get("next_mode") == "choose_one":
            if len(outgoing[membership.o]) < 2:
                raise ValueError(f"step {membership.o!r}: choose_one needs two successors")
            step["next_mode"] = "choose_one"
        elif meta.get("next_mode") is not None:
            raise ValueError(f"step {membership.o!r}: invalid next_mode")
        steps.append(step)
    meta = db.node(workflow_id)
    plan = {"id": workflow_id, "label": meta.get("label", workflow_id),
            "summary": meta.get("summary", ""), "steps": steps}
    return plan


def _fingerprint(plan: dict) -> str:
    payload = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _select_workflows(db, query: str) -> list[dict]:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("select requires a non-empty query")
    normalized = unicodedata.normalize("NFKC", query).casefold()
    words = set(re.findall(r"[^\W_]+", normalized))
    terms = set(words)
    for word in words:
        if len(word) >= 3 and any(ord(char) > 127 for char in word):
            terms.update(word[index:index + 2] for index in range(len(word) - 1))
    # Use the RDF projection for workflow membership and metadata. TrikeDB's
    # SELECT path runs on PyOxigraph by default; keep lexical ranking in Python
    # so NFKC normalization and Japanese partial matches remain consistent.
    rows = db.sparql("""
        SELECT ?workflow ?label ?summary ?step ?stepLabel WHERE {
          ?workflow t:type "workflow" .
          OPTIONAL { ?workflow t:label ?label }
          OPTIONAL { ?workflow t:summary ?summary }
          OPTIONAL {
            ?workflow t:HAS_STEP ?step .
            OPTIONAL { ?step t:label ?stepLabel }
          }
        }
    """)
    workflows = {}
    for row in rows:
        workflow_id = row["workflow"]
        entry = workflows.setdefault(workflow_id, {
            "id": workflow_id, "label": row.get("label", workflow_id),
            "summary": row.get("summary", ""), "steps": {},
        })
        if "step" in row:
            entry["steps"][row["step"]] = row.get("stepLabel", row["step"])
    candidates = []
    for plan in workflows.values():
        fields = [plan["id"], plan["label"], plan["summary"]]
        fields.extend(plan["steps"].values())
        haystack = unicodedata.normalize("NFKC", " ".join(fields)).casefold()
        matched = sorted(term for term in terms if term in haystack)
        if matched:
            candidates.append({"id": plan["id"], "label": plan["label"],
                               "summary": plan["summary"], "step_count": len(plan["steps"]),
                               "score": len(matched) + (3 if normalized in haystack else 0),
                               "matched_terms": matched,
                               "reason": "Matched workflow text; confirm the choice before start."})
    return sorted(candidates, key=lambda row: (-row["score"], row["id"]))


def _verify_junit(reference: str, root: Path | None) -> dict:
    if root is None:
        raise ValueError("JUnit verifier needs a configured evidence directory")
    candidate = Path(reference)
    if (candidate.is_absolute() or not candidate.parts or
            any(part in {".", ".."} for part in candidate.parts)):
        raise ValueError("JUnit reference must be a relative file within the evidence directory")
    directory = root.resolve()
    path = (directory / candidate).resolve()
    if not path.is_relative_to(directory) or not path.is_file():
        raise ValueError("JUnit reference must be a file within the evidence directory")
    if path.stat().st_size > 2_000_000:
        raise ValueError("JUnit report is too large")
    content = path.read_bytes()
    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise ValueError("JUnit report must not contain XML entities")
    try:
        report = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise ValueError("JUnit report is invalid XML") from exc
    if report.tag not in {"testsuite", "testsuites"}:
        raise ValueError("JUnit report has no test suite")
    suites = list(report.iter("testsuite"))
    cases = list(report.iter("testcase"))
    if not suites or not cases:
        raise ValueError("JUnit report contains no tests")
    for suite in suites:
        for key in ("tests", "failures", "errors", "skipped"):
            if key in suite.attrib:
                try:
                    count = int(suite.attrib[key])
                except ValueError as exc:
                    raise ValueError("JUnit report has invalid counts") from exc
                if count < 0 or (key == "tests" and count == 0) or (key != "tests" and count != 0):
                    raise ValueError("JUnit report did not pass")
    if any(case.find(name) is not None for case in cases
           for name in ("failure", "error", "skipped")):
        raise ValueError("JUnit report did not pass")
    return {"verifier": "junit", "sha256": hashlib.sha256(content).hexdigest(),
            "tests": len(cases)}


def _verify_github_actions(reference: str, gate: dict, artifacts: dict) -> dict:
    parsed = urlparse(reference)
    repository = gate["repository"]
    prefix = f"/{repository}/actions/runs/"
    if (parsed.scheme != "https" or parsed.netloc.lower() != "github.com"
            or parsed.query or parsed.fragment or not parsed.path.startswith(prefix)
            or not re.fullmatch(r"[1-9][0-9]*", parsed.path[len(prefix):])):
        raise ValueError("GitHub Actions reference must be a run URL for the declared repository")
    expected_sha = artifacts[gate["subject_artifact"]]
    if not re.fullmatch(r"[0-9a-fA-F]{40}", expected_sha):
        raise ValueError("GitHub Actions commit artifact must be a full SHA")
    run_id = int(parsed.path[len(prefix):])
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "trikedb-agent-workflow"}
    token = os.environ.get("TRIKEDB_GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        f"https://api.github.com/repos/{repository}/actions/runs/{run_id}",
        headers=headers,
    )
    try:
        with urlopen(request, timeout=10) as response:
            content = response.read(1_000_001)
        if len(content) > 1_000_000:
            raise ValueError("GitHub Actions response is too large")
        run = json.loads(content)
    except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
        raise ValueError("GitHub Actions run could not be verified") from exc
    if (run.get("id") != run_id
            or (run.get("repository") or {}).get("full_name", "").lower() != repository.lower()
            or run.get("head_sha", "").lower() != expected_sha.lower()):
        raise ValueError("GitHub Actions run does not match the declared repository and commit")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise ValueError("GitHub Actions run has not passed")
    return {"verifier": "github_actions", "run_id": run_id,
            "head_sha": expected_sha.lower()}


def _state_path(graph_path, state_dir=None) -> Path:
    root = Path(state_dir or os.environ.get("TRIKEDB_AGENT_WORKFLOW_STATE_DIR")
                or Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
                / "trikedb" / "agent-workflow")
    identity = str(graph_path.resolve()) if isinstance(graph_path, Path) else str(graph_path)
    return root / (hashlib.sha256(identity.encode()).hexdigest() + ".sqlite3")


def _edge_active(run: dict, predecessor: str, target: str) -> bool | None:
    record = run["completed"].get(predecessor)
    if record is None:
        return None
    if record.get("status") == "skipped":
        return False
    step = next(item for item in run["plan"]["steps"] if item["id"] == predecessor)
    if step.get("next_mode") == "choose_one":
        choice = record.get("choice")
        return None if choice is None else choice["target_id"] == target
    return True


def _ready_steps(run: dict) -> list[dict]:
    completed = run["completed"]
    return [step for step in run["plan"]["steps"]
            if step["id"] not in completed
            and all(parent in completed for parent in step["predecessors"])
            and (not step["predecessors"] or any(
                _edge_active(run, parent, step["id"]) is True
                for parent in step["predecessors"]))]


def _settle_skipped_routes(run: dict, reason: str) -> None:
    """Skip only nodes with no remaining active incoming route."""
    changed = True
    while changed:
        changed = False
        for step in run["plan"]["steps"]:
            if step["id"] in run["completed"] or not step["predecessors"]:
                continue
            if all(_edge_active(run, parent, step["id"]) is False
                   for parent in step["predecessors"]):
                run["completed"][step["id"]] = {
                    "at": _stamp(), "status": "skipped", "reason": reason,
                    "verification": "routing_decision",
                }
                changed = True


class RunStore:
    """SQLite transaction boundary; safe across server restarts and processes."""

    def __init__(self, path: Path, evidence_dir: Path | None = None):
        self.path = path
        self.evidence_dir = evidence_dir

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

    @staticmethod
    def _save(conn, run: dict) -> None:
        run["updated_at"] = _stamp()
        conn.execute("UPDATE runs SET completed=?, updated_at=? WHERE run_id=?",
                     (json.dumps(run["completed"], ensure_ascii=False),
                      run["updated_at"], run["run_id"]))

    @staticmethod
    def _require_current(run: dict, current_fingerprint: str) -> None:
        if run["fingerprint"] != current_fingerprint:
            raise ValueError("workflow definition changed; start a new run")

    def choose(self, run_id: str, owner: str, step_id: str, target_id: str,
               reason: str, current_fingerprint: str) -> dict:
        if not reason or not reason.strip():
            raise ValueError("choose requires a reason")
        with self.transaction() as conn:
            conn.execute("BEGIN IMMEDIATE")
            run = self._load(conn, run_id, owner)
            self._require_current(run, current_fingerprint)
            step = next((s for s in run["plan"]["steps"] if s["id"] == step_id), None)
            if step is None or step.get("next_mode") != "choose_one":
                raise ValueError("step has no choose_one branch")
            if target_id not in step["next"]:
                raise ValueError("target_id is not a successor of this step")
            record = run["completed"].get(step_id)
            if record is None or record.get("status") == "skipped":
                raise ValueError("complete the branch step before choosing")
            if "choice" in record:
                raise ValueError("branch choice is already recorded")
            record["choice"] = {"target_id": target_id, "reason": reason.strip(),
                                "at": _stamp()}
            _settle_skipped_routes(run, reason.strip())
            self._save(conn, run)
            return run

    def skip(self, run_id: str, owner: str, step_id: str, reason: str,
             current_fingerprint: str) -> dict:
        if not reason or not reason.strip():
            raise ValueError("skip requires a reason")
        with self.transaction() as conn:
            conn.execute("BEGIN IMMEDIATE")
            run = self._load(conn, run_id, owner)
            self._require_current(run, current_fingerprint)
            step = next((s for s in run["plan"]["steps"] if s["id"] == step_id), None)
            if step is None or not step["agent"].get("skippable"):
                raise ValueError("step is not declared skippable")
            if step not in _ready_steps(run):
                raise ValueError("step is not ready")
            run["completed"][step_id] = {
                "at": _stamp(), "status": "skipped", "reason": reason.strip(),
                "verification": "declared_optional",
            }
            _settle_skipped_routes(run, f"Skipped predecessor: {reason.strip()}")
            self._save(conn, run)
            return run

    def complete(self, run_id: str, owner: str, step_id: str, artifacts: dict,
                 evidence: list[dict], current_fingerprint: str) -> dict:
        with self.transaction() as conn:
            conn.execute("BEGIN IMMEDIATE")
            run = self._load(conn, run_id, owner)
            self._require_current(run, current_fingerprint)
            step = next((s for s in run["plan"]["steps"] if s["id"] == step_id), None)
            if step is None:
                raise ValueError(f"step {step_id!r} is not in this workflow")
            if step_id in run["completed"]:
                raise ValueError(f"step {step_id!r} is already complete")
            if step not in _ready_steps(run):
                raise ValueError("finish predecessor step(s) and choose an active route first")
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
            checks = []
            for gate_id, item in reported.items():
                if (set(item) != {"gate", "result", "reference"}
                        or item["result"] != "pass"
                        or not isinstance(item["reference"], str)
                        or not item["reference"].strip()):
                    raise ValueError(f"gate {gate_id!r} needs a passing result and evidence reference")
                if gates[gate_id].get("verifier") == "junit":
                    checks.append({"gate": gate_id,
                                   **_verify_junit(item["reference"], self.evidence_dir)})
                elif gates[gate_id].get("verifier") == "github_actions":
                    checks.append({"gate": gate_id,
                                   **_verify_github_actions(item["reference"], gates[gate_id], artifacts)})
            run["completed"][step_id] = {
                "at": _stamp(), "status": "completed", "artifacts": artifacts,
                "evidence": evidence, "checks": checks,
                "verification": ("verified_report" if checks and len(checks) == len(gates)
                                 else "mixed" if checks else "reported_by_agent"),
            }
            self._save(conn, run)
            return run


def _result(run: dict, current_fingerprint: str) -> dict:
    plan = run["plan"]
    completed = run["completed"]
    ready = _ready_steps(run)
    return {
        "run_id": run["run_id"], "workflow_id": run["workflow_id"],
        "workflow": {"label": plan["label"], "summary": plan["summary"]},
        "ready": ready, "completed": completed,
        "finished": len(completed) == len(plan["steps"]),
        "definition_changed": run["fingerprint"] != current_fingerprint,
        "updated_at": run["updated_at"],
        "evidence_note": "Unverified references are agent-reported. Verified gates inspect JUnit or GitHub Actions results but do not execute tests or establish who produced the work.",
    }


class AgentWorkflow:
    """The single MCP-facing use case; it never executes external systems."""

    def __init__(self, db, state_dir=None, evidence_dir=None):
        self.db = db
        configured_evidence = evidence_dir or os.environ.get("TRIKEDB_AGENT_WORKFLOW_EVIDENCE_DIR")
        self.store = RunStore(_state_path(db.path, state_dir),
                              Path(configured_evidence) if configured_evidence else None)

    def handle(self, action: str, owner: str, workflow_id: str | None = None,
               run_id: str | None = None, step_id: str | None = None,
               artifacts: dict | None = None, evidence: list[dict] | None = None,
               query: str | None = None, target_id: str | None = None,
               reason: str | None = None) -> dict:
        if action == "select":
            return {"query": query, "candidates": _select_workflows(self.db, query)}
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
        if action not in {"next", "resume", "complete", "choose", "skip"}:
            raise ValueError("action must be list, select, start, next, complete, choose, skip or resume")
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
        elif action == "choose":
            if not step_id or not target_id:
                raise ValueError("choose requires step_id and target_id")
            run = self.store.choose(run_id, owner, step_id, target_id, reason, current)
        elif action == "skip":
            if not step_id:
                raise ValueError("skip requires step_id")
            run = self.store.skip(run_id, owner, step_id, reason, current)
        return _result(run, current)
