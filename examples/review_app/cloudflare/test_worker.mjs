import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import worker from "./worker.js";

const root = "https://example.test";
const data = JSON.parse(await readFile(new URL("./dist/demo-data.json", import.meta.url), "utf8"));
const env = {
  ASSETS: {
    async fetch() { return Response.json(data); },
  },
};
const request = (path, options) => worker.fetch(new Request(root + path, options), env);

test("the Worker serves only fictional state without publishing", async () => {
  const state = await (await request("/api/state")).json();
  assert.equal(state.demo, true);
  assert.equal(state.publishing, false);
  assert.equal(state.file, "demo.yaml");
  const publish = await request("/api/pr", { method: "POST" });
  assert.equal(publish.status, 503);
  assert.equal((await request("/api/setup/status")).status, 200);
});

test("the Worker previews a validated YAML change and rejects stale edits", async () => {
  const proposal = {
    base_sha: data.sha,
    source: "Example guide",
    reason: "Document a fictional process",
    operations: [{ kind: "node", action: "create", id: "example-note", type: "document", label: "Example note", description: "Fictional" }],
  };
  const preview = await request("/api/preview", { method: "POST", body: JSON.stringify(proposal) });
  assert.equal(preview.status, 200);
  assert.match((await preview.json()).diff, /example-note/);
  const stale = await request("/api/preview", { method: "POST", body: JSON.stringify({ ...proposal, base_sha: "0".repeat(64) }) });
  assert.equal(stale.status, 409);
  const invalid = await request("/api/preview", { method: "POST", body: JSON.stringify({ ...proposal, operations: [{ kind: "edge", action: "add", s: "missing-node", p: "USES", o: "order-form" }] }) });
  assert.equal(invalid.status, 400);
});

test("the Worker retains an optional step action contract", async () => {
  const step = {kind: "step", action: "create", workflow: "daily-order-report",
    id: "archive-orders", after: "publish-report", label: "Archive orders",
    description: "Keep a fictional copy", next: [], agent: {
      affects: [{concept: "report-table", operation: "create"}],
      executor: {kind: "mcp", server: "example-service", tool: "archive_report",
        parameter_map: {id: "report_id"}},
    }};
  const proposal = {base_sha: data.sha, source: "Example guide",
    reason: "Keep an audit copy", operations: [step]};
  const preview = await request("/api/preview", {method: "POST", body: JSON.stringify(proposal)});
  assert.equal(preview.status, 200);
  assert.match((await preview.json()).diff, /archive_report/);
  step.agent.affects[0].concept = "missing-concept";
  const invalid = await request("/api/preview", {method: "POST", body: JSON.stringify(proposal)});
  assert.equal(invalid.status, 400);
});
