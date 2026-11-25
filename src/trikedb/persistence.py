"""Getting the graph out of storage and back into it.

One YAML (or JSON) document holds the ontology, the nodes and the
triples; a workspace holds paths to several of those and reads them as
one. Where the bytes actually live — a local file or object storage — is
storage.py's question, not this module's.

Free functions taking the store, with `reload` and `save` kept as methods
on TrikeDB because they are public.
"""

from __future__ import annotations

import json
from copy import deepcopy
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from . import rules
from .model import Triple, _parse_document, _plain, _YamlDumper
from .storage import check_scheme as _check_scheme
from .storage import exists as _exists
from .storage import is_remote as _is_remote
from .storage import read_text as _read_text
from .storage import serialization as _serialization
from .storage import version as _version_of
from .storage import write_text as _write_text
from .workflow_source import _authored_workflow, _workflow_state
from .workflows import _validate_workflows, validate_agent_spec
from .yaml_source import (
    _roundtrip_yaml,
    _sync_authored_workflow,
    _sync_mapping,
    _sync_triples,
    attached_comment,
    format_long_inline,
    has_comments,
    parse_source,
)

if TYPE_CHECKING:
    from .db import TrikeDB


def locate(path):
    """What the constructor was handed, as the store should hold it.

    Local paths become Path; remote URLs (s3://, https://, ...) stay the
    strings they were, because splitting a URL on os.sep is how a bucket
    key turns into a directory that does not exist.
    """
    _check_scheme(path)
    return path if _is_remote(path) else (Path(path) if path else None)


def load_if_present(db) -> None:
    """Read the document now if there is one. A path with nothing at it is
    not an error — it is an empty graph that knows where it will be saved."""
    if db.path is not None and _exists(db.path):
        load(db)


def reload(db) -> TrikeDB:
    """Replace the in-memory graph only after the new document is valid.

    The way out of a ``ConcurrentWriteError``: someone else's version is
    now the real one, so pick it up and re-apply whatever you were doing
    on top of it.
    """
    fresh = type(db)(
        db.path, autosave=db.autosave, read_only=db._read_only_requested,
        sparql_engine=db.sparql_engine,
        validate_on_load=db.validate_on_load,
    )
    # Parsing can fail when a person is halfway through an edit. Keep the
    # old snapshot and its token in that case, so reads never see an empty
    # graph and a later write still conflicts with the changed file.
    for name in ("nodes_meta", "ontology", "predicate_descriptions_ja",
                 "predicate_rules", "_triples", "workspace", "read_only",
                 "_version", "_rdf_cache", "_index", "_index_len",
                 "_pidx", "_eidx", "_pidx_len", "_pending"):
        setattr(db, name, getattr(fresh, name))
    db._source_document = fresh._source_document
    db._workflow_states = fresh._workflow_states
    return db


def reload_local_if_changed(db) -> None:
    """Keep a long-running server's local snapshot in sync with file edits.

    Call under the graph lock, before handling a request. Python callers
    retain explicit reload semantics; stale Python writes fail on save.
    """
    if (isinstance(db.path, Path) and db.workspace is None
            and _version_of(db.path) != db._version):
        reload(db)


