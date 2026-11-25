"""Project authored workflows onto graph facts and back for editing."""

from __future__ import annotations

from copy import deepcopy


def _workflow_state(db, wid: str) -> dict:
    """The editable graph facts belonging to one authored workflow."""
    members = [t for t in db._triples if t.s == wid and t.p == "HAS_STEP"]
    steps = {t.o for t in members}
    return {
        "workflow": deepcopy(db.nodes_meta.get(wid)),
        "steps": {sid: deepcopy(db.nodes_meta.get(sid)) for sid in steps},
        "membership": [t.to_dict() for t in members],
        "successors": [t.to_dict() for t in db._triples
                       if t.s in steps and t.p == "NEXT_STEP" and t.o in steps],
    }


def _authored_workflow(state: dict) -> dict | None:
    meta = state["workflow"]
    members = state["membership"]
    if not meta or meta.get("type") != "workflow" or not members:
        return None
    result = {key: deepcopy(meta[key]) for key in
              ("label", "summary", "description", "tags", "workflow_facets") if key in meta}
    extras = {k: deepcopy(v) for k, v in meta.items()
              if k not in {"type", "label", "summary", "description", "tags", "workflow_facets"}}
    if extras:
        result["properties"] = extras
    members = sorted(members, key=lambda t: (t.get("order", 0), t["o"]))
    steps = []
    for index, link in enumerate(members, 1):
        sid = link["o"]
        props = state["steps"].get(sid) or {"type": "process_step"}
        if props.get("type") != "process_step":
            raise ValueError(f"workflow step {sid!r} must have type process_step")
        if set(link) - {"s", "p", "o", "order"}:
            raise ValueError(f"workflow membership {sid!r} has attributes that workflows: cannot store")
        item = {"id": sid}
        for key in ("label", "description"):
            if key in props:
                item[key] = deepcopy(props[key])
        if link.get("order", index) != index:
            item["order"] = link["order"]
        for key in ("next_mode", "agent"):
            if key in props:
                item[key] = deepcopy(props[key])
        extra = {k: deepcopy(v) for k, v in props.items()
                 if k not in {"type", "label", "description", "next_mode", "agent"}}
        if extra:
            item["properties"] = extra
        successors = [t["o"] for t in state["successors"] if t["s"] == sid]
        if any(set(t) - {"s", "p", "o"} for t in state["successors"] if t["s"] == sid):
            raise ValueError(f"workflow successor from {sid!r} has attributes that workflows: cannot store")
        if successors:
            item["next"] = successors
        steps.append(item)
    result["steps"] = steps
    return result
