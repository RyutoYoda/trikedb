"""Core triple store: a knowledge graph persisted as a single YAML file."""

from __future__ import annotations

import json
import shlex
from copy import deepcopy
from threading import RLock
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence, Union

import yaml

# What a triple is, and the helpers that answer questions about one, live in
# model.py — the bottom of the package, which imports nothing from trikedb.
# They are re-exported here because `from trikedb.db import Triple` (and
# `_shorten`, and `_oxigraph_available`) is what callers have always written.
from .model import (  # noqa: F401
    RULE_KEYS,
    TIME_ATTRS,
    OntologyError,
    Triple,
    _YamlDumper,
    _YamlLoader,
    _iri,
    _iri_node,
    _is_pattern,
    _now,
    _oxigraph_available,
    _parse_document,
    _plain,
    _shorten,
    _term,
    _term_match,
    _time_key,
    _unify,
    _unique,
    _validate_rdf_terms,
)

__all__ = ["Triple", "TrikeDB", "OntologyError"]

# What the store is made of, and what it is allowed to know about.
#
# `model` is the data; `rules`, `rdf`, `reasoning`, `persistence` and
# `audit` are what the store means, and they take the store as their first
# argument rather than importing it back. `html`, `embeddings` and
# `importers` are the other direction — a page, a model, a file format —
# and are imported inside the three methods that use them, so the core
# never depends on its own presentation or on an adapter it may not need.
from . import audit as _audit
from . import persistence, rdf, reasoning, rules





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
        self._lock = RLock()  # shared by server adapters, never serialized
        #: local paths become Path; remote URLs (s3://, https://, ...) stay str
        self.path: Union[Path, str, None] = persistence.locate(path)
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
        #: predicate -> {"domain": (type, ...), "range": (type, ...)} for the
        #: predicates that declare one. Kept beside self.ontology rather than
        #: inside it so a description stays a plain string for everything
        #: that reads one, and so a graph that declares nothing pays nothing.
        self.predicate_rules: dict = {}
        self._triples: list = []
        #: open batch() blocks; while any is open, autosave holds its write
        self._batch_depth = 0
        #: One list per open batch, holding (triple, attrs-before) for
        #: the one mutation that happens in place — see add()'s upsert.
        self._batch_undo: list = []
        #: storage token the in-memory graph was built from; see storage.version
        self._version = None
        #: (base, engine) -> a built query graph. sparql() used to rebuild one
        #: per call, which was two thirds of its cost; see _query_graph.
        self._rdf_cache: Optional[tuple] = None
        #: (s, p, o) -> Triple, so add() does not scan; see _spo_index
        self._index: Optional[dict] = None
        self._index_len = -1
        #: predicate -> its triples, and (predicate, node) -> the triples
        #: with that node at either end, so a declared condition does not
        #: scan; see _p_index
        self._pidx: Optional[dict] = None
        self._eidx: Optional[dict] = None
        self._pidx_len = -1
        #: conditions a half-built graph cannot answer yet; see _settle
        self._pending: list = []
        #: who the current write is by, when the transport knows. Bound per
        #: request by the MCP server under this instance's lock — a served
        #: graph is one instance shared by every caller, so the actor cannot
        #: live on the constructor. None everywhere else, which is what keeps
        #: library use, stdio and a static token behaving exactly as before.
        #: See rules.signed_by.
        self._actor: Optional[str] = None
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
                for key, value in ontology.items():
                    self._declare_predicate(str(key), value)
            else:
                self.ontology = {str(p): "" for p in ontology}
        persistence.load_if_present(self)

    # ------------------------------------------------------------------- io
    #
    # Reading and writing the document — and reading a workspace as one —
    # live in persistence.py. `reload` and `save` are the public pair.

    def reload(self) -> "TrikeDB":
        """Throw away the in-memory graph and read it again from storage.
        See persistence.reload."""
        return persistence.reload(self)

    def _guard_writable(self) -> None:
        return persistence.guard_writable(self)

    def save(self, path: Union[str, Path, None] = None):
        """Write the graph back out. See persistence.save."""
        return persistence.save(self, path)

    # -------------------------------------------------------------- writing

    # ---------------------------------------------- declarations and rules
    #
    # What these mean lives in rules.py, as free functions taking the store.
    # What is left here is what something outside db.py actually calls —
    # `audit` asks `db._unmet`, the tests ask for the rest by name. A
    # forward that nobody follows is not an interface, so it is gone.

    def _declare_predicate(self, name: str, value: Any, *,
                           keep_existing: bool = False) -> None:
        return rules.declare_predicate(self, name, value,
                                       keep_existing=keep_existing)

    def declare_link(self, predicate: str, *, domain=None, range=None,
                     requires=None, by=None,
                     description: Optional[str] = None) -> dict:
        """Declare what a predicate connects and how it may run, and have
        it enforced. See rules.declare_link."""
        return rules.declare_link(self, predicate, domain=domain, range=range,
                                  requires=requires, by=by,
                                  description=description)

    def _check_link(self, s: str, p: str, o: str) -> None:
        return rules.check_link(self, s, p, o)

    def _unmet(self, t: Triple, rule: dict) -> list:
        return rules.unmet(self, t, rule)

    def _check_action(self, t: Triple) -> None:
        return rules.check_action(self, t)

    def _settle(self) -> None:
        return rules.settle(self)

    def _check_node_type(self, name: str, new_type: str) -> None:
        return rules.check_node_type(self, name, new_type)

    def _check_predicate(self, p: str) -> None:
        return rules.check_predicate(self, p)

    def add(self, s: str, p: str, o: str, *, rdf_terms=None, **attrs: Any) -> Triple:
        """Add (or upsert) a triple. Same (s, p, o) merges attributes.

        Absolute-URI predicates (http://...) are exempt from the ontology
        check — they are meta-level statements (OWL declarations, interop).
        """
        self._guard_writable()
        s, p = _term(s, "s"), _term(p, "p")
        _validate_rdf_terms(rdf_terms or {})
        self._check_predicate(p)
        attrs = rules.signed_by(self, p, attrs)
        triple = Triple.from_dict({"s": s, "p": p, "o": o, **attrs,
                                   "rdf_terms": rdf_terms or {}})
        if triple.rdf_terms:
            actual_p = _shorten(triple.as_rdf()[1], "urn:trikedb:")
            if self.ontology and actual_p not in self.ontology and not actual_p.startswith(("http://", "https://")):
                raise OntologyError(f"predicate {actual_p!r} is not in the ontology")
        self._check_link(triple.s, triple.p, triple.o)
        self._check_action(triple)
        key = triple.identity()
        index = self._spo_index()
        existing = index.get(key)
        if existing is not None:
            # The only edit to a triple already in the store, so it is the
            # only thing a shallow snapshot cannot undo on its own. Every
            # open batch gets the pre-image, because each rolls back to
            # the state it began in, not to the innermost one.
            for undo in self._batch_undo:
                undo.append((existing, dict(existing.attrs)))
            existing.attrs.update(deepcopy(attrs))
            self._autosave()
            return deepcopy(existing)
        self._triples.append(triple)
        self._index_append(triple)
        self._autosave()
        return deepcopy(triple)

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
        self._index = self._pidx = self._eidx = None
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
                index.setdefault(triple.identity(), triple)
            self._index = index
            self._index_len = len(self._triples)
        return self._index

    def _index_append(self, t: Triple) -> None:
        """Keep the indexes current rather than dropping them.

        They rebuild when the triple count stops matching what was indexed,
        which is the right answer for a list edited from outside and the
        wrong one for the common case: appending a triple makes the count
        differ, so a graph built one write at a time rebuilt every index on
        every write, and a declared condition cost the size of the graph
        after all — indexed, and still linear. Extending them instead costs
        nothing and keeps the count in step. Call after the append.
        """
        if self._index is not None:
            self._index.setdefault(t.identity(), t)
            self._index_len = len(self._triples)
        if self._pidx is not None:
            self._pidx.setdefault(t.p, []).append(t)
            self._eidx.setdefault((t.p, t.s), []).append(t)
            if t.o != t.s:
                self._eidx.setdefault((t.p, t.o), []).append(t)
            self._pidx_len = len(self._triples)

    def _p_index(self) -> tuple:
        """predicate -> its triples, and (predicate, node) -> the triples
        with that node at either end. Built together, on demand, reused.

        A declared condition asks the same question of every write — has
        this happened yet — and answering it by walking the whole graph
        makes the condition cost O(n) per triple, once per step of it. At
        16k triples that was eight minutes to build a graph, which is a
        guarantee nobody would leave switched on.

        By predicate alone is not enough: ``PLACED_BY`` narrows a shipping
        graph to a third of itself and no further, so a step that already
        knows one of its ends still walked every order in the book. Keyed
        by the end as well it goes straight to the handful that touch this
        order, and the check stops growing with the graph — which is what
        makes a condition spanning several steps affordable to enforce on
        every write rather than only in audit().

        Either end, not the subject, for the same reason _happened reads
        both: an event promoted to an object sits on the far side of its
        own edge. Same refresh rule as _spo_index, and the same explicit
        clearing when triples are removed rather than appended.
        """
        if self._pidx is None or self._pidx_len != len(self._triples):
            by_p: dict = {}
            by_end: dict = {}
            for t in self._triples:
                by_p.setdefault(t.p, []).append(t)
                by_end.setdefault((t.p, t.s), []).append(t)
                if t.o != t.s:
                    by_end.setdefault((t.p, t.o), []).append(t)
            self._pidx, self._eidx = by_p, by_end
            self._pidx_len = len(self._triples)
        return self._pidx, self._eidx

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
        with self._lock:
            # Structural copies, not deepcopy. What rollback has to undo is
            # *which* objects the store holds, not what is inside them:
            # triples are appended and dropped, never edited, except for
            # add()'s attribute merge, which records its own pre-image
            # below. A node's properties are replaced rather than edited
            # for the same reason, so one level down is the whole store.
            #
            # deepcopy walked the entire graph on the way into every batch,
            # and act() opens one per action — an action on a 200k-triple
            # graph spent 1.5 seconds copying the 199,999 triples it was
            # not going to touch. Copying pointers instead is the same
            # guarantee at a thousandth of the cost.
            snapshot = (list(self._triples), dict(self.nodes_meta),
                        dict(self.ontology), dict(self.predicate_rules))
            undo: list = []
            self._batch_undo.append(undo)
            self._batch_depth += 1
            try:
                yield self
                if self._batch_depth == 1:
                    self._settle()
                    if self.autosave and self.path:
                        self.save()
            except BaseException:
                self._pending = []
                for triple, before in reversed(undo):
                    triple.attrs = before
                (self._triples, self.nodes_meta, self.ontology,
                 self.predicate_rules) = snapshot
                self._index = self._pidx = self._eidx = self._rdf_cache = None
                raise
            finally:
                self._batch_depth -= 1
                self._batch_undo.pop()

    def set_node(self, name: str, /, *, replace: bool = False, **props: Any) -> dict:
        """Attach (or merge) free-form properties onto a node.

        Conventional keys the HTML export understands: `type` (color
        grouping + legend), `label` / `name` / `title` / `summary` (what
        the node is called, in that order of preference), `level` (column
        in the flow layout). Everything else shows up in the detail panel.

        The node is positional-only, because `name` is one of the keys a
        caller most wants to set and a parameter of the same name would
        eat it: `set_node("SVC-1", name="checkout-api")` has to mean the
        property, not a second spelling of the node.

        `type` is the one property not merged blindly. Two different things
        that share a name — a tool and a topic both called "Codex" — would
        otherwise take each other's place, and since the type is what the
        legend groups by, the only trace is a node count that no longer
        adds up. Pass `replace=True` to change a type on purpose.
        """
        self._guard_writable()
        rules.check_identity_prop(self, str(name), props)
        # A node's properties are replaced, never edited in place. That is
        # what lets batch() snapshot the store by copying pointers instead
        # of walking it — see the note there.
        merged = dict(self.nodes_meta.get(str(name)) or {})
        old = merged.get("type")
        if not replace and "type" in props and old is not None and props["type"] != old:
            raise ValueError(
                f"node {name!r} already has type {old!r}; refusing to replace "
                f"it with {props['type']!r} — pass replace (--replace on the "
                f"CLI) to change it deliberately"
            )
        if self.predicate_rules and "type" in props and props["type"] != old:
            # Before mutating: a refused type must leave the node as it was.
            self._check_node_type(str(name), str(props["type"]))
        merged.update(deepcopy(props))
        self.nodes_meta[str(name)] = merged
        self._autosave()
        return deepcopy(merged)

    def node(self, name: str) -> dict:
        """The properties attached to a node (empty dict if none)."""
        return deepcopy(self.nodes_meta.get(str(name), {}))

    # -------------------------------------------------------------- actions

    def act(self, s: str, p: str, o: str, *, state: Optional[str] = None,
            by: Optional[str] = None, at: Any = None, **attrs: Any) -> Triple:
        """Run an action: change the node, and leave the record of it.

        An action *is* an event — the same triple the graph already stores,
        with the time on it. What act() adds is that the three things
        happen together and cannot come apart:

        * it stamps the time (``at=`` overrides, otherwise now), so an
          action always says when;
        * it appends, never merges — running the same action twice is two
          things happening, and the first must survive the second;
        * when the action says what state it left the node in, that state
          is written onto the node.

        So afterwards the node *is* different, not merely described by a
        line further down the file: ``db.node(s)["state"]`` is where it
        ended up and ``db.history(s)`` is how it got there.
        """
        self._guard_writable()
        s, p = _term(s, "s"), _term(p, "p")
        self._check_predicate(p)
        payload: dict = {}
        if at is not None:
            payload["at"] = _plain(at)
        elif not any(k in attrs for k in TIME_ATTRS):
            payload["at"] = _now()   # the caller spelled no time; an action has one
        if by is not None:
            payload["by"] = by
        if state is not None:
            payload["state"] = state
        payload.update(attrs)
        payload = rules.signed_by(self, p, payload, stamp=True)
        triple = Triple.from_dict({"s": s, "p": p, "o": o, **payload})
        self._check_link(triple.s, triple.p, triple.o)
        self._check_action(triple)
        with self.batch():
            # One write, and nothing half-applied: an event whose state
            # never reached the node would be a log of something that
            # did not happen.
            self._triples.append(triple)
            self._index_append(triple)
            if state is not None:
                self.nodes_meta[s] = {**(self.nodes_meta.get(s) or {}),
                                      "state": str(state)}
        return deepcopy(triple)

    def _own_events(self, name: str, p: Optional[str] = None) -> list:
        """Dated triples this node is the subject of — what it did or became.

        The state a node wears comes from here and only here. An event
        pointing *at* a node says something happened to it, not that it
        took the event's state: a price change that leaves the change
        record 'applied' does not leave the approver applied.
        """
        return [(i, t) for i, t in enumerate(self._triples)
                if t.s == name and t.when() and (p is None or t.p == p)]

    def history(self, name: str, p: Optional[str] = None,
                *, incoming: bool = True) -> list:
        """Everything that happened to this node, newest first.

        Both directions, because an event is not always written from the
        node's side. Once an event is big enough to carry its own
        properties it becomes an object in its own right — a price change
        with a before and an after, a shipment with a carrier and a wave —
        and then the product is the *object* of ``CHANGED``, not the
        subject. Folding the incoming side in is what keeps that promotion
        from cutting the product off from its own history.

        ``incoming=False`` narrows it back to what this node is the
        subject of, which is the view :meth:`state` reads.

        Promotion moves the properties the event grew — a before, an
        after, a reason — onto the node. It does not move ``at:`` and
        ``state:``, which are read off the triple and belong there in
        both spellings; a graph that puts them on the event node instead
        loads without complaint and then returns nothing here.
        ``audit()`` reports that as ``event-written-on-node``. The YAML
        for the promoted form is in the README, under "When an event
        grows properties of its own, promote it to an object".
        """
        name = str(name)
        rows = self._own_events(name, p)
        if incoming:
            rows += [(i, t) for i, t in enumerate(self._triples)
                     if t.o == name and t.s != name and t.when()
                     and (p is None or t.p == p)]
        # Newest first, and a tie on the day goes to whichever was appended
        # later: written later, happened later.
        rows.sort(key=lambda row: (_time_key(row[1].when()), row[0]), reverse=True)
        return [deepcopy(t) for _, t in rows]

    def state(self, name: str) -> Optional[str]:
        """What state this node is in now, or None if nothing ever said.

        The property act() wrote, if there is one; otherwise the state
        carried by the latest event this node is the *subject* of, so a
        graph hand-written in YAML answers the question the same way one
        built through act() does.

        Subject-only, and on the triple: an event pointing at a node did
        not leave the node in the event's state, and a promoted event
        keeps its ``at:`` and ``state:`` on the triple while the node
        holds the properties it was promoted for. Writing those two keys
        onto the node instead reads as nothing here; ``audit()`` reports
        it as ``event-written-on-node``. See "When an event grows
        properties of its own, promote it to an object" in the README.
        """
        stored = (self.nodes_meta.get(str(name)) or {}).get("state")
        if stored is not None:
            return str(stored)
        for _, event in sorted(self._own_events(str(name)),
                               key=lambda row: (_time_key(row[1].when()), row[0]),
                               reverse=True):
            for key in ("state", "status"):
                if key in event.attrs:
                    return str(event.attrs[key])
        return None

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
                yield deepcopy(t)

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
        with self.batch():
            for d in dicts:
                d = dict(d)
                self.add(d.pop("s"), d.pop("p"), d.pop("o"), **d)
        return len(self._triples) - before

    # -------------------------------------------------------------- sparql

    # ------------------------------------------------------------------ rdf
    #
    # The projection into RDF, and the two engines that read it, live in
    # rdf.py. Only the three public names keep methods here.

    def to_rdflib(self, base: str = "urn:trikedb:", node_props: bool = True,
                  edge_attrs: bool = True):
        """This graph as an rdflib Graph. See rdf.to_rdflib."""
        return rdf.to_rdflib(self, base, node_props, edge_attrs)

    def _statements(self, base: str, node_props: bool = True,
                    edge_attrs: bool = True):
        return rdf.statements(self, base, node_props, edge_attrs)

    def _oxigraph_store(self, base: str):
        return rdf.oxigraph_store(self, base)

    def _query_graph(self, base: str, engine: str = "rdflib"):
        return rdf.query_graph(self, base, engine)

    def sparql(self, query: str, base: str = "urn:trikedb:"):
        """Run a SPARQL 1.1 query. See rdf.sparql."""
        return rdf.sparql(self, query, base)

    def _query_oxigraph(self, prefixed: str, base: str):
        return rdf.query_oxigraph(self, prefixed, base)

    def update(self, query: str, base: str = "urn:trikedb:") -> int:
        """Run a SPARQL 1.1 update against the default graph. See rdf.update."""
        return rdf.update(self, query, base)

    # ---------------------------------------------------- validation / owl

    def declare(self, predicate: str, characteristic: str) -> Triple:
        """Give a predicate OWL semantics for infer().

        characteristic: 'transitive', 'symmetric', 'functional', or
        'inverse_of:<OTHER_PREDICATE>'. Stored as an ordinary triple in
        the YAML (subject = the predicate itself), so it is reviewable.
        """
        return reasoning.declare(self, predicate, characteristic)

    def search(self, query: str, k: int = 10, model: Optional[str] = None) -> list:
        """Semantic search: rank triples/nodes by meaning, not spelling
        (requires the [semantic] extra). "認証まわりの注意点" finds keypair
        and MFA facts without sharing a keyword. Returns scored dicts.
        """
        from . import embeddings

        kwargs = {"model": model} if model else {}
        return embeddings.search(self, query, k=k, **kwargs)

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
        from . import embeddings

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
                out.append({"node": name, "props": embeddings.preview(props), "facts": facts})
        return out

    def infer(self, apply: bool = False, base: str = "urn:trikedb:") -> list:
        """Materialize OWL-RL inferences over the graph (requires [owl] extra).

        Uses declared characteristics (see declare()) to derive new facts.
        Returns the new (s, p, o) tuples; with apply=True they are added
        to the store with an `inferred: true` attribute, so the YAML diff
        shows exactly what the reasoner concluded.
        """
        return reasoning.infer(self, apply=apply, base=base)

    def validate(self, shapes, base: str = "urn:trikedb:"):
        """Validate the graph against SHACL shapes (requires [shacl] extra).

        shapes: a Turtle string, or a path/URL to a .ttl file, using the
        urn:trikedb: namespace. Returns (conforms: bool, report: str).
        """
        return reasoning.validate(self, shapes, base=base)

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
        if self.predicate_rules:
            # Added only when there is one, so that every graph written
            # before declarations existed keeps the fingerprint its
            # exported HTML was stamped with. See check().
            doc["links"] = {p: {k: list(v) for k, v in rule.items()}
                            for p, rule in self.predicate_rules.items()}
        return hashlib.sha256(
            _json.dumps(doc, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16]

    def audit(self) -> list:
        """Health findings for a growing graph; see trikedb.audit.audit()."""
        return _audit.audit(self)

    def to_jsonld(self, base: str = "urn:trikedb:") -> dict:
        """Best-effort JSON-LD export for interop with real RDF tooling."""
        return {"@graph": json.loads(self.to_rdflib(base).serialize(format="json-ld"))}

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
                key = t.p
                if g.has_edge(t.s, t.o, key):
                    key = (t.p, len(g[t.s][t.o]))
                g.add_edge(t.s, t.o, key=key)
                g[t.s][t.o][key].update({"label": t.p, **deepcopy(t.attrs)})
                if t.rdf_terms:
                    g[t.s][t.o][key]["rdf_terms"] = deepcopy(t.rdf_terms)
            else:
                g.add_edge(t.s, t.o)
                g[t.s][t.o].update({"label": t.p, **deepcopy(t.attrs)})
        return g

    def to_html(
        self,
        path: Union[str, Path, None] = None,
        title: str = "trikedb knowledge graph",
        event_predicates=None,
        layout: str = "auto",
    ) -> str:
        """Render the workbench. See html.to_html.

        Imported here rather than at the top: a store that is never drawn
        should not carry the page that would draw it, and the core owning
        its own presentation is the one edge that would point backwards.
        """
        from .html import to_html

        return to_html(self, path=path, title=title,
                       event_predicates=event_predicates, layout=layout)

    # ------------------------------------------------------------- protocol

    def __len__(self) -> int:
        return len(self._triples)

    def __iter__(self) -> Iterator[Triple]:
        return (deepcopy(t) for t in self._triples)

    def __contains__(self, spo) -> bool:
        return any(t.spo() == tuple(spo) for t in self._triples)

    def __repr__(self) -> str:
        where = str(self.path) if self.path else "in-memory"
        return f"<TrikeDB {where}: {len(self)} triples, {len(self.predicates())} predicates>"