def load(db) -> None:
    # Version first, content second — the other order can hand us a token
    # that belongs to bytes we never saw. See storage.version.
    db._version = _version_of(db.path)
    source_text = _read_text(db.path)
    try:
        data = _parse_document(source_text)
    except yaml.YAMLError as exc:
        # PyYAML reports "<unicode string>", never the file it came from,
        # which is no help at all in a workspace of five members.
        raise ValueError(f"{db.path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        # Valid YAML that isn't a mapping — a bare string or list. Reaching
        # .get() on it blames whichever key we happened to ask for first,
        # which sends the reader looking in the wrong place entirely. More
        # than a theoretical worry once the graph lives in shared storage.
        raise ValueError(
            f"{db.path} does not hold a graph: expected a YAML mapping "
            f"with triples/nodes/ontology keys, found {type(data).__name__}"
        )
    for key, want in (("triples", list), ("nodes", dict), ("graphs", dict),
                      ("workflows", dict)):
        if key in data and data[key] is not None and not isinstance(data[key], want):
            # Left to itself this surfaces as .items() on a list or a
            # dict() on a string, several frames away from the file that
            # actually needs fixing.
            raise ValueError(
                f"{db.path}: '{key}:' must be a {want.__name__}, "
                f"found {type(data[key]).__name__}"
            )
    graphs = data.get("graphs")
    if isinstance(graphs, dict) and not data.get("triples"):
        if data.get("workflows"):
            raise ValueError(
                f"{db.path}: 'workflows:' must be declared in a graph document, "
                "not alongside workspace 'graphs:'"
            )
        load_workspace(db, graphs)
        return
    onto = data.get("ontology") or {}
    preds = onto.get("predicates", onto) if isinstance(onto, dict) else onto
    if not isinstance(preds, (dict, list, tuple)):
        raise ValueError(
            f"{db.path}: 'ontology:' must be a mapping of predicate to "
            f"description (or a list of predicates), found "
            f"{type(preds).__name__}"
        )
    if isinstance(preds, dict):
        for k, v in preds.items():
            rules.declare_predicate(db, str(k), v, keep_existing=True)
    elif isinstance(preds, (list, tuple)):
        for p in preds:
            db.ontology.setdefault(str(p), "")
    declared_nodes = data.get("nodes") or {}
    workflows = data.get("workflows") or {}
    workflow_nodes, workflow_triples = _compile_workflows(db.path, workflows, declared_nodes)
    for name, props in declared_nodes.items():
        db.nodes_meta[str(name)] = _plain(dict(props or {}))
    for name, props in workflow_nodes.items():
        db.nodes_meta[name] = _plain(props)
    triples = list(data.get("triples") or []) + workflow_triples
    for item in triples:
        db._triples.append(Triple.from_dict(item))
    if workflows:
        # The shorthand has a stricter contract than arbitrary graph triples:
        # reject a malformed process at the point it enters the RDF store.
        try:
            _validate_workflows(workflow_triples, {"NEXT_STEP"}, "HAS_STEP")
        except ValueError as exc:
            raise ValueError(f"{db.path}: {exc}") from exc
    db._rdf_cache = None
    db._index = db._pidx = db._eidx = None
    if _serialization(db.path) != "json":
        # Parsing for comments is only needed by writers. Keep reads fast.
        db._source_document = source_text
    elif workflows:
        db._source_document = deepcopy(data)
    if workflows:
        db._workflow_states = {str(wid): _workflow_state(db, str(wid)) for wid in workflows}


def format_for_review(db, *, width: int = 100, workflows: bool = False):
    """Make source YAML readable without changing its graph facts."""
    if db._source_document is None or _serialization(db.path) == "json":
        raise ValueError("format requires an existing YAML graph file")
    source = _source_tree(db)
    if workflows:
        had_workflows = "workflows" in source
        authored = source.get("workflows")
        if authored is None:
            authored = {}
            source["workflows"] = authored
        for wid, meta in db.nodes_meta.items():
            if meta.get("type") != "workflow" or wid in authored:
                continue
            state = _workflow_state(db, wid)
            declaration = _authored_workflow(state)
            if declaration is not None:
                nodes = source.get("nodes") or {}
                steps = {link["o"] for link in state["membership"]}
                if any(
                    attached_comment(nodes, name) or has_comments(nodes.get(name))
                    for name in {wid, *steps}
                ):
                    raise ValueError(
                        f"workflow {wid!r} has node comments; "
                        "move them into workflows: before conversion"
                    )
                triples = source.get("triples") or []
                for index, triple in enumerate(triples):
                    structural = triple["p"] == "HAS_STEP" and triple["s"] == wid
                    structural |= (
                        triple["p"] == "NEXT_STEP"
                        and triple["s"] in steps
                        and triple["o"] in steps
                    )
                    if structural and (attached_comment(triples, index) or has_comments(triple)):
                        raise ValueError(
                            f"workflow {wid!r} has relation comments; "
                            "move them into workflows: before conversion"
                        )
                authored[wid] = declaration
        if not authored and not had_workflows:
            source.pop("workflows", None)
    format_long_inline(source, width=width)
    return save(db, width=width)


def _source_tree(db):
    db._source_document = parse_source(db._source_document)
    return db._source_document


def _compile_workflows(path, workflows: dict, existing_nodes: dict):
    """Expand author-friendly workflow declarations into ordinary graph data.

    ``workflows:`` is an editable source form. Its RDF projection is the same node
    metadata and RDF triples used by every other TrikeDB feature, so queries,
    Oxigraph, and the HTML picker do not have a parallel workflow store.
    """
    if not workflows:
        return {}, []
    if not isinstance(workflows, dict):  # also protects callers outside load()
        raise ValueError(f"{path}: 'workflows:' must be a mapping")

    nodes: dict[str, dict] = {}
    triples: list[dict] = []
    errors: list[str] = []

    def fail(where: str, message: str) -> None:
        errors.append(f"{where}: {message}")

    for workflow_id, raw in workflows.items():
        wid = str(workflow_id)
        where = f"workflows.{wid}"
        if not isinstance(raw, dict):
            fail(where, "must be a mapping")
            continue
        allowed = {"label", "summary", "description", "tags", "workflow_facets",
                   "properties", "steps"}
        extra = set(raw) - allowed
        if extra:
            fail(where, f"unknown field(s): {', '.join(sorted(map(str, extra)))}")
        if wid in existing_nodes or wid in nodes:
            fail(where, f"node id {wid!r} is already declared")
        steps = raw.get("steps")
        if not isinstance(steps, list) or not steps:
            fail(where, "'steps:' must be a non-empty list")
            continue
        props = raw.get("properties", {})
        if not isinstance(props, dict):
            fail(f"{where}.properties", "must be a mapping")
            props = {}
        elif set(props) & {"type", "label", "summary", "description", "tags", "workflow_facets"}:
            fail(f"{where}.properties", "put reserved workflow fields at the workflow level")
        metadata = dict(props)
        metadata["type"] = "workflow"
        for field in ("label", "summary", "description", "tags", "workflow_facets"):
            if field in raw:
                metadata[field] = raw[field]
        nodes[wid] = metadata

        step_ids: list[str] = []
        normalized_steps: list[tuple[str, dict]] = []
        for index, item in enumerate(steps, start=1):
            step_where = f"{where}.steps[{index - 1}]"
            if not isinstance(item, dict):
                fail(step_where, "must be a mapping")
                continue
            allowed_step = {"id", "label", "description", "properties", "order", "next", "next_mode", "agent"}
            unknown = set(item) - allowed_step
            if unknown:
                fail(step_where, f"unknown field(s): {', '.join(sorted(map(str, unknown)))}")
            if "id" not in item or not isinstance(item["id"], (str, int)):
                fail(step_where, "requires a string or integer 'id'")
                continue
            sid = str(item["id"])
            if not sid:
                fail(step_where, "'id' cannot be empty")
                continue
            if sid in existing_nodes or sid in nodes or sid in step_ids:
                fail(step_where, f"node id {sid!r} is already declared")
            step_ids.append(sid)
            step_props = item.get("properties", {})
            if not isinstance(step_props, dict):
                fail(f"{step_where}.properties", "must be a mapping")
                step_props = {}
            elif set(step_props) & {"type", "label", "description", "agent", "next_mode"}:
                fail(f"{step_where}.properties", "put reserved step fields at the step level")
            step_meta = dict(step_props)
            step_meta["type"] = "process_step"
            for field in ("label", "description"):
                if field in item:
                    step_meta[field] = item[field]
            if "next_mode" in item:
                if item["next_mode"] != "choose_one":
                    fail(step_where, "next_mode must be choose_one")
                else:
                    step_meta["next_mode"] = "choose_one"
            if "agent" in item:
                try:
                    step_meta["agent"] = validate_agent_spec(item["agent"], step_where)
                except ValueError as exc:
                    fail(step_where, str(exc).split(": ", 1)[-1])
            nodes[sid] = step_meta
            normalized_steps.append((sid, item))

        for index, (sid, item) in enumerate(normalized_steps, start=1):
            order = item.get("order", index)
            triples.append({"s": wid, "p": "HAS_STEP", "o": sid, "order": order})
            next_ids = item.get("next", [])
            if isinstance(next_ids, (str, int)):
                next_ids = [next_ids]
            if not isinstance(next_ids, list):
                fail(f"{where}.steps[{index - 1}].next", "must be a node id or list of node ids")
                continue
            if item.get("next_mode") == "choose_one" and len(next_ids) < 2:
                fail(step_where, "choose_one requires at least two next steps")
            for target in next_ids:
                target_id = str(target)
                if target_id not in step_ids:
                    fail(f"{where}.steps[{index - 1}].next", f"unknown step id {target_id!r}")
                else:
                    triples.append({"s": sid, "p": "NEXT_STEP", "o": target_id})

    if errors:
        raise ValueError(f"{path}: invalid workflow declaration:\n- " + "\n- ".join(errors))
    return nodes, triples


def load_workspace(db, graphs: dict) -> None:
    """Union view over member graphs. The union is read-only — write to a
    member graph instead.

    Three details decide what the union contains, and all three are easy
    to get wrong when reimplementing this by hand:

    - **Node properties merge per key, not per node.** A node declared in
      two members keeps the first value of each *key*, so a description
      only the second member carries still survives. Taking the whole
      dict from the first member instead drops it silently.
    - **Ontologies merge per predicate**, first member wins the
      description.
    - **A triple's `graph` attribute is the workspace key**, not the
      member's path or filename.
    """
    if not graphs:
        raise ValueError(
            f"{db.path}: 'graphs:' is empty — a workspace needs at least "
            "one member ({name: path})"
        )
    db.workspace = {str(k): str(v) for k, v in graphs.items()}
    db.read_only = True
    base_dir = None if _is_remote(db.path) else Path(db.path).parent
    for name, gpath in db.workspace.items():
        if not _is_remote(gpath) and base_dir is not None and not Path(gpath).is_absolute():
            gpath = str(base_dir / gpath)
        # Members inherit the connection: a union whose members live in a
        # warehouse has to reach it the same way this graph did, and a
        # host that cannot open its own connection cannot open one here
        # either.
        if not _exists(gpath):
            # Not the same as an empty member: the workspace named this
            # file, so a typo here silently drops a whole graph out of
            # the union and every query just returns less.
            raise FileNotFoundError(
                f"{db.path}: workspace member '{name}' points at "
                f"{gpath}, which does not exist"
            )
        # A member of a workspace is another store of the same kind, so
        # ask the instance rather than importing the class back — the one
        # place this module would otherwise have to know about db.py.
        sub = type(db)(gpath)
        for k, v in sub.ontology.items():
            db.ontology.setdefault(k, v)
        for k, v in sub.predicate_descriptions_ja.items():
            db.predicate_descriptions_ja.setdefault(k, v)
        for k, rule in sub.predicate_rules.items():
            db.predicate_rules.setdefault(k, rule)
        for n, props in sub.nodes_meta.items():
            merged = db.nodes_meta.setdefault(n, {})
            for k, v in props.items():
                merged.setdefault(k, v)
        for t in sub:
            db._triples.append(Triple(t.s, t.p, t.o, {**t.attrs, "graph": name}, t.rdf_terms))
    db._index = db._pidx = db._eidx = None


def guard_writable(db) -> None:
    # Every method that can change the graph calls this first, which makes
    # it the one place a cache of the built RDF graph can be dropped
    # without hunting for mutation sites. Over-invalidating (save() also
    # passes through here) costs a rebuild; under-invalidating would
    # answer queries from a graph that no longer exists, so the
    # conservative side is the only safe one.
    db._rdf_cache = None
    if not db.read_only:
        return
    if db.workspace is not None:
        raise ValueError(
            "this is a read-only workspace union — write to one of its "
            f"member graphs instead: {db.workspace}"
        )
    # Naming the reason matters: "read-only" on its own reads like a
    # filesystem permission problem to go and fix, when in fact the caller
    # asked for this and the fix is to stop writing here.
    raise ValueError(
        f"{db.path} was opened read_only=True — mutations are refused. "
        "Open it without read_only to write, or write through whichever "
        "path owns this graph"
    )


def save(db, path: str | Path | None = None, *, width: int | None = None):
    """Write the graph back out, retaining authored workflows as workflows.

    Works for local paths and object URLs (s3://, ...). On local files and S3 the write is
    conditional on the stored graph still being the one this copy was
    read from: if another writer got there first, nothing is written and
    ``ConcurrentWriteError`` is raised — call ``reload()`` and re-apply.
    Other remote backends without conditional writes stay last-write-wins.

    Files get YAML by default because a person reads those. A .json path gets JSON.
    """
    guard_writable(db)
    rules.settle(db)   # a file that breaks its own ontology never gets out
    if path is None:
        target = db.path
    else:
        target = path if _is_remote(path) else Path(path)
    if target is None:
        raise ValueError("no path given and TrikeDB was created without one")
    doc: dict = {}
    if db.ontology:
        doc["ontology"] = {
            "predicates": {p: rules.declaration(db, p) for p in db.ontology}
        }
    if db.nodes_meta:
        doc["nodes"] = {k: dict(v) for k, v in db.nodes_meta.items()}
    doc["triples"] = [t.to_dict() for t in db._triples]
    source = _source_tree(db) if db._source_document is not None else None
    if source is not None:
        old_ontology = source.get("ontology") or {}
        if not isinstance(old_ontology, dict):
            old_ontology = {}
        old_predicates = old_ontology.get("predicates", old_ontology)
        if isinstance(old_predicates, dict) and "ontology" in doc:
            declarations = doc["ontology"]["predicates"]
            for predicate, declaration in declarations.items():
                previous = old_predicates.get(predicate)
                if (isinstance(previous, dict) and set(previous) == {"description"}
                        and previous["description"] == declaration):
                    declarations[predicate] = previous
            if "predicates" not in old_ontology:
                doc["ontology"] = declarations
        authored = {}
        hidden_nodes = set()
        hidden_memberships = set()
        hidden_successors = set()
        for wid_key, original in source.get("workflows", {}).items():
            wid = str(wid_key)
            state = _workflow_state(db, wid)
            workflow = _authored_workflow(state)
            if workflow is None:
                continue
            # An untouched declaration keeps its spelling, comments and flow style.
            authored[wid_key] = original if state == db._workflow_states.get(wid) else workflow
            members = {t["o"] for t in state["membership"]}
            if hidden_nodes.intersection(members):
                raise ValueError(f"workflow steps belong to multiple authored workflows: {hidden_nodes & members}")
            hidden_nodes.update({wid, *members})
            hidden_memberships.update((t["s"], t["p"], t["o"])
                                      for t in state["membership"])
            hidden_successors.update((t["s"], t["p"], t["o"])
                                     for t in state["successors"])
        if authored:
            doc["workflows"] = authored
        doc["nodes"] = {k: v for k, v in doc.get("nodes", {}).items()
                        if k not in hidden_nodes}
        doc["triples"] = [t for t in doc["triples"]
                          if (t["s"], t["p"], t["o"]) not in
                          hidden_memberships | hidden_successors]
        if not doc["nodes"]:
            doc.pop("nodes")
        if authored:
            _, projected = _compile_workflows(target, authored, doc.get("nodes", {}))
            _validate_workflows(projected, {"NEXT_STEP"}, "HAS_STEP")
    if source is not None and not doc["triples"] and "triples" not in source:
        doc.pop("triples")
    if _serialization(target) == "json":
        text = json.dumps(doc, ensure_ascii=False, indent=2)
    elif source is not None:
        # Update the source tree in place so comments in unchanged sections
        # survive edits elsewhere. The graph is still the source of the values.
        for key in ("ontology", "nodes", "triples", "workflows"):
            value = doc.get(key)
            if value is None:
                source.pop(key, None)
            elif key == "workflows":
                existing = source.get("workflows", {})
                for wid in list(existing):
                    if wid not in value:
                        del existing[wid]
                for wid, workflow in value.items():
                    if wid not in existing:
                        existing[wid] = workflow
                    elif existing[wid] is not workflow:
                        _sync_authored_workflow(existing[wid], workflow)
                source["workflows"] = existing
            elif key not in source:
                source[key] = value
            elif key == "triples" and _plain(source[key]) != _plain(value):
                _sync_triples(source[key], value)
            elif isinstance(source[key], dict) and isinstance(value, dict):
                _sync_mapping(source[key], value)
            elif _plain(source[key]) != _plain(value):
                source[key] = value
        formatter = _roundtrip_yaml()
        formatter.allow_unicode = True
        formatter.width = width if width is not None else 4096
        formatter.indent(mapping=2, sequence=4, offset=2)
        output = StringIO()
        formatter.dump(source, output)
        text = output.getvalue()
    else:
        text = yaml.dump(
            doc,
            Dumper=_YamlDumper,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=None,
            width=120,
        )
    if target == db.path:
        # Same file we read: refuse to overwrite someone else's save.
        db._version = _write_text(target, text, expect=db._version)
    else:  # save-as: nothing to compare against
        db._version = _write_text(target, text)
    db.path = target
    if source is not None:
        db._source_document = text if _serialization(target) != "json" else json.loads(text)
        db._workflow_states = {str(wid): _workflow_state(db, str(wid))
                               for wid in source.get("workflows", {}) if str(wid) in db.nodes_meta}
    return target
