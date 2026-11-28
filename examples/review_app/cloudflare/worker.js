import { createTwoFilesPatch } from "diff";
import { stringify } from "yaml";

const idPattern = /^[A-Za-z][A-Za-z0-9_.-]{1,119}$/;
const json = (data, status = 200) => new Response(JSON.stringify(data), {
  status,
  headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", "x-content-type-options": "nosniff" },
});

function fail(status, message) {
  return json({ detail: message }, status);
}

function validId(value, label) {
  if (typeof value !== "string" || !idPattern.test(value)) throw new Error(`Invalid ${label}`);
  return value;
}

function validText(value, label, max = 200) {
  if (typeof value !== "string" || !value.trim() || value.length > max) throw new Error(`Invalid ${label}`);
  return value.trim();
}

function stepIds(graph) {
  return new Set(Object.values(graph.workflows).flatMap((workflow) => (workflow.steps || []).map((step) => step.id)));
}

function applyOperations(original, operations, source) {
  const graph = structuredClone(original);
  graph.nodes ||= {};
  graph.triples ||= [];
  graph.workflows ||= {};
  const predicates = graph.ontology?.predicates || {};
  for (let operation of operations) {
    if (!operation || typeof operation !== "object") throw new Error("Invalid operation");
    const { kind, action } = operation;
    if (kind === "node" && ["create", "update", "remove"].includes(action)) {
      const id = validId(operation.id, "node ID");
      if (action === "remove") {
        if (!graph.nodes[id] || graph.triples.some((edge) => edge.s === id || edge.o === id)) throw new Error("Remove this node's relationships first");
        delete graph.nodes[id];
      } else {
        if (Boolean(graph.nodes[id]) !== (action === "update")) throw new Error("Node existence changed");
        graph.nodes[id] = {
          ...(graph.nodes[id] || {}),
          type: validId(operation.type, "node type"),
          label: validText(operation.label, "node label"),
          description: String(operation.description || "").slice(0, 4000),
          prov: source,
        };
      }
    } else if (kind === "edge" && ["add", "remove"].includes(action)) {
      const s = validId(operation.s, "subject");
      const p = validId(operation.p, "predicate");
      const o = validId(operation.o, "object");
      if (!Object.hasOwn(predicates, p)) throw new Error("Undeclared relationship");
      const index = graph.triples.findIndex((edge) => edge.s === s && edge.p === p && edge.o === o);
      if (action === "add") {
        if (index !== -1 || (!graph.nodes[s] && !stepIds(graph).has(s)) || !graph.nodes[o]) throw new Error("Relationship exists or an endpoint is missing");
        graph.triples.push({ s, p, o, prov: source });
      } else {
        if (index === -1) throw new Error("Relationship is missing");
        graph.triples.splice(index, 1);
      }
    } else if (kind === "workflow" && ["create", "update"].includes(action)) {
      const id = validId(operation.id, "workflow ID");
      if (Boolean(graph.workflows[id]) !== (action === "update")) throw new Error("Workflow existence changed");
      graph.workflows[id] = {
        ...(graph.workflows[id] || {}),
        label: validText(operation.label, "workflow label"),
        summary: validText(operation.summary, "workflow summary", 1000),
        steps: graph.workflows[id]?.steps || [],
      };
    } else if (kind === "step" && ["create", "update", "remove"].includes(action)) {
      const workflowId = validId(operation.workflow, "workflow ID");
      const id = validId(operation.id, "step ID");
      const steps = graph.workflows[workflowId]?.steps;
      if (!steps) throw new Error("Workflow is missing");
      let index = steps.findIndex((step) => step.id === id);
      if (action === "create") {
        if (index !== -1 || stepIds(graph).has(id)) throw new Error("Step already exists");
        const prior = steps.find((step) => step.id === operation.after);
        if (steps.length && !prior) throw new Error("Choose a step to insert after");
        const inheritedNext = prior ? [...(prior.next || [])] : [];
        steps.push({ id });
        index = steps.length - 1;
        if (prior) prior.next = [id];
        if (!operation.next?.length) operation = { ...operation, next: inheritedNext };
      } else if (index === -1) throw new Error("Step is missing");
      if (action === "remove") {
        steps.splice(index, 1);
        for (const step of steps) step.next = (step.next || []).filter((next) => next !== id);
        graph.triples = graph.triples.filter((edge) => edge.s !== id && edge.o !== id);
      } else {
        if (!Array.isArray(operation.next) || operation.next.length > 30) throw new Error("Invalid next steps");
        Object.assign(steps[index], {
          label: validText(operation.label, "step label"),
          description: String(operation.description || "").slice(0, 4000),
          next: operation.next.map((next) => validId(next, "next step")),
        });
        if (Object.hasOwn(operation, "agent")) {
          if (!operation.agent || typeof operation.agent !== "object" || Array.isArray(operation.agent)) throw new Error("Invalid agent action");
          if (Object.keys(operation.agent).length) steps[index].agent = operation.agent;
          else delete steps[index].agent;
        }
      }
    } else throw new Error("Unsupported operation");
  }
  validateGraph(graph);
  return graph;
}

