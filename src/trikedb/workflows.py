"""Validation for workflow membership and directed order graphs."""

from __future__ import annotations


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
