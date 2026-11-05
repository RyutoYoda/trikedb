"""A local review UI for a TrikeDB graph, with optional GitHub App PR publishing.

This example has no built-in accounts or persistent server drafts. The browser
keeps an unsent draft; the server always rebuilds a proposal from the current
canonical YAML before previewing or publishing it.
"""

from __future__ import annotations

import base64
import difflib
import hashlib
import io
import json
import logging
import os
import re
import secrets
import tempfile
import time
from pathlib import Path

import httpx
import jwt
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field
from ruamel.yaml import YAML

from trikedb import TrikeDB

ROOT = Path(__file__).resolve().parent
GRAPH = Path(os.environ.get("GRAPH_FILE", ROOT / "demo.yaml")).resolve()
STATE_DIR = Path(os.environ.get("STATE_DIR", "/state"))
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
SETUP_TOKEN = os.environ.get("SETUP_TOKEN", "")
REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "")
REPO_FILE = os.environ.get("GITHUB_GRAPH_PATH", "")
EDITOR_TOKEN = os.environ.get("EDITOR_TOKEN", "") or SETUP_TOKEN
APP_ID = os.environ.get("GITHUB_APP_ID", "")
INSTALLATION_ID = os.environ.get("GITHUB_INSTALLATION_ID", "")
KEY_FILE = os.environ.get("GITHUB_APP_PRIVATE_KEY_FILE", "")
APP_SLUG = ""
GITHUB_API = "https://api.github.com"
ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{1,119}$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
FILE = re.compile(r"^[A-Za-z0-9_./-]+\.ya?ml$")
yaml = YAML(typ="rt")
yaml.preserve_quotes = True
yaml.width = 120
app = FastAPI(title="TrikeDB review example", docs_url=None, redoc_url=None)
logger = logging.getLogger(__name__)


@app.middleware("http")
async def private_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def load_saved_config():
    global REPOSITORY, REPO_FILE, APP_ID, INSTALLATION_ID, KEY_FILE, APP_SLUG
    config_file = STATE_DIR / "github.json"
    if config_file.exists():
        saved = json.loads(config_file.read_text(encoding="utf-8"))
        REPOSITORY = saved["repository"]
        REPO_FILE = saved["graph_path"]
        APP_ID = str(saved["app_id"])
        INSTALLATION_ID = str(saved.get("installation_id", ""))
        KEY_FILE = str(STATE_DIR / "github-app.pem")
        APP_SLUG = saved["app_slug"]


load_saved_config()