function validateGraph(graph) {
  const ids = stepIds(graph);
  for (const edge of graph.triples) {
    if (!Object.hasOwn(graph.ontology.predicates, edge.p) || (!graph.nodes[edge.s] && !ids.has(edge.s)) || !graph.nodes[edge.o]) throw new Error("Invalid relationship endpoint");
  }
  for (const workflow of Object.values(graph.workflows)) {
    const local = new Set((workflow.steps || []).map((step) => step.id));
    for (const step of workflow.steps || []) {
      if ((step.next || []).some((next) => !local.has(next))) throw new Error("Next step is missing");
      const agent = step.agent;
      if (!agent) continue;
      if (!Array.isArray(agent.affects || [])) throw new Error("Invalid affects declaration");
      const effects = new Set();
      for (const effect of agent.affects || []) {
        if (!effect || typeof effect !== "object" || !graph.nodes[effect.concept]
            || !["create", "update", "delete"].includes(effect.operation)
            || (effect.fields !== undefined && (effect.operation === "delete" || !Array.isArray(effect.fields)
                || effect.fields.some((field) => typeof field !== "string" || !field.trim())))) throw new Error("Invalid affects declaration");
        const key = `${effect.concept}:${effect.operation}`;
        if (effects.has(key)) throw new Error("Duplicate affects declaration");
        effects.add(key);
      }
      if (agent.executor) {
        const executor = agent.executor;
        if (executor.kind !== "mcp" || !/^[A-Za-z0-9_.-]{1,100}$/.test(executor.server)
            || !/^[A-Za-z0-9_.-]{1,100}$/.test(executor.tool)
            || !executor.parameter_map || typeof executor.parameter_map !== "object"
            || Array.isArray(executor.parameter_map)
            || Object.entries(executor.parameter_map).some(([parameter, name]) =>
                typeof name !== "string" || !/^[A-Za-z][A-Za-z0-9_]{0,99}$/.test(name)
                || /secret|password|token|credential|api[_-]?key|private[_-]?key/i.test(parameter)
                || /secret|password|token|credential|api[_-]?key|private[_-]?key/i.test(name))) throw new Error("Invalid executor declaration");
      }
    }
  }
}

async function digest(value) {
  const bytes = new TextEncoder().encode(value);
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(hash)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function demo(env, request) {
  const asset = await env.ASSETS.fetch(new Request(new URL("/demo-data.json", request.url)));
  if (!asset.ok) throw new Error("Demo data was not built");
  return asset.json();
}

export default {
  async fetch(request, env) {
    const path = new URL(request.url).pathname;
    if (!path.startsWith("/api/")) return env.ASSETS.fetch(request);
    try {
      if (request.method === "GET" && path === "/api/setup/status") return json({ enabled: false, registered: false, connected: false, demo: true });
      if (request.method === "GET" && path === "/api/history") return json({ commits: [] });
      const data = await demo(env, request);
      if (request.method === "GET" && path === "/api/meta") return json({ version: data.version });
      if (request.method === "GET" && path === "/api/state") return json({ sha: data.sha, graph: data.graph, publishing: false, demo: true, file: "demo.yaml" });
      if (request.method === "POST" && path === "/api/pr") return fail(503, "GitHub publishing is available in the Docker example, not this public demo");
      if (request.method === "POST" && path === "/api/preview") {
        const raw = await request.text();
        if (raw.length > 65536) return fail(413, "Proposal is too large");
        const proposal = JSON.parse(raw);
        if (proposal.base_sha !== data.sha) return fail(409, "Canonical YAML changed. Reload before editing.");
        const source = validText(proposal.source, "source", 1000);
        const reason = validText(proposal.reason, "reason", 2000);
        if (reason.length < 5 || !Array.isArray(proposal.operations) || proposal.operations.length < 1 || proposal.operations.length > 30) throw new Error("A source, reason, and 1-30 changes are required");
        const updated = stringify(applyOperations(data.graph, proposal.operations, source));
        const diff = createTwoFilesPatch("a/demo.yaml", "b/demo.yaml", data.yaml, updated);
        if (data.yaml === updated) throw new Error("No change");
        return json({ base_sha: data.sha, preview_hash: await digest(data.sha + updated + source + reason), diff });
      }
      return fail(404, "Not found");
    } catch (error) {
      return fail(400, error.message || "Invalid request");
    }
  },
};
