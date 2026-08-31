"""Core triple store: a knowledge graph persisted as a single YAML file."""

from __future__ import annotations

import fnmatch
import json
import shlex
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence, Union

import yaml

__all__ = ["Triple", "TrikeDB", "OntologyError"]


class OntologyError(ValueError):
    """Raised when a triple uses a predicate not declared in the ontology."""


from .storage import check_scheme as _check_scheme
from .storage import exists as _exists
from .storage import is_remote as _is_remote
from .storage import read_text as _read_text
from .storage import serialization as _serialization
from .storage import version as _version_of
from .storage import write_text as _write_text


def _term(value, field: str, whole=None) -> str:
    """A triple's three terms are names, and a name has to be something.

    ``None`` is the one that matters: left alone it becomes the string
    ``"None"``, and the graph grows a node called None that joins to every
    other missing value in it.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        shown = f": {whole!r}" if whole is not None else ""
        raise ValueError(f"triple {field} is empty{shown}")
    return str(value)


@dataclass
class Triple:
    """A single subject-predicate-object statement, with optional attributes."""

    s: str
    p: str
    o: str
    attrs: dict = field(default_factory=dict)

    def spo(self) -> tuple:
        return (self.s, self.p, self.o)

    def to_dict(self) -> dict:
        return {"s": self.s, "p": self.p, "o": self.o, **self.attrs}

    @classmethod
    def from_dict(cls, data: dict) -> "Triple":
        d = dict(data)
        try:
            s, p, o = d.pop("s"), d.pop("p"), d.pop("o")
        except KeyError as exc:
            raise ValueError(f"triple is missing required key {exc}: {data!r}") from None
        s, p, o = _term(s, "s", data), _term(p, "p", data), _term(o, "o", data)
        return cls(s, p, o, d)


#: libyaml if PyYAML was built with it, which is the usual case. Four to five
#: times faster than the pure-Python parser on the same bytes, and — verified
#: byte-for-byte on graphs up to a megabyte — the dumper emits exactly the
#: same text, so switching cannot churn anyone's diffs.
try:
    _YamlLoader = yaml.CSafeLoader
    _YamlDumper = yaml.CSafeDumper
except AttributeError:  # pragma: no cover - PyYAML built without libyaml
    _YamlLoader = yaml.SafeLoader
    _YamlDumper = yaml.SafeDumper


def _oxigraph_available() -> bool:
    """Is the faster SPARQL engine installed?

    A core dependency, so normally yes — it was faster at every graph size
    measured, down to a few hundred triples. This is still a question rather
    than an assumption because trikedb reaches places pip does not: hosts
    that allow only a curated package channel (pyoxigraph is absent from
    Snowflake's, for one), and hosts where trikedb is vendored as a subset of
    its files. There, reads fall back to rdflib and everything keeps working,
    slower.
    """
    try:
        import pyoxigraph  # noqa: F401
    except ImportError:
        return False
    return True


def _parse_document(text: str) -> dict:
    """Parse a stored graph, whichever of the two forms it is in.

    JSON first, because a warehouse row holds JSON and ``json.loads`` reads
    it about 400x faster than a YAML parser does — 12ms against 5s on 50k
    triples. Feeding JSON to the YAML parser is *correct*, which is why it
    went unnoticed; it is just enormously slower.

    The fallback is free: JSON parsing of a YAML document fails on the first
    key, in 8 microseconds. So the order costs nothing for files and saves
    almost everything for rows. Both parsers agree on any JSON document —
    JSON is a subset of YAML — so which one ran is not observable.
    """
    if not text or not text.strip():
        return {}
    stripped = text.lstrip()
    if stripped[0] in "{[":
        try:
            return json.loads(text)
        except ValueError:
            pass                      # a YAML flow-style document, then
    return yaml.load(text, Loader=_YamlLoader) or {}


def _term_match(pattern: Optional[str], value: str) -> bool:
    """None is a wildcard; '*'/'?' in a pattern enables glob matching."""
    if pattern is None:
        return True
    if any(ch in pattern for ch in "*?[") :
        return fnmatch.fnmatchcase(value, pattern)
    return pattern == value


class TrikeDB:
    """A YAML-backed triple store with a graph-database interface.

    >>> db = TrikeDB("graph.yaml")
    >>> db.add("salesflow-crm", "PROVIDES", "crm-sync-job")
    >>> for t in db.triples(p="PROVIDES"):
    ...     print(t.s, "->", t.o)
    >>> db.save()
    """

    def __init__(
        self,
        path: Union[str, Path, None] = None,
        ontology: Union[dict, Sequence[str], None] = None,
        autosave: bool = True,
        read_only: bool = False,
        connection=None,
        sparql_engine: Optional[str] = None,
    ):
        _check_scheme(path)
        #: local paths become Path; remote URLs (s3://, https://, ...) stay str
        self.path: Union[Path, str, None] = (
            path if _is_remote(path) else (Path(path) if path else None)
        )
        #: when True (the default), every mutation writes straight back to
        #: the file — what you add is what's on disk, same as the CLI.
        #: Pass autosave=False to batch mutations and call save() yourself.
        self.autosave = autosave
        #: workspace member graphs ({name: path}) when this is a union view
        self.workspace: Optional[dict] = None
        #: asked for at construction, as opposed to implied by a workspace
        #: union. Kept apart because reload() has to be able to restore it:
        #: forgetting it there would silently hand back a writable graph.
        self._read_only_requested = bool(read_only)
        #: an already-open warehouse connection or Snowpark session to run
        #: through, for hosts that cannot open one themselves. Ignored for
        #: file-backed graphs, which have nothing to connect to.
        self._connection = connection
        #: True for workspace unions and for read_only=True — mutations are
        #: refused. A reader that cannot write is the point when the graph is
        #: shared: an app serving a warehouse-backed graph has no business
        #: holding a write path, and a bug or an agent cannot spend one it
        #: does not have.
        self.read_only = self._read_only_requested
        #: node name -> free-form properties (type, label, url, description, ...)
        self.nodes_meta: dict = {}
        #: predicate -> human description. Empty dict means free-form predicates.
        self.ontology: dict = {}
        self._triples: list = []
        #: open batch() blocks; while any is open, autosave holds its write
        self._batch_depth = 0
        #: storage token the in-memory graph was built from; see storage.version
        self._version = None
        #: (base, engine) -> a built query graph. sparql() used to rebuild one
        #: per call, which was two thirds of its cost; see _query_graph.
        self._rdf_cache: Optional[tuple] = None
        #: (s, p, o) -> Triple, so add() does not scan; see _spo_index
        self._index: Optional[dict] = None
        self._index_len = -1
        #: which engine answers read queries: "oxigraph" when the extra is
        #: installed, else "rdflib". Pass sparql_engine="rdflib" to pin it —
        #: worth doing if you ever need to compare the two on a real query,
        #: since they are separate SPARQL 1.1 implementations. Updates, OWL
        #: inference and SHACL always go through rdflib.
        if sparql_engine is not None and sparql_engine not in ("oxigraph", "rdflib"):
            # Falling back silently means the engine you asked to compare
            # against is not the one that answered.
            raise ValueError(
                f"unknown sparql_engine {sparql_engine!r} - use 'oxigraph' or 'rdflib'"
            )
        self.sparql_engine = sparql_engine or (
            "oxigraph" if _oxigraph_available() else "rdflib")
        if ontology is not None:
            if isinstance(ontology, dict):
                self.ontology = {str(k): str(v or "") for k, v in ontology.items()}
            else:
                self.ontology = {str(p): "" for p in ontology}
        if self.path is not None and _exists(self.path, self._connection):
            self._load()

    # ------------------------------------------------------------------ io

    def reload(self) -> "TrikeDB":
        """Throw away the in-memory graph and read it again from storage.

        The way out of a ``ConcurrentWriteError``: someone else's version is
        now the real one, so pick it up and re-apply whatever you were doing
        on top of it.
        """
        self.nodes_meta = {}
        self._triples = []
        self.workspace = None
        self.read_only = self._read_only_requested   # a reload must not grant writes
        self._version = None
        self._rdf_cache = None
        # Not just for tidiness: the length check in _spo_index cannot see a
        # replacement that happens to be the same length, and a stale entry
        # would make add() think a triple is already there and drop it.
        self._index = None
        if self.path is not None and _exists(self.path, self._connection):
            self._load()
        return self

    def _load(self) -> None:
        # Version first, content second — the other order can hand us a token
        # that belongs to bytes we never saw. See storage.version.
        self._version = _version_of(self.path, self._connection)
        try:
            data = _parse_document(_read_text(self.path, connection=self._connection))
        except yaml.YAMLError as exc:
            # PyYAML reports "<unicode string>", never the file it came from,
            # which is no help at all in a workspace of five members.
            raise ValueError(f"{self.path} is not valid YAML: {exc}") from exc
        if not isinstance(data, dict):
            # Valid YAML that isn't a mapping — a bare string or list. Reaching
            # .get() on it blames whichever key we happened to ask for first,
            # which sends the reader looking in the wrong place entirely. More
            # than a theoretical worry once the graph lives somewhere other
            # people can write to, like a shared warehouse table.
            raise ValueError(
                f"{self.path} does not hold a graph: expected a YAML mapping "
                f"with triples/nodes/ontology keys, found {type(data).__name__}"
            )
        for key, want in (("triples", list), ("nodes", dict), ("graphs", dict)):
            if key in data and data[key] is not None and not isinstance(data[key], want):
                # Left to itself this surfaces as .items() on a list or a
                # dict() on a string, several frames away from the file that
                # actually needs fixing.
                raise ValueError(
                    f"{self.path}: '{key}:' must be a {want.__name__}, "
                    f"found {type(data[key]).__name__}"
                )
        graphs = data.get("graphs")
        if isinstance(graphs, dict) and not data.get("triples"):
            self._load_workspace(graphs)
            return
        onto = data.get("ontology") or {}
        preds = onto.get("predicates", onto) if isinstance(onto, dict) else onto
        if not isinstance(preds, (dict, list, tuple)):
            raise ValueError(
                f"{self.path}: 'ontology:' must be a mapping of predicate to "
                f"description (or a list of predicates), found "
                f"{type(preds).__name__}"
            )
        if isinstance(preds, dict):
            for k, v in preds.items():
                self.ontology.setdefault(str(k), str(v or ""))
        elif isinstance(preds, (list, tuple)):
            for p in preds:
                self.ontology.setdefault(str(p), "")
        for name, props in (data.get("nodes") or {}).items():
            self.nodes_meta[str(name)] = dict(props or {})
        for item in data.get("triples") or []:
            self._triples.append(Triple.from_dict(item))
        self._rdf_cache = None
        self._index = None

    def _load_workspace(self, graphs: dict) -> None:
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
                f"{self.path}: 'graphs:' is empty — a workspace needs at least "
                "one member ({name: path})"
            )
        self.workspace = {str(k): str(v) for k, v in graphs.items()}
        self.read_only = True
        base_dir = None if _is_remote(self.path) else Path(self.path).parent
        for name, gpath in self.workspace.items():
            if not _is_remote(gpath) and base_dir is not None and not Path(gpath).is_absolute():
                gpath = str(base_dir / gpath)
            # Members inherit the connection: a union whose members live in a
            # warehouse has to reach it the same way this graph did, and a
            # host that cannot open its own connection cannot open one here
            # either.
            if not _exists(gpath, self._connection):
                # Not the same as an empty member: the workspace named this
                # file, so a typo here silently drops a whole graph out of
                # the union and every query just returns less.
                raise FileNotFoundError(
                    f"{self.path}: workspace member '{name}' points at "
                    f"{gpath}, which does not exist"
                )
            sub = TrikeDB(gpath, connection=self._connection)
            for k, v in sub.ontology.items():
                self.ontology.setdefault(k, v)
            for n, props in sub.nodes_meta.items():
                merged = self.nodes_meta.setdefault(n, {})
                for k, v in props.items():
                    merged.setdefault(k, v)
            for t in sub:
                self._triples.append(Triple(t.s, t.p, t.o, {**t.attrs, "graph": name}))
        self._index = None

    def _guard_writable(self) -> None:
        # Every method that can change the graph calls this first, which makes
        # it the one place a cache of the built RDF graph can be dropped
        # without hunting for mutation sites. Over-invalidating (save() also
        # passes through here) costs a rebuild; under-invalidating would
        # answer queries from a graph that no longer exists, so the
        # conservative side is the only safe one.
        self._rdf_cache = None
        if not self.read_only:
            return
        if self.workspace is not None:
            raise ValueError(
                "this is a read-only workspace union — write to one of its "
                f"member graphs instead: {self.workspace}"
            )
        # Naming the reason matters: "read-only" on its own reads like a
        # filesystem permission problem to go and fix, when in fact the caller
        # asked for this and the fix is to stop writing here.
        raise ValueError(
            f"{self.path} was opened read_only=True — mutations are refused. "
            "Open it without read_only to write, or write through whichever "
            "path owns this graph"
        )

    def save(self, path: Union[str, Path, None] = None):
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
        self._guard_writable()
        if path is None:
            target = self.path
        else:
            target = path if _is_remote(path) else Path(path)
        if target is None:
            raise ValueError("no path given and TrikeDB was created without one")
        doc: dict = {}
        if self.ontology:
            doc["ontology"] = {"predicates": dict(self.ontology)}
        if self.nodes_meta:
            doc["nodes"] = {k: dict(v) for k, v in self.nodes_meta.items()}
        doc["triples"] = [t.to_dict() for t in self._triples]
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
        if target == self.path:
            # Same file we read: refuse to overwrite someone else's save.
            _write_text(target, text, expect=self._version, connection=self._connection)
            self._version = _version_of(target, self._connection)
        else:  # save-as: nothing to compare against
            _write_text(target, text, connection=self._connection)
            self._version = _version_of(target, self._connection)
        self.path = target
        return target

    # -------------------------------------------------------------- writing

    def add(self, s: str, p: str, o: str, **attrs: Any) -> Triple:
        """Add (or upsert) a triple. Same (s, p, o) merges attributes.

        Absolute-URI predicates (http://...) are exempt from the ontology
        check — they are meta-level statements (OWL declarations, interop).
        """
        self._guard_writable()
        if (
            self.ontology
            and p not in self.ontology
            and not p.startswith(("http://", "https://"))
        ):
            raise OntologyError(
                f"predicate {p!r} is not in the ontology "
                f"(allowed: {sorted(self.ontology)})"
            )
        key = (_term(s, "s"), _term(p, "p"), _term(o, "o"))
        index = self._spo_index()
        existing = index.get(key)
        if existing is not None:
            existing.attrs.update(attrs)
            self._autosave()
            return existing
        triple = Triple(*key, dict(attrs))
        self._triples.append(triple)
        index.setdefault(key, triple)
        self._index_len = len(self._triples)
        self._autosave()
        return triple

    def remove(
        self,
        s: Optional[str] = None,
        p: Optional[str] = None,
        o: Optional[str] = None,
    ) -> int:
        """Remove all triples matching the pattern. Returns how many."""
        self._guard_writable()
        keep = [t for t in self._triples if not self._matches(t, s, p, o)]
        removed = len(self._triples) - len(keep)
        self._triples = keep
        self._index = None
        if removed:
            self._autosave()
        return removed

    def _spo_index(self) -> dict:
        """(s, p, o) -> Triple, built on demand and reused.

        ``add`` is an upsert, so it has to find an existing triple before
        appending. Doing that with a scan made *building* a graph O(n^2):
        100k triples took 289 seconds, and the cost of one add grew in
        proportion to the graph — 60us at 2k, 2.9ms at 100k. Loading was
        never affected (it appends without checking), so this only ever bit
        graphs being built or imported, which is exactly what an agent does.

        First entry wins, matching what the scan did when a hand-edited file
        contains the same triple twice. Rebuilt whenever the list length no
        longer matches what was indexed, which is how the index survives
        ``_triples`` being replaced or edited from outside.
        """
        if self._index is None or self._index_len != len(self._triples):
            index: dict = {}
            for triple in self._triples:
                index.setdefault(triple.spo(), triple)
            self._index = index
            self._index_len = len(self._triples)
        return self._index

    def _autosave(self) -> None:
        if self.autosave and self.path and not self._batch_depth:
            self.save()

    @contextmanager
    def batch(self):
        """Mutate freely, save once on the way out.

        `autosave=True` rewrites the whole file per mutation, which is what
        you want for a fact or two and quadratic for a bulk load — 28k
        triples one autosaved add at a time is an hour, and the same load in
        here is seconds. Nothing is written if the block raises: a half-
        finished import stays out of the file it would have to be undone from.
        """
        self._batch_depth += 1
        succeeded = False
        try:
            yield self
            succeeded = True
        finally:
            self._batch_depth -= 1
            if succeeded and not self._batch_depth and self.autosave and self.path:
                self.save()

    def set_node(self, name: str, *, replace: bool = False, **props: Any) -> dict:
        """Attach (or merge) free-form properties onto a node.

        Conventional keys the HTML export understands: `type` (color
        grouping + legend), `label` (display name), `level` (column in
        the flow layout). Everything else shows up in the detail panel.

        `type` is the one property not merged blindly. Two different things
        that share a name — a tool and a topic both called "Codex" — would
        otherwise take each other's place, and since the type is what the
        legend groups by, the only trace is a node count that no longer
        adds up. Pass `replace=True` to change a type on purpose.
        """
        self._guard_writable()
        merged = self.nodes_meta.setdefault(str(name), {})
        old = merged.get("type")
        if not replace and "type" in props and old is not None and props["type"] != old:
            raise ValueError(
                f"node {name!r} already has type {old!r}; refusing to replace "
                f"it with {props['type']!r} — pass replace (--replace on the "
                f"CLI) to change it deliberately"
            )
        merged.update(props)
        self._autosave()
        return merged

    def node(self, name: str) -> dict:
        """The properties attached to a node (empty dict if none)."""
        return dict(self.nodes_meta.get(str(name), {}))

    # -------------------------------------------------------------- reading

    @staticmethod
    def _matches(t: Triple, s, p, o, attrs: Optional[dict] = None) -> bool:
        if not (_term_match(s, t.s) and _term_match(p, t.p) and _term_match(o, t.o)):
            return False
        for k, v in (attrs or {}).items():
            if t.attrs.get(k) != v:
                return False
        return True

    def triples(
        self,
        s: Optional[str] = None,
        p: Optional[str] = None,
        o: Optional[str] = None,
        **attrs: Any,
    ) -> Iterator[Triple]:
        """Pattern-match triples. None = wildcard, '*' globs, attrs filter exactly."""
        for t in self._triples:
            if self._matches(t, s, p, o, attrs):
                yield t

    def subjects(self, p: Optional[str] = None, o: Optional[str] = None) -> list:
        return _unique(t.s for t in self.triples(p=p, o=o))

    def objects(self, s: Optional[str] = None, p: Optional[str] = None) -> list:
        return _unique(t.o for t in self.triples(s=s, p=p))

    def predicates(self) -> list:
        return _unique(t.p for t in self._triples)

    def nodes(self) -> list:
        return _unique(
            [x for t in self._triples for x in (t.s, t.o)] + list(self.nodes_meta)
        )

    # ---------------------------------------------------------------- query

    def query(self, patterns: Sequence) -> list:
        """Match multiple patterns with shared variables (SPARQL-style BGP).

        Each pattern is an (s, p, o) tuple or a string like '?src PROVIDES ?job'.
        Terms starting with '?' are variables; bindings are joined across
        patterns. Returns a list of {variable: value} dicts.

        >>> db.query(["?src PROVIDES ?job", "?job INGESTS_TO ?table"])
        [{'src': ..., 'job': ..., 'table': ...}, ...]
        """
        if not patterns:
            # The identity of a join over nothing is one empty row, which is
            # a true answer to a question nobody meant to ask.
            raise ValueError("query needs at least one pattern, got none")
        parsed = [self._parse_pattern(pat) for pat in patterns]
        bindings: list = [{}]
        for pat in parsed:
            if not bindings:
                break
            # candidates: filter by the pattern's constant terms once
            candidates = [
                t for t in self._triples
                if all(
                    term.startswith("?") or _term_match(term, value)
                    for term, value in zip(pat, t.spo())
                )
            ]
            # hash-join on variables this pattern shares with prior bindings
            # (all bindings at this point have the same keys)
            shared = [
                (term[1:], i) for i, term in enumerate(pat)
                if term.startswith("?") and term[1:] in bindings[0]
            ]
            if shared:
                index: dict = {}
                for t in candidates:
                    key = tuple(t.spo()[i] for _, i in shared)
                    index.setdefault(key, []).append(t)
                step = []
                for binding in bindings:
                    key = tuple(binding[name] for name, _ in shared)
                    for t in index.get(key, ()):
                        nb = _unify(pat, t, binding)
                        if nb is not None:
                            step.append(nb)
            else:
                step = []
                for binding in bindings:
                    for t in candidates:
                        nb = _unify(pat, t, binding)
                        if nb is not None:
                            step.append(nb)
            bindings = step
        unique, seen = [], set()
        for b in bindings:
            key = tuple(sorted(b.items()))
            if key not in seen:
                seen.add(key)
                unique.append(b)
        return unique

    @staticmethod
    def _parse_pattern(pattern) -> tuple:
        if isinstance(pattern, str):
            parts = shlex.split(pattern)
        else:
            parts = [str(x) for x in pattern]
        if len(parts) != 3:
            raise ValueError(
                f"pattern must have exactly 3 terms (s p o), got {pattern!r}"
            )
        return tuple(parts)

    # ------------------------------------------------------------- imports

    def import_file(self, path: Union[str, Path]) -> int:
        """Merge triples from a YAML graph, CSV/TSV, or Markdown document.

        CSV needs an s/p/o header (extra columns become attributes);
        Markdown contributes every table whose header has s/p/o columns.
        The ontology, if any, is enforced. Returns how many triples were
        added (upserts of existing triples don't count).
        """
        from . import importers

        path = Path(path)
        suffix = path.suffix.lower()
        if suffix in (".yaml", ".yml"):
            dicts = [t.to_dict() for t in TrikeDB(path)]
        elif suffix in (".csv", ".tsv"):
            dicts = importers.read_csv(path)
        elif suffix in (".md", ".markdown"):
            dicts = importers.read_markdown(path)
        else:
            raise ValueError(
                f"unsupported import format {path.suffix!r} (use .yaml/.csv/.tsv/.md)"
            )
        before = len(self._triples)
        for d in dicts:
            d = dict(d)
            self.add(d.pop("s"), d.pop("p"), d.pop("o"), **d)
        return len(self._triples) - before

    # -------------------------------------------------------------- sparql

    def to_rdflib(self, base: str = "urn:trikedb:", node_props: bool = True,
                  edge_attrs: bool = True):
        """Convert to an rdflib.Graph.

        Subjects and predicates become URIRefs under `base`. Objects become
        URIRefs too, unless they contain whitespace (e.g. change-event
        descriptions), in which case they become Literals. Node properties
        are included as literal-valued statements (so SPARQL can filter on
        them, e.g. `?x t:type "table"`) unless node_props=False.

        Edge attributes (note, prov, ...) are exported as standard RDF
        reification unless edge_attrs=False: each attributed triple gains a
        statement resource so the attributes are SPARQL-queryable::

            SELECT ?s ?o ?note WHERE {
              ?st rdf:subject ?s ; rdf:predicate t:AFFECTED_BY ;
                  rdf:object ?o ; t:note ?note }
        """
        from rdflib import RDF, Graph, Literal, URIRef

        def node(name: str):
            # absolute URIs (OWL/RDF vocabulary, external resources) pass through
            if name.startswith(("http://", "https://", "urn:")):
                return URIRef(name)
            return URIRef(_iri(name, base))

        g = Graph()
        g.bind("t", base)
        for s, p, o, is_literal in self._statements(base, node_props, edge_attrs):
            g.add((node(s), node(p), Literal(o) if is_literal else node(o)))
        return g

    def _statements(self, base: str, node_props: bool = True,
                    edge_attrs: bool = True):
        """Yield (subject, predicate, object, object_is_literal) — the RDF view.

        The single source of truth for what this graph *means* in RDF: which
        objects are URIs and which are literals, how edge attributes reify,
        which node properties surface. Every query engine builds from this,
        so two of them cannot drift into disagreeing about the same graph —
        which is the failure that would be hardest to notice, because both
        answers would look plausible.

        Subjects and predicates are names to be resolved against `base`;
        anything already absolute passes through untouched.
        """
        RDF_ = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        for i, t in enumerate(self._triples):
            o_is_literal = any(c.isspace() for c in t.o)
            yield t.s, t.p, t.o, o_is_literal
            if edge_attrs and t.attrs:
                st = f"{base}stmt{i}"
                yield st, RDF_ + "type", RDF_ + "Statement", False
                yield st, RDF_ + "subject", t.s, False
                yield st, RDF_ + "predicate", t.p, False
                yield st, RDF_ + "object", t.o, o_is_literal
                for key, value in t.attrs.items():
                    yield st, str(key), value, True
        if node_props:
            for name, props in self.nodes_meta.items():
                for key, value in props.items():
                    yield name, str(key), value, True

    _UPDATE_KEYWORDS = frozenset(
        {"INSERT", "DELETE", "CLEAR", "DROP", "CREATE", "LOAD", "MOVE", "COPY", "ADD", "WITH"}
    )

    def _oxigraph_store(self, base: str):
        """The same statements, in an oxigraph store.

        Oxigraph executes SPARQL roughly twenty times faster than rdflib on
        the same graph — 21ms against 427ms on 50k triples — because it is a
        Rust engine with real indexes rather than a Python dict of sets. The
        statements come from ``_statements``, so the two engines answer
        questions about the same graph and not about two similar ones.

        Literal typing has to match rdflib's, because a query like
        ``?x t:pii true`` matches a typed boolean and would silently return
        nothing against a plain string.
        """
        from pyoxigraph import DefaultGraph, Literal, NamedNode, Quad, Store

        xsd = "http://www.w3.org/2001/XMLSchema#"

        def node(name: str):
            if name.startswith(("http://", "https://", "urn:")):
                return NamedNode(name)
            return NamedNode(_iri(name, base))

        def literal(value):
            # bool before int: in Python bool *is* an int, and a boolean
            # typed as xsd:integer stops matching `true`.
            if isinstance(value, bool):
                return Literal("true" if value else "false",
                               datatype=NamedNode(xsd + "boolean"))
            if isinstance(value, int):
                return Literal(str(value), datatype=NamedNode(xsd + "integer"))
            if isinstance(value, float):
                return Literal(repr(value), datatype=NamedNode(xsd + "double"))
            return Literal(str(value))

        store = Store()
        default = DefaultGraph()
        store.extend([
            Quad(node(s), node(p), literal(o) if lit else node(o), default)
            for s, p, o, lit in self._statements(base)
        ])
        return store

    def _query_graph(self, base: str, engine: str = "rdflib"):
        """The built RDF graph for read queries, reused between them.

        Building it was two thirds of what a query cost — 769ms of 1200ms on
        50k triples — because every call started from scratch. Reads dominate
        in the shape that matters (a served graph answering agents), so the
        second query onward now pays only for the query itself.

        Any attempted mutation drops this; see ``_guard_writable``. Updates
        deliberately do not come here: ``update()`` needs a graph without node
        properties or reification so it can diff the result back, and it
        builds its own.
        """
        key = (base, engine)
        if self._rdf_cache is not None and self._rdf_cache[0] == key:
            return self._rdf_cache[1]
        graph = (self._oxigraph_store(base) if engine == "oxigraph"
                 else self.to_rdflib(base))
        self._rdf_cache = (key, graph)
        return graph

    def sparql(self, query: str, base: str = "urn:trikedb:"):
        """Run real SPARQL 1.1 (via rdflib) against the graph — reads and writes.

        The prefix `t:` is bound to `base`, so predicates are written
        `t:PROVIDES`. SELECT returns a list of {var: value} dicts with URIs
        shortened back to plain names; ASK returns a bool. Update forms
        (INSERT DATA, DELETE WHERE, ...) mutate the store and return the
        change in triple count.

        >>> db.sparql("SELECT ?v ?t WHERE { ?v t:PROVIDES ?j . ?j t:INGESTS_TO ?t }")
        >>> db.sparql("INSERT DATA { t:figly t:PROVIDES t:figly-export-job }")
        """
        first = next((w.upper() for w in query.split() if not w.startswith("#")), "")
        if first in self._UPDATE_KEYWORDS:
            return self.update(query, base=base)

        prefixed = (
            f"PREFIX t: <{base}>\n"
            "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n" + query
        )
        if self.sparql_engine == "oxigraph":
            rows = self._query_oxigraph(prefixed, base)
            if rows is not NotImplemented:
                return rows
            # a CONSTRUCT or DESCRIBE: rdflib owns those, unchanged

        result = self._query_graph(base).query(prefixed)
        if result.type == "ASK":
            return result.askAnswer
        if result.type in ("CONSTRUCT", "DESCRIBE"):
            # These answer with triples, not bindings, so `result.vars` is
            # None and the binding loop below raised TypeError on it. Give
            # them the same shape a triple has everywhere else in the API.
            return [{"s": _shorten(s, base), "p": _shorten(p, base),
                     "o": _shorten(o, base)} for s, p, o in result.graph]

        rows = []
        for binding in result:
            row = {}
            for var, value in zip(result.vars, binding):
                if value is not None:
                    row[str(var)] = _shorten(value, base)
            rows.append(row)
        return rows

    def _query_oxigraph(self, prefixed: str, base: str):
        """Answer a SELECT or ASK through oxigraph, in the same shape.

        Returns ``NotImplemented`` for query forms this path does not cover
        (CONSTRUCT, DESCRIBE) so the caller can fall back rather than this
        having to parse the query to find out which form it is.
        """
        result = self._query_graph(base, "oxigraph").query(prefixed)
        if hasattr(result, "variables"):                   # SELECT
            pass
        elif hasattr(result, "__bool__") and not hasattr(result, "__iter__"):
            # ASK. pyoxigraph answers with QueryBoolean, not bool, so an
            # isinstance(result, bool) test silently missed every ASK and sent
            # it to rdflib — which also evicted the oxigraph store from the
            # one-entry graph cache, so the next read rebuilt it. An ASK cost
            # ~100ms instead of ~0.1ms and the engine reported for it was a
            # lie.
            return bool(result)
        else:                                              # CONSTRUCT/DESCRIBE
            return NotImplemented

        # oxigraph terms stringify to N-Triples (`<urn:trikedb:a>`), so the
        # raw value has to come off the term before _shorten sees it.
        names = [str(v)[1:] if str(v).startswith("?") else str(v)
                 for v in result.variables]
        rows = []
        for solution in result:
            row = {}
            for name, value in zip(names, solution):
                if value is not None:
                    row[name] = _shorten(value.value, base)
            rows.append(row)
        return rows

    def update(self, query: str, base: str = "urn:trikedb:") -> int:
        """Apply a SPARQL 1.1 Update and sync the result back to the store.

        Attributes of surviving triples are preserved; triples inserted via
        SPARQL start with no attributes. The ontology (if any) is enforced
        on inserted predicates. Returns the net change in triple count.
        """
        self._guard_writable()
        # no node_props / edge_attrs: the sync-back below must see pure facts
        g = self.to_rdflib(base, node_props=False, edge_attrs=False)
        g.update(f"PREFIX t: <{base}>\n" + query)

        new_spos = {tuple(_shorten(x, base) for x in triple) for triple in g}
        before = len(self._triples)
        old_by_spo = {t.spo(): t for t in self._triples}
        kept = [t for t in self._triples if t.spo() in new_spos]
        existing = {t.spo() for t in kept}
        for s, p, o in sorted(new_spos - existing):
            if self.ontology and p not in self.ontology:
                raise OntologyError(
                    f"update inserts predicate {p!r} not in the ontology "
                    f"(allowed: {sorted(self.ontology)})"
                )
            old = old_by_spo.get((s, p, o))
            kept.append(Triple(s, p, o, old.attrs if old else {}))
        self._triples = kept
        self._index = None
        if len(self._triples) != before or new_spos - existing:
            self._autosave()
        return len(self._triples) - before

    # ---------------------------------------------------- validation / owl

    def declare(self, predicate: str, characteristic: str) -> Triple:
        """Give a predicate OWL semantics for infer().

        characteristic: 'transitive', 'symmetric', 'functional', or
        'inverse_of:<OTHER_PREDICATE>'. Stored as an ordinary triple in
        the YAML (subject = the predicate itself), so it is reviewable.
        """
        from . import semantics

        return semantics.declare(self, predicate, characteristic)

    def search(self, query: str, k: int = 10, model: Optional[str] = None) -> list:
        """Semantic search: rank triples/nodes by meaning, not spelling
        (requires the [semantic] extra). "認証まわりの注意点" finds keypair
        and MFA facts without sharing a keyword. Returns scored dicts.
        """
        from . import semantic

        kwargs = {"model": model} if model else {}
        return semantic.search(self, query, k=k, **kwargs)

    def find(self, question: str, where=None, k: int = 10,
             model: Optional[str] = None) -> list:
        """Hybrid retrieval: semantic recall, then a hard structured filter.

        Two stages, one call — the pattern an agent wants:
          1. recall — `search()` casts a wide semantic net (meaning, not
             spelling; cross-lingual) to gather candidate nodes;
          2. precision — keep only the ones that satisfy `where`, an exact
             filter with no fuzz.

        where: None (keep every recalled node), a dict of required node
        properties (`{"type": "table", "pii": True}` — all must match), or
        a callable `(name, props) -> bool` for arbitrary logic.

        Returns candidates in recall-rank order, each as a ready-to-use
        payload: {"node": name, "props": {...}, "facts": [[p, o], ...]}.
        A property holding a whole document comes back as a preview — this
        answers a question, and burying the answer under 540k characters of
        source does not. `node(name)` returns the untouched value.
        Requires the [semantic] extra (for the recall stage).
        """
        from .semantic import preview
        candidates = []
        for hit in self.search(question, k=k, model=model):   # stage 1: recall
            candidates += (
                [hit["node"]] if hit.get("kind") == "node"
                else [hit.get("s"), hit.get("o")]
            )
        out, seen = [], set()
        for name in candidates:                               # stage 2: precision
            if not name or name in seen:
                continue
            seen.add(name)
            props = self.node(name)
            if callable(where):
                keep = bool(where(name, props))
            elif where:
                keep = all(props.get(key) == val for key, val in where.items())
            else:
                keep = True
            if keep:
                facts = [[t.p, t.o] for t in self.triples(s=name)]
                out.append({"node": name, "props": preview(props), "facts": facts})
        return out

    def infer(self, apply: bool = False, base: str = "urn:trikedb:") -> list:
        """Materialize OWL-RL inferences over the graph (requires [owl] extra).

        Uses declared characteristics (see declare()) to derive new facts.
        Returns the new (s, p, o) tuples; with apply=True they are added
        to the store with an `inferred: true` attribute, so the YAML diff
        shows exactly what the reasoner concluded.
        """
        from . import semantics

        return semantics.infer(self, apply=apply, base=base)

    def validate(self, shapes, base: str = "urn:trikedb:"):
        """Validate the graph against SHACL shapes (requires [shacl] extra).

        shapes: a Turtle string, or a path/URL to a .ttl file, using the
        urn:trikedb: namespace. Returns (conforms: bool, report: str).
        """
        from . import semantics

        return semantics.validate(self, shapes, base=base)

    # -------------------------------------------------------------- exports

    def content_hash(self) -> str:
        """Stable fingerprint of the graph content (triples + nodes + ontology).

        Embedded into generated HTML so `trikedb check` can detect a stale
        export without knowing the generation parameters.
        """
        import hashlib
        import json as _json

        doc = {
            "ontology": self.ontology,
            "nodes": self.nodes_meta,
            "triples": sorted(
                (t.to_dict() for t in self._triples),
                key=lambda d: _json.dumps(d, sort_keys=True, ensure_ascii=False),
            ),
        }
        return hashlib.sha256(
            _json.dumps(doc, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16]

    def audit(self) -> list:
        """Health findings for a growing graph; see trikedb.audit.audit()."""
        from . import audit

        return audit.audit(self)

    def to_jsonld(self, base: str = "urn:trikedb:") -> dict:
        """Best-effort JSON-LD export for interop with real RDF tooling."""
        context = {p: {"@id": base + p, "@type": "@id"} for p in self.predicates()}
        nodes: dict = {}
        for t in self._triples:
            node = nodes.setdefault(t.s, {"@id": t.s})
            node.setdefault(t.p, []).append(t.o)
        return {"@context": context, "@graph": list(nodes.values())}

    def to_networkx(self, multigraph: bool = True):
        """Project to a networkx graph — the property-graph view (requires
        the [networkx] extra: pip install 'trikedb[networkx]').

        One YAML file, two projections: to_rdflib() gives the RDF/SPARQL view,
        this gives the labeled-property-graph view for graph algorithms
        (shortest path, centrality, communities) via networkx. Nodes carry
        their properties (type, url, ...); each edge carries the predicate as
        `label` plus every edge attribute (schedule, prov, deprecated, ...).

        multigraph=True (default) returns a MultiDiGraph, preserving parallel
        edges with different predicates between the same pair; False collapses
        to a DiGraph (last edge between a pair wins).
        """
        try:
            import networkx as nx
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "networkx projection requires networkx - pip install 'trikedb[networkx]'"
            ) from exc

        g = nx.MultiDiGraph() if multigraph else nx.DiGraph()
        for name in self.nodes():           # nodes first, so property-only nodes survive
            g.add_node(name, **self.node(name))
        for t in self._triples:
            if multigraph:
                g.add_edge(t.s, t.o, key=t.p, label=t.p, **t.attrs)
            else:
                g.add_edge(t.s, t.o, label=t.p, **t.attrs)
        return g

    def to_html(
        self,
        path: Union[str, Path, None] = None,
        title: str = "trikedb knowledge graph",
        event_predicates=None,
        layout: str = "auto",
    ) -> str:
        from .html import to_html

        return to_html(self, path=path, title=title,
                       event_predicates=event_predicates, layout=layout)

    # ------------------------------------------------------------- protocol

    def __len__(self) -> int:
        return len(self._triples)

    def __iter__(self) -> Iterator[Triple]:
        return iter(self._triples)

    def __contains__(self, spo) -> bool:
        return any(t.spo() == tuple(spo) for t in self._triples)

    def __repr__(self) -> str:
        where = str(self.path) if self.path else "in-memory"
        return f"<TrikeDB {where}: {len(self)} triples, {len(self.predicates())} predicates>"


#: What actually has to be escaped to sit inside an IRI: the delimiters
#: RFC 3987 excludes, the characters that would end the term early in
#: N-Triples or start a comment in Turtle, and `%` itself so the escaping
#: round-trips. Everything else stays as it was written — most importantly
#: every non-ASCII letter, which an IRI is explicitly allowed to carry.
#:
#: Percent-encoding all of it (`quote(name, safe="")`) made a Japanese node
#: `urn:trikedb:%E6%8B%85%E5%BD%93A`, so `SELECT ?s WHERE { ?s t:OWNED_BY
#: t:担当A }` matched nothing and reported it as zero rows rather than as an
#: error — the graph looked empty instead of mis-encoded. Names with spaces
#: still need `<urn:trikedb:Baltic%20states>`; a space cannot be in an IRI.
_IRI_ESCAPES = {chr(c): f"%{c:02X}" for c in list(range(0x21)) + [0x7F]}
_IRI_ESCAPES.update({c: f"%{ord(c):02X}" for c in '"<>{}|\\^`%#?'})


def _iri(name: str, base: str) -> str:
    """`name` as an IRI under `base`, escaped only where it has to be."""
    return base + "".join(_IRI_ESCAPES.get(c, c) for c in name)


def _shorten(value, base: str) -> str:
    """Map a URI under `base` back to its plain name; literals pass through."""
    from urllib.parse import unquote

    text = str(value)
    if text.startswith(base):
        return unquote(text[len(base):])
    return text


def _unify(pattern: tuple, t: Triple, binding: dict) -> Optional[dict]:
    """Extend binding so pattern matches triple, or return None."""
    nb = dict(binding)
    for term, value in zip(pattern, t.spo()):
        if term.startswith("?"):
            var = term[1:]
            if var in nb:
                if nb[var] != value:
                    return None
            else:
                nb[var] = value
        elif not _term_match(term, value):
            return None
    return nb


def _unique(items) -> list:
    seen, out = set(), []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out
