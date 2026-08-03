"""Core triple store: a knowledge graph persisted as a single YAML file."""

from __future__ import annotations

import fnmatch
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence, Union

import yaml

__all__ = ["Triple", "TripLite", "OntologyError"]


class OntologyError(ValueError):
    """Raised when a triple uses a predicate not declared in the ontology."""


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
            s, p, o = str(d.pop("s")), str(d.pop("p")), str(d.pop("o"))
        except KeyError as exc:
            raise ValueError(f"triple is missing required key {exc}: {data!r}") from None
        return cls(s, p, o, d)


def _term_match(pattern: Optional[str], value: str) -> bool:
    """None is a wildcard; '*'/'?' in a pattern enables glob matching."""
    if pattern is None:
        return True
    if any(ch in pattern for ch in "*?[") :
        return fnmatch.fnmatchcase(value, pattern)
    return pattern == value


class TripLite:
    """A YAML-backed triple store with a graph-database interface.

    >>> db = TripLite("graph.yaml")
    >>> db.add("salesflow-crm", "PROVIDES", "crm-sync-job")
    >>> for t in db.triples(p="PROVIDES"):
    ...     print(t.s, "->", t.o)
    >>> db.save()
    """

    def __init__(
        self,
        path: Union[str, Path, None] = None,
        ontology: Union[dict, Sequence[str], None] = None,
    ):
        self.path: Optional[Path] = Path(path) if path else None
        #: predicate -> human description. Empty dict means free-form predicates.
        self.ontology: dict = {}
        self._triples: list = []
        if ontology is not None:
            if isinstance(ontology, dict):
                self.ontology = {str(k): str(v or "") for k, v in ontology.items()}
            else:
                self.ontology = {str(p): "" for p in ontology}
        if self.path and self.path.exists():
            self._load()

    # ------------------------------------------------------------------ io

    def _load(self) -> None:
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        onto = data.get("ontology") or {}
        preds = onto.get("predicates", onto) if isinstance(onto, dict) else onto
        if isinstance(preds, dict):
            for k, v in preds.items():
                self.ontology.setdefault(str(k), str(v or ""))
        elif isinstance(preds, (list, tuple)):
            for p in preds:
                self.ontology.setdefault(str(p), "")
        for item in data.get("triples") or []:
            self._triples.append(Triple.from_dict(item))

    def save(self, path: Union[str, Path, None] = None) -> Path:
        """Write the graph back to YAML. Plain triples stay on one line."""
        target = Path(path) if path else self.path
        if target is None:
            raise ValueError("no path given and TripLite was created without one")
        doc: dict = {}
        if self.ontology:
            doc["ontology"] = {"predicates": dict(self.ontology)}
        doc["triples"] = [t.to_dict() for t in self._triples]
        text = yaml.dump(
            doc,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=None,
            width=120,
        )
        target.write_text(text, encoding="utf-8")
        self.path = target
        return target

    # -------------------------------------------------------------- writing

    def add(self, s: str, p: str, o: str, **attrs: Any) -> Triple:
        """Add (or upsert) a triple. Same (s, p, o) merges attributes."""
        if self.ontology and p not in self.ontology:
            raise OntologyError(
                f"predicate {p!r} is not in the ontology "
                f"(allowed: {sorted(self.ontology)})"
            )
        for t in self._triples:
            if t.spo() == (s, p, o):
                t.attrs.update(attrs)
                return t
        triple = Triple(str(s), str(p), str(o), dict(attrs))
        self._triples.append(triple)
        return triple

    def remove(
        self,
        s: Optional[str] = None,
        p: Optional[str] = None,
        o: Optional[str] = None,
    ) -> int:
        """Remove all triples matching the pattern. Returns how many."""
        keep = [t for t in self._triples if not self._matches(t, s, p, o)]
        removed = len(self._triples) - len(keep)
        self._triples = keep
        return removed

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
        return _unique(x for t in self._triples for x in (t.s, t.o))

    # ---------------------------------------------------------------- query

    def query(self, patterns: Sequence) -> list:
        """Match multiple patterns with shared variables (SPARQL-style BGP).

        Each pattern is an (s, p, o) tuple or a string like '?src PROVIDES ?job'.
        Terms starting with '?' are variables; bindings are joined across
        patterns. Returns a list of {variable: value} dicts.

        >>> db.query(["?src PROVIDES ?job", "?job INGESTS_TO ?table"])
        [{'src': ..., 'job': ..., 'table': ...}, ...]
        """
        parsed = [self._parse_pattern(pat) for pat in patterns]
        bindings: list = [{}]
        for pat in parsed:
            step = []
            for binding in bindings:
                for t in self._triples:
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

    # -------------------------------------------------------------- sparql

    def to_rdflib(self, base: str = "urn:triplite:"):
        """Convert to an rdflib.Graph. Requires the [sparql] extra.

        Subjects and predicates become URIRefs under `base`. Objects become
        URIRefs too, unless they contain whitespace (e.g. change-event
        descriptions), in which case they become Literals.
        """
        try:
            from rdflib import Graph, Literal, URIRef
        except ImportError:  # pragma: no cover
            raise ImportError(
                "SPARQL support requires rdflib — pip install 'triplite[sparql]'"
            ) from None
        from urllib.parse import quote

        def node(name: str):
            return URIRef(base + quote(name, safe=""))

        g = Graph()
        g.bind("t", base)
        for t in self._triples:
            obj = Literal(t.o) if any(c.isspace() for c in t.o) else node(t.o)
            g.add((node(t.s), node(t.p), obj))
        return g

    def sparql(self, query: str, base: str = "urn:triplite:"):
        """Run a real SPARQL 1.1 query (via rdflib) against the graph.

        The prefix `t:` is bound to `base`, so predicates are written
        `t:PROVIDES`. SELECT returns a list of {var: value} dicts with
        URIs shortened back to plain names; ASK returns a bool.

        >>> db.sparql("SELECT ?v ?t WHERE { ?v t:PROVIDES ?j . ?j t:INGESTS_TO ?t }")
        """
        from urllib.parse import unquote

        g = self.to_rdflib(base)
        result = g.query(f"PREFIX t: <{base}>\n" + query)
        if result.type == "ASK":
            return result.askAnswer

        def shorten(value) -> str:
            text = str(value)
            if text.startswith(base):
                return unquote(text[len(base):])
            return text

        rows = []
        for binding in result:
            row = {}
            for var, value in zip(result.vars, binding):
                if value is not None:
                    row[str(var)] = shorten(value)
            rows.append(row)
        return rows

    # -------------------------------------------------------------- exports

    def to_jsonld(self, base: str = "urn:triplite:") -> dict:
        """Best-effort JSON-LD export for interop with real RDF tooling."""
        context = {p: {"@id": base + p, "@type": "@id"} for p in self.predicates()}
        nodes: dict = {}
        for t in self._triples:
            node = nodes.setdefault(t.s, {"@id": t.s})
            node.setdefault(t.p, []).append(t.o)
        return {"@context": context, "@graph": list(nodes.values())}

    def to_html(self, path: Union[str, Path, None] = None, title: str = "triplite graph") -> str:
        from .html import to_html

        return to_html(self, path=path, title=title)

    # ------------------------------------------------------------- protocol

    def __len__(self) -> int:
        return len(self._triples)

    def __iter__(self) -> Iterator[Triple]:
        return iter(self._triples)

    def __contains__(self, spo) -> bool:
        return any(t.spo() == tuple(spo) for t in self._triples)

    def __repr__(self) -> str:
        where = str(self.path) if self.path else "in-memory"
        return f"<TripLite {where}: {len(self)} triples, {len(self.predicates())} predicates>"


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
