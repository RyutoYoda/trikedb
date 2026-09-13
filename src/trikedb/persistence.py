"""Getting the graph out of storage and back into it.

One YAML (or JSON) document holds the ontology, the nodes and the
triples; a workspace holds paths to several of those and reads them as
one. Where the bytes actually live — a file, S3, a warehouse row — is
storage.py's question, not this module's.

Free functions taking the store, with `reload` and `save` kept as methods
on TrikeDB because they are public.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Union

import yaml

from . import rules
from .model import Triple, _YamlDumper, _parse_document, _plain
from .storage import check_scheme as _check_scheme
from .storage import exists as _exists
from .storage import is_remote as _is_remote
from .storage import read_text as _read_text
from .storage import serialization as _serialization
from .storage import version as _version_of
from .storage import write_text as _write_text


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
    if db.path is not None and _exists(db.path, db._connection):
        load(db)


def reload(db) -> "TrikeDB":
    """Throw away the in-memory graph and read it again from storage.

    The way out of a ``ConcurrentWriteError``: someone else's version is
    now the real one, so pick it up and re-apply whatever you were doing
    on top of it.
    """
    db.nodes_meta = {}
    db.ontology = {}
    db.predicate_rules = {}
    db._triples = []
    db.workspace = None
    db.read_only = db._read_only_requested   # a reload must not grant writes
    db._version = None
    db._rdf_cache = None
    # Not just for tidiness: the length check in _spo_index cannot see a
    # replacement that happens to be the same length, and a stale entry
    # would make add() think a triple is already there and drop it.
    db._index = db._pidx = db._eidx = None
    if db.path is not None and _exists(db.path, db._connection):
        load(db)
    return db


def load(db) -> None:
    # Version first, content second — the other order can hand us a token
    # that belongs to bytes we never saw. See storage.version.
    db._version = _version_of(db.path, db._connection)
    try:
        data = _parse_document(_read_text(db.path, connection=db._connection))
    except yaml.YAMLError as exc:
        # PyYAML reports "<unicode string>", never the file it came from,
        # which is no help at all in a workspace of five members.
        raise ValueError(f"{db.path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        # Valid YAML that isn't a mapping — a bare string or list. Reaching
        # .get() on it blames whichever key we happened to ask for first,
        # which sends the reader looking in the wrong place entirely. More
        # than a theoretical worry once the graph lives somewhere other
        # people can write to, like a shared warehouse table.
        raise ValueError(
            f"{db.path} does not hold a graph: expected a YAML mapping "
            f"with triples/nodes/ontology keys, found {type(data).__name__}"
        )
    for key, want in (("triples", list), ("nodes", dict), ("graphs", dict)):
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
    for name, props in (data.get("nodes") or {}).items():
        db.nodes_meta[str(name)] = _plain(dict(props or {}))
    for item in data.get("triples") or []:
        db._triples.append(Triple.from_dict(item))
    db._rdf_cache = None
    db._index = db._pidx = db._eidx = None


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
        if not _exists(gpath, db._connection):
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
        sub = type(db)(gpath, connection=db._connection)
        for k, v in sub.ontology.items():
            db.ontology.setdefault(k, v)
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


def save(db, path: Union[str, Path, None] = None):
    """Write the graph back out. Plain triples stay on one line.

    Works for local paths, remote URLs (s3://, ...) and warehouse rows
    (snowflake://) alike. On S3 and in a warehouse the write is
    conditional on the stored graph still being the one this copy was
    read from: if another writer got there first, nothing is written and
    ``ConcurrentWriteError`` is raised — call ``reload()`` and re-apply.
    Backends without conditional writes stay last-write-wins.

    Files get YAML, because a person reads those. A warehouse row gets
    JSON, so SQL can see inside it; see ``storage.serialization``.
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
    if _serialization(target) == "json":
        text = json.dumps(doc, ensure_ascii=False, indent=2)
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
        db._version = _write_text(target, text, expect=db._version, connection=db._connection)
    else:  # save-as: nothing to compare against
        db._version = _write_text(target, text, connection=db._connection)
    db.path = target
    return target