def private_write(path: Path, content: str):
    """Atomically replace a secret or setup record, never exposing a 0644 window."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=STATE_DIR, prefix=".private-", delete=False
    ) as handle:
        staging = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(staging, 0o600)
    staging.replace(path)


def save_config():
    target = STATE_DIR / "github.json"
    private_write(
        target,
        json.dumps(
            {
                "repository": REPOSITORY,
                "graph_path": REPO_FILE,
                "app_id": APP_ID,
                "installation_id": INSTALLATION_ID,
                "app_slug": APP_SLUG,
            }
        ),
    )


class Proposal(BaseModel):
    base_sha: str = Field(min_length=40, max_length=64)
    operations: list[dict] = Field(min_length=1, max_length=30)
    source: str = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=5, max_length=2000)
    preview_hash: str | None = None


class SetupStart(BaseModel):
    repository: str
    graph_path: str


def configured() -> bool:
    safe_file = bool(FILE.fullmatch(REPO_FILE)) and all(
        part not in ("", ".", "..") for part in REPO_FILE.split("/")
    )
    return all(
        (
            REPO.fullmatch(REPOSITORY),
            safe_file,
            EDITOR_TOKEN,
            APP_ID,
            INSTALLATION_ID,
            KEY_FILE,
            Path(KEY_FILE).is_file() if KEY_FILE else False,
        )
    )


def require_editor(request: Request):
    if not EDITOR_TOKEN or not secrets.compare_digest(
        request.headers.get("x-editor-token", ""), EDITOR_TOKEN
    ):
        raise HTTPException(403, "Editor token required")
    origin = request.headers.get("origin")
    expected_origin = (
        PUBLIC_BASE_URL or f"{request.url.scheme}://{request.headers.get('host')}"
    )
    if origin and origin != expected_origin:
        raise HTTPException(403, "Cross-origin write refused")


def require_setup(request: Request):
    if (
        not SETUP_TOKEN
        or len(SETUP_TOKEN) < 24
        or not secrets.compare_digest(
            request.headers.get("x-setup-token", ""), SETUP_TOKEN
        )
    ):
        raise HTTPException(403, "Setup token required")
    if not PUBLIC_BASE_URL or not PUBLIC_BASE_URL.startswith(
        ("https://", "http://localhost:", "http://127.0.0.1:")
    ):
        raise HTTPException(400, "PUBLIC_BASE_URL must be HTTPS or local loopback")
    origin = request.headers.get("origin")
    if origin and origin != PUBLIC_BASE_URL:
        raise HTTPException(403, "Cross-origin setup refused")


def git_request(token: str, method: str, path: str, body: dict | None = None):
    with httpx.Client(timeout=20) as client:
        response = client.request(
            method,
            f"{GITHUB_API}/repos/{REPOSITORY}{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "trikedb-review-example",
            },
            json=body,
        )
    if response.status_code >= 400:
        raise HTTPException(502, f"GitHub request failed ({response.status_code})")
    return response.json() if response.content else None


def installation_token() -> str:
    key = Path(KEY_FILE).read_text(encoding="utf-8")
    now = int(time.time())
    assertion = jwt.encode(
        {"iat": now - 30, "exp": now + 540, "iss": APP_ID}, key, algorithm="RS256"
    )
    with httpx.Client(timeout=20) as client:
        response = client.post(
            f"{GITHUB_API}/app/installations/{INSTALLATION_ID}/access_tokens",
            headers={
                "Authorization": f"Bearer {assertion}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "trikedb-review-example",
            },
            json={
                "repositories": [REPOSITORY.split("/", 1)[1]],
                "permissions": {"contents": "write", "pull_requests": "write"},
            },
        )
    if response.status_code >= 400:
        raise HTTPException(
            502, f"GitHub App authorization failed ({response.status_code})"
        )
    return response.json()["token"]


def app_token() -> str:
    now = int(time.time())
    return jwt.encode(
        {"iat": now - 30, "exp": now + 540, "iss": APP_ID},
        Path(KEY_FILE).read_text(encoding="utf-8"),
        algorithm="RS256",
    )


@app.get("/api/setup/status")
def setup_status():
    return {
        "enabled": bool(SETUP_TOKEN and len(SETUP_TOKEN) >= 24 and PUBLIC_BASE_URL),
        "registered": bool(APP_ID and KEY_FILE),
        "connected": configured(),
        "install_url": f"https://github.com/apps/{APP_SLUG}/installations/new"
        if APP_SLUG
        else None,
    }


@app.post("/api/setup/start")
def setup_start(data: SetupStart, request: Request):
    require_setup(request)
    if configured() or APP_ID:
        raise HTTPException(409, "A GitHub App is already registered")
    if (
        not REPO.fullmatch(data.repository)
        or not FILE.fullmatch(data.graph_path)
        or any(part in ("", ".", "..") for part in data.graph_path.split("/"))
    ):
        raise HTTPException(400, "Invalid repository or YAML path")
    pending = {
        "state": secrets.token_urlsafe(32),
        "repository": data.repository,
        "graph_path": data.graph_path,
        "created": int(time.time()),
    }
    pending_file = STATE_DIR / "pending.json"
    private_write(pending_file, json.dumps(pending))
    owner = data.repository.split("/", 1)[0]
    manifest = {
        "name": f"trikedb-review-{owner.lower()}",
        "url": PUBLIC_BASE_URL,
        "redirect_url": f"{PUBLIC_BASE_URL}/api/setup/callback",
        "hook_attributes": {
            "url": f"{PUBLIC_BASE_URL}/api/github/webhook",
            "active": False,
        },
        "public": False,
        "default_events": [],
        "default_permissions": {"contents": "write", "pull_requests": "write"},
    }
    return {
        "url": f"https://github.com/organizations/{owner}/settings/apps/new?state={pending['state']}",
        "personal_url": f"https://github.com/settings/apps/new?state={pending['state']}",
        "manifest": manifest,
    }


@app.get("/api/setup/callback")
def setup_callback(code: str, state: str):
    pending_file = STATE_DIR / "pending.json"
    if not pending_file.exists():
        raise HTTPException(400, "No pending registration")
    pending = json.loads(pending_file.read_text(encoding="utf-8"))
    if time.time() - pending["created"] > 3600 or not secrets.compare_digest(
        state, pending["state"]
    ):
        raise HTTPException(400, "Registration state expired or invalid")
    with httpx.Client(timeout=20) as client:
        response = client.post(
            f"{GITHUB_API}/app-manifests/{code}/conversions",
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "trikedb-review-example",
            },
        )
    if response.status_code >= 400:
        raise HTTPException(502, f"GitHub registration failed ({response.status_code})")
    registration = response.json()
    global REPOSITORY, REPO_FILE, APP_ID, APP_SLUG, KEY_FILE
    REPOSITORY, REPO_FILE = pending["repository"], pending["graph_path"]
    APP_ID, APP_SLUG = str(registration["id"]), registration["slug"]
    KEY_FILE = str(STATE_DIR / "github-app.pem")
    key_path = Path(KEY_FILE)
    private_write(key_path, registration["pem"])
    save_config()
    pending_file.unlink(missing_ok=True)
    return RedirectResponse("/?setup=registered", status_code=303)


@app.post("/api/setup/finish")
def setup_finish(request: Request):
    require_setup(request)
    if not APP_ID or not KEY_FILE or not REPO.fullmatch(REPOSITORY):
        raise HTTPException(409, "Register a GitHub App first")
    with httpx.Client(timeout=20) as client:
        response = client.get(
            f"{GITHUB_API}/repos/{REPOSITORY}/installation",
            headers={
                "Authorization": f"Bearer {app_token()}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "trikedb-review-example",
            },
        )
    if response.status_code >= 400:
        raise HTTPException(409, "Install the App on the selected repository first")
    global INSTALLATION_ID
    previous_installation = INSTALLATION_ID
    INSTALLATION_ID = str(response.json()["id"])
    try:
        canonical()  # Check that the App can read the chosen YAML on main.
    except Exception:
        INSTALLATION_ID = previous_installation
        raise
    save_config()
    return {"connected": True, "repository": REPOSITORY, "graph_path": REPO_FILE}


def canonical() -> tuple[str, str, str | None]:
    if configured():
        token = installation_token()
        item = git_request(token, "GET", f"/contents/{REPO_FILE}?ref=main")
        return base64.b64decode(item["content"]).decode("utf-8"), item["sha"], token
    text = GRAPH.read_text(encoding="utf-8")
    return text, hashlib.sha256(text.encode()).hexdigest(), None


def _require_id(value: object, name: str) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise HTTPException(400, f"Invalid {name}")
    return value


def _text(value: object, name: str, limit: int = 200) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise HTTPException(400, f"Invalid {name}")
    return value.strip()


def apply_operations(original: str, proposal: Proposal) -> str:
    document = yaml.load(original)
    if not isinstance(document, dict):
        raise HTTPException(409, "Graph YAML must be a mapping")
    nodes = document.setdefault("nodes", {})
    triples = document.setdefault("triples", [])
    workflows = document.setdefault("workflows", {})
    predicates = document.get("ontology", {}).get("predicates", {})
    if not all(
        isinstance(x, dict) for x in (nodes, workflows, predicates)
    ) or not isinstance(triples, list):
        raise HTTPException(409, "Unsupported graph document")
    for operation in proposal.operations:
        if not isinstance(operation, dict):
            raise HTTPException(400, "Invalid operation")
        kind = operation.get("kind")
        action = operation.get("action")
        if kind == "node" and action in ("create", "update", "remove"):
            node_id = _require_id(operation.get("id"), "node ID")
            if action == "remove":
                if node_id not in nodes:
                    raise HTTPException(409, "Node is missing")
                if any(
                    edge.get("s") == node_id or edge.get("o") == node_id
                    for edge in triples
                ):
                    raise HTTPException(409, "Remove this node's relationships first")
                del nodes[node_id]
                continue
            if (node_id in nodes) != (action == "update"):
                raise HTTPException(409, "Node existence changed")
            value = nodes.get(node_id, {})
            value["type"] = _require_id(operation.get("type"), "node type")
            value["label"] = _text(operation.get("label"), "node label")
            value["description"] = str(operation.get("description") or "")[:4000]
            value["prov"] = proposal.source.strip()
            nodes[node_id] = value
        elif kind == "edge" and action in ("add", "remove"):
            source = _require_id(operation.get("s"), "subject")
            predicate = _require_id(operation.get("p"), "predicate")
            target = _require_id(operation.get("o"), "object")
            if predicate not in predicates:
                raise HTTPException(400, "Undeclared relationship")
            found = [
                index
                for index, edge in enumerate(triples)
                if edge.get("s") == source
                and edge.get("p") == predicate
                and edge.get("o") == target
            ]
            if action == "add":
                step_ids = {
                    step.get("id")
                    for workflow in workflows.values()
                    for step in workflow.get("steps", [])
                }
                if (
                    found
                    or (source not in nodes and source not in step_ids)
                    or target not in nodes
                ):
                    raise HTTPException(
                        409, "Relationship exists or an endpoint is missing"
                    )
                triples.append(
                    {
                        "s": source,
                        "p": predicate,
                        "o": target,
                        "prov": proposal.source.strip(),
                    }
                )
            else:
                if len(found) != 1:
                    raise HTTPException(409, "Relationship is missing or ambiguous")
                del triples[found[0]]
        elif kind == "workflow" and action in ("create", "update"):
            workflow_id = _require_id(operation.get("id"), "workflow ID")
            if (workflow_id in workflows) != (action == "update"):
                raise HTTPException(409, "Workflow existence changed")
            value = workflows.get(workflow_id, {})
            value["label"] = _text(operation.get("label"), "workflow label")
            value["summary"] = _text(operation.get("summary"), "workflow summary", 1000)
            value.setdefault("steps", [])
            workflows[workflow_id] = value
        elif kind == "step" and action in ("create", "update", "remove"):
            workflow_id = _require_id(operation.get("workflow"), "workflow ID")
            step_id = _require_id(operation.get("id"), "step ID")
            if workflow_id not in workflows:
                raise HTTPException(409, "Workflow is missing")
            steps = workflows[workflow_id].setdefault("steps", [])
            found = [
                index for index, step in enumerate(steps) if step.get("id") == step_id
            ]
            if action == "create":
                if found:
                    raise HTTPException(409, "Step already exists")
                after = operation.get("after")
                prior = next((step for step in steps if step.get("id") == after), None)
                if steps and prior is None:
                    raise HTTPException(400, "Choose an existing step to insert after")
                inherited_next = list(prior.get("next", [])) if prior else []
                steps.append({"id": step_id})
                found = [len(steps) - 1]
                if prior is not None:
                    prior["next"] = [step_id]
            elif len(found) != 1:
                raise HTTPException(409, "Step is missing or ambiguous")
            if action == "remove":
                del steps[found[0]]
                for step in steps:
                    if step_id in step.get("next", []):
                        step["next"].remove(step_id)
                triples[:] = [
                    edge
                    for edge in triples
                    if edge.get("s") != step_id and edge.get("o") != step_id
                ]
            else:
                step = steps[found[0]]
                step["label"] = _text(operation.get("label"), "step label")
                step["description"] = str(operation.get("description") or "")[:4000]
                next_ids = operation.get("next", [])
                if action == "create" and not next_ids:
                    next_ids = inherited_next
                if not isinstance(next_ids, list) or len(next_ids) > 30:
                    raise HTTPException(400, "Invalid next steps")
                step["next"] = [_require_id(item, "next step") for item in next_ids]
        else:
            raise HTTPException(400, "Unsupported operation")
    buffer = io.StringIO()
    yaml.dump(document, buffer)
    updated = buffer.getvalue()
    with tempfile.TemporaryDirectory() as directory:
        candidate = Path(directory) / "candidate.yaml"
        candidate.write_text(updated, encoding="utf-8")
        try:
            TrikeDB(candidate, validate_on_load=True)
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, f"Invalid graph: {exc}") from exc
    if updated == original:
        raise HTTPException(400, "No change")
    return updated


def prepare(proposal: Proposal):
    if not proposal.source.strip() or len(proposal.reason.strip()) < 5:
        raise HTTPException(
            400, "A source and reason of at least 5 characters are required"
        )
    original, sha, token = canonical()
    if proposal.base_sha != sha:
        raise HTTPException(409, "Canonical YAML changed. Reload before editing.")
    updated = apply_operations(original, proposal)
    digest = hashlib.sha256(
        json.dumps(
            {
                "sha": sha,
                "updated": updated,
                "source": proposal.source.strip(),
                "reason": proposal.reason.strip(),
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    diff = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=f"a/{REPO_FILE or GRAPH.name}",
            tofile=f"b/{REPO_FILE or GRAPH.name}",
        )
    )
    return updated, digest, diff, sha, token


@app.get("/")
def page():
    return FileResponse(ROOT / "index.html")


@app.get("/app.css")
def css():
    return FileResponse(ROOT / "app.css", media_type="text/css")


@app.get("/app.js")
def javascript():
    return FileResponse(ROOT / "app.js", media_type="text/javascript")


@app.get("/logo.png")
def logo():
    return FileResponse(ROOT / "logo.png", media_type="image/png")


@app.get("/api/state")
def state(request: Request):
    if configured():
        require_editor(request)
    original, sha, _ = canonical()
    parsed = yaml.load(original)
    return {
        "sha": sha,
        "graph": json.loads(json.dumps(parsed)),
        "publishing": configured(),
        "file": REPO_FILE or GRAPH.name,
    }


@app.post("/api/preview")
def preview(proposal: Proposal, request: Request):
    if configured():
        require_editor(request)
    _, digest, diff, sha, _ = prepare(proposal)
    return {"base_sha": sha, "preview_hash": digest, "diff": diff}


@app.post("/api/pr")
def publish(proposal: Proposal, request: Request):
    if not configured():
        raise HTTPException(
            503, "Configure a GitHub App and editor token before publishing"
        )
    require_editor(request)
    updated, digest, _, sha, token = prepare(proposal)
    if not proposal.preview_hash or not secrets.compare_digest(
        proposal.preview_hash, digest
    ):
        raise HTTPException(409, "Preview the current YAML diff before publishing")
    owner = REPOSITORY.split("/", 1)[0]
    branch = f"trikedb/review-{digest[:16]}"
    existing = git_request(token, "GET", f"/pulls?state=open&head={owner}:{branch}")
    if existing:
        return {"url": existing[0]["html_url"], "number": existing[0]["number"]}
    main = git_request(token, "GET", "/git/ref/heads/main")["object"]["sha"]
    current = git_request(token, "GET", f"/contents/{REPO_FILE}?ref={main}")
    if current["sha"] != sha:
        raise HTTPException(409, "Canonical YAML changed after preview")
    git_request(
        token, "POST", "/git/refs", {"ref": f"refs/heads/{branch}", "sha": main}
    )
    try:
        git_request(
            token,
            "PUT",
            f"/contents/{REPO_FILE}",
            {
                "message": f"docs(graph): propose {REPO_FILE} update",
                "content": base64.b64encode(updated.encode()).decode(),
                "sha": sha,
                "branch": branch,
            },
        )
        pull = git_request(
            token,
            "POST",
            "/pulls",
            {
                "title": f"Graph proposal: {REPO_FILE}",
                "head": branch,
                "base": "main",
                "draft": True,
                "body": f"Source: {proposal.source.strip()}\n\nReason: {proposal.reason.strip()}\n\nPreview SHA-256: {digest}",
            },
        )
    except Exception:
        try:
            git_request(token, "DELETE", f"/git/refs/heads/{branch}")
        except (HTTPException, httpx.HTTPError) as cleanup_error:
            logger.warning("Could not remove failed proposal branch: %s", cleanup_error)
        raise
    return {"url": pull["html_url"], "number": pull["number"]}
