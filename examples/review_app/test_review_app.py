"""Focused API checks for review and publishing boundaries."""

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from examples.review_app import app as module


class ReviewAppTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(module.app)
        self.original = (Path(__file__).parent / "demo.yaml").read_text(
            encoding="utf-8"
        )
        self.sha = hashlib.sha256(self.original.encode()).hexdigest()
        self.proposal = {
            "base_sha": self.sha,
            "operations": [
                {
                    "kind": "step",
                    "action": "create",
                    "workflow": "daily-order-report",
                    "id": "archive-orders",
                    "after": "publish-report",
                    "label": "Archive orders",
                    "description": "Keep a copy",
                    "next": [],
                }
            ],
            "source": "Example guide",
            "reason": "Keep an audit copy",
        }

    def test_preview_validates_connected_workflow_and_does_not_write(self):
        response = self.client.post("/api/preview", json=self.proposal)
        self.assertEqual(response.status_code, 200)
        self.assertIn("archive-orders", response.json()["diff"])
        self.assertEqual(
            (Path(__file__).parent / "demo.yaml").read_text(encoding="utf-8"),
            self.original,
        )
        self.assertEqual(
            self.client.post(
                "/api/pr",
                json={**self.proposal, "preview_hash": response.json()["preview_hash"]},
            ).status_code,
            503,
        )

    def test_stale_canonical_is_rejected(self):
        response = self.client.post(
            "/api/preview", json={**self.proposal, "base_sha": "0" * 64}
        )
        self.assertEqual(response.status_code, 409)

    def test_node_deletion_requires_relationship_cleanup(self):
        proposal = {
            **self.proposal,
            "operations": [{"kind": "node", "action": "remove", "id": "order-form"}],
        }
        self.assertEqual(
            self.client.post("/api/preview", json=proposal).status_code, 409
        )
        proposal["operations"] = [
            {
                "kind": "edge",
                "action": "remove",
                "s": "intake-orders",
                "p": "USES",
                "o": "order-form",
            },
            {"kind": "node", "action": "remove", "id": "order-form"},
        ]
        response = self.client.post("/api/preview", json=proposal)
        self.assertEqual(response.status_code, 200)
        self.assertIn("order-form", response.json()["diff"])

    def test_connected_graph_requires_editor_token_even_for_read(self):
        with (
            patch.object(module, "configured", return_value=True),
            patch.object(module, "EDITOR_TOKEN", "editor-secret"),
            patch.object(
                module,
                "canonical",
                return_value=(self.original, self.sha, "test-token"),
            ),
        ):
            self.assertEqual(self.client.get("/api/state").status_code, 403)
            response = self.client.get(
                "/api/state", headers={"X-Editor-Token": "editor-secret"}
            )
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("editor-secret", response.text)

    def test_draft_pr_requires_current_preview_and_targets_main(self):
        calls = []

        def fake_git(token, method, path, body=None):
            calls.append((method, path, body))
            if path.startswith("/pulls?"):
                return []
            if path == "/git/ref/heads/main":
                return {"object": {"sha": "main-commit"}}
            if path.startswith("/contents/") and method == "GET":
                return {"sha": self.sha}
            if path == "/pulls" and method == "POST":
                return {
                    "html_url": "https://github.com/example-org/graph-repo/pull/1",
                    "number": 1,
                }
            return {}

        with (
            patch.object(module, "configured", return_value=True),
            patch.object(
                module,
                "canonical",
                return_value=(self.original, self.sha, "test-token"),
            ),
            patch.object(module, "require_editor"),
            patch.object(module, "git_request", side_effect=fake_git),
            patch.object(module, "REPOSITORY", "example-org/graph-repo"),
            patch.object(module, "REPO_FILE", "graph.yaml"),
        ):
            denied = self.client.post(
                "/api/pr", json={**self.proposal, "preview_hash": "0" * 64}
            )
            self.assertEqual(denied.status_code, 409)
            self.assertFalse(calls)
            preview = self.client.post("/api/preview", json=self.proposal)
            self.assertEqual(preview.status_code, 200)
            response = self.client.post(
                "/api/pr",
                json={**self.proposal, "preview_hash": preview.json()["preview_hash"]},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["number"], 1)
            self.assertEqual(
                next(body for method, path, body in calls if path == "/pulls")["draft"],
                True,
            )
            self.assertIn("/git/ref/heads/main", [path for _, path, _ in calls])

    def test_setup_manifest_needs_token_and_uses_minimal_permissions(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(module, "STATE_DIR", Path(directory)),
            patch.object(module, "SETUP_TOKEN", "s" * 32),
            patch.object(module, "PUBLIC_BASE_URL", "https://example.test"),
            patch.object(module, "APP_ID", ""),
        ):
            data = {"repository": "example-org/graph-repo", "graph_path": "graph.yaml"}
            denied = self.client.post("/api/setup/start", json=data)
            self.assertEqual(denied.status_code, 403)
            response = self.client.post(
                "/api/setup/start", json=data, headers={"X-Setup-Token": "s" * 32}
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json()["manifest"]["default_permissions"],
                {"contents": "write", "pull_requests": "write"},
            )
            self.assertFalse(response.json()["manifest"]["hook_attributes"]["active"])
            self.assertTrue((Path(directory) / "pending.json").exists())

    def test_manifest_callback_keeps_private_key_server_side(self):
        class FakeResponse:
            status_code = 200

            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return self.payload

        class FakeGitHub:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def post(self, *_args, **_kwargs):
                return FakeResponse(
                    {"id": 123, "slug": "review-demo", "pem": "PRIVATE TEST KEY"}
                )

            def get(self, *_args, **_kwargs):
                return FakeResponse({"id": 456})

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(module, "STATE_DIR", Path(directory)),
            patch.object(module, "SETUP_TOKEN", "s" * 32),
            patch.object(module, "EDITOR_TOKEN", "e" * 32),
            patch.object(module, "PUBLIC_BASE_URL", "https://example.test"),
            patch.object(module, "APP_ID", ""),
            patch.object(module, "APP_SLUG", ""),
            patch.object(module, "KEY_FILE", ""),
            patch.object(module, "INSTALLATION_ID", ""),
            patch.object(module, "REPOSITORY", ""),
            patch.object(module, "REPO_FILE", ""),
            patch.object(module.httpx, "Client", return_value=FakeGitHub()),
            patch.object(module, "app_token", return_value="test-jwt"),
            patch.object(
                module,
                "canonical",
                return_value=(self.original, self.sha, "test-token"),
            ),
        ):
            start = self.client.post(
                "/api/setup/start",
                json={
                    "repository": "example-org/graph-repo",
                    "graph_path": "graph.yaml",
                },
                headers={"X-Setup-Token": "s" * 32},
            )
            state = start.json()["url"].split("state=", 1)[1]
            callback = self.client.get(
                "/api/setup/callback",
                params={"code": "test-code", "state": state},
                follow_redirects=False,
            )
            self.assertEqual(callback.status_code, 303)
            key = Path(directory) / "github-app.pem"
            self.assertEqual(key.read_text(), "PRIVATE TEST KEY")
            self.assertEqual(os.stat(key).st_mode & 0o777, 0o600)
            self.assertNotIn("PRIVATE TEST KEY", callback.text)
            finish = self.client.post(
                "/api/setup/finish", headers={"X-Setup-Token": "s" * 32}
            )
            self.assertEqual(finish.status_code, 200)
            self.assertTrue(finish.json()["connected"])


if __name__ == "__main__":
    unittest.main()
