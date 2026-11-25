"""Validation for workflow membership and directed order graphs."""

from __future__ import annotations

import re


def validate_agent_spec(value, where: str) -> dict:
    """Validate the optional agent-facing contract on a process step.

    Tool names and entry conditions describe work; gates and outputs are the
    fields the run ledger can require evidence for. No external tool is run
    merely because its name appears here.
    """
    if not isinstance(value, dict):
        raise ValueError(f"{where}: 'agent' must be a mapping")
    unknown = set(value) - {"tools", "entry", "outputs", "gates", "skippable"}
    if unknown:
        raise ValueError(f"{where}: unknown agent field(s): {', '.join(sorted(unknown))}")
    result = {}
    if "skippable" in value:
        if not isinstance(value["skippable"], bool):
            raise ValueError(f"{where}.agent.skippable: must be a boolean")
        if value["skippable"]:
            result["skippable"] = True
    for key in ("tools", "entry", "outputs"):
        items = value.get(key, [])
        if not isinstance(items, list) or any(
            not isinstance(item, str) or not item.strip() for item in items
        ):
            raise ValueError(f"{where}.agent.{key}: must be a list of non-empty strings")
        if len(items) != len(set(items)):
            raise ValueError(f"{where}.agent.{key}: duplicate values are not allowed")
        result[key] = items
    gates = value.get("gates", [])
    if not isinstance(gates, list):
        raise ValueError(f"{where}.agent.gates: must be a list")
    seen = set()
    for gate in gates:
        if not isinstance(gate, dict) or not {"id", "kind", "description"} <= set(gate):
            raise ValueError(f"{where}.agent.gates: each gate needs id, kind and description")
        if not isinstance(gate["kind"], str) or gate["kind"] not in {"test", "e2e", "review", "manual"}:
            raise ValueError(f"{where}.agent.gates: invalid kind {gate['kind']!r}")
        if any(not isinstance(gate[key], str) or not gate[key].strip()
               for key in ("id", "description")):
            raise ValueError(f"{where}.agent.gates: id and description must be non-empty strings")
        if gate["id"] in seen:
            raise ValueError(f"{where}.agent.gates: duplicate id {gate['id']!r}")
        verifier = gate.get("verifier")
        if verifier is None:
            allowed = {"id", "kind", "description"}
        elif verifier == "junit":
            allowed = {"id", "kind", "description", "verifier"}
            if gate["kind"] not in {"test", "e2e"}:
                raise ValueError(f"{where}.agent.gates: junit requires a test or e2e gate")
        elif verifier == "github_actions":
            allowed = {"id", "kind", "description", "verifier", "repository", "subject_artifact"}
            if gate["kind"] not in {"test", "e2e"}:
                raise ValueError(f"{where}.agent.gates: github_actions requires a test or e2e gate")
            if not isinstance(gate.get("repository"), str) or not re.fullmatch(
                r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", gate["repository"]
            ):
                raise ValueError(f"{where}.agent.gates: github_actions needs a repository")
            if gate.get("subject_artifact") not in result["outputs"]:
                raise ValueError(f"{where}.agent.gates: subject_artifact must name an output")
        else:
            raise ValueError(f"{where}.agent.gates: unsupported verifier")
        if set(gate) != allowed:
            raise ValueError(f"{where}.agent.gates: unexpected or missing verifier fields")
        seen.add(gate["id"])
    result["gates"] = gates
    return result


def _validate_workflows(triples: list[dict], order_predicates: set[str],
                        membership_predicate: str) -> None:
    """Reject workflow membership/order that cannot describe one process.

    Workflow membership scopes process steps; configured order predicates
    define directed adjacency. Branches and rejoins are valid, but the order
    graph must be one connected DAG. Context relations remain independent.
    """
    members: dict[str, set[str]] = {}
    orders: dict[str, dict[str, list[object]]] = {}
    for triple in triples:
        if triple["p"] != membership_predicate:
            continue
        workflow, step = triple["s"], triple["o"]
        members.setdefault(workflow, set()).add(step)
        if "order" in triple:
            orders.setdefault(workflow, {}).setdefault(step, []).append(triple["order"])

    if not members:
        return
    errors: list[str] = []
    owners: dict[str, set[str]] = {}
    for workflow, steps in members.items():
        for step in steps:
            owners.setdefault(step, set()).add(workflow)
            values = orders.get(workflow, {}).get(step, [])
            if len(values) > 1:
                errors.append(f"workflow {workflow!r} assigns step {step!r} more than once")
            elif values:
                value = values[0]
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    errors.append(f"workflow {workflow!r} has invalid order {value!r} for step {step!r}; use a positive integer")

    adjacency: dict[str, dict[str, set[str]]] = {
        workflow: {step: set() for step in steps} for workflow, steps in members.items()
    }
    for triple in triples:
        if triple["p"] not in order_predicates:
            continue
        source, target = triple["s"], triple["o"]
        source_owners, target_owners = owners.get(source, set()), owners.get(target, set())
        common = source_owners & target_owners
        if not common:
            # Unrelated processes may share the same predicate in a mixed KG.
            if not source_owners and not target_owners:
                continue
            errors.append(f"{triple['p']} edge {source!r} -> {target!r} must connect steps in the same workflow")
            continue
        for workflow in common:
            adjacency[workflow][source].add(target)
            source_order = orders.get(workflow, {}).get(source, [])
            target_order = orders.get(workflow, {}).get(target, [])
            valid_source = source_order and isinstance(source_order[0], int) and not isinstance(source_order[0], bool)
            valid_target = target_order and isinstance(target_order[0], int) and not isinstance(target_order[0], bool)
            if valid_source and valid_target and source_order[0] >= target_order[0]:
                errors.append(f"workflow {workflow!r} orders {source!r} ({source_order[0]}) before {target!r} ({target_order[0]}), but the values are not increasing")

    for workflow, graph in adjacency.items():
        indegree = dict.fromkeys(graph, 0)
        undirected = {step: set() for step in graph}
        for source, targets in graph.items():
            for target in targets:
                indegree[target] += 1
                undirected[source].add(target)
                undirected[target].add(source)
        queue = [step for step, degree in indegree.items() if degree == 0]
        visited = 0
        while queue:
            source = queue.pop()
            visited += 1
            for target in graph[source]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    queue.append(target)
        if visited != len(graph):
            errors.append(f"workflow {workflow!r} contains a cycle in its order relations")
        if graph:
            reached: set[str] = set()
            stack = [next(iter(graph))]
            while stack:
                step = stack.pop()
                if step in reached:
                    continue
                reached.add(step)
                stack.extend(undirected[step] - reached)
            if len(reached) != len(graph):
                errors.append(f"workflow {workflow!r} has steps disconnected from its order graph")

    if errors:
        raise ValueError("Invalid workflow definition:\n- " + "\n- ".join(dict.fromkeys(errors)))
