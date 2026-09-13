"""What a triple *is* — the pieces every other module needs and none of
them should own twice.

This module is the bottom of the package: it imports nothing from trikedb.
Everything else may import it, which is what lets ``html`` draw events and
``reasoning`` shorten IRIs without either of them reaching back into the
store — the import cycles those two used to need are gone, not deferred
into function bodies.
"""

from __future__ import annotations

import datetime
import fnmatch
import json
import re
import shlex
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Optional

import yaml

__all__ = ["Triple", "OntologyError", "TIME_ATTRS", "RULE_KEYS"]


class OntologyError(ValueError):
    """Raised when a triple uses a predicate not declared in the ontology."""


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


def _plain(value):
    """YAML scalars json can hold.

    An unquoted ``at: 2025-04-01`` — the natural way to date an event —
    comes back from PyYAML as a ``datetime.date``, which json refuses.
    That put a TypeError between a perfectly ordinary graph and
    ``content_hash()``, ``to_html()`` and every JSON surface downstream.
    Dates are kept, as the ISO text they were written as.
    """
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


_DIGIT_RUN = re.compile(r"\d+")


def _time_key(text: str) -> str:
    """Sort key for a time somebody typed, not the string anyone sees.

    Pad every number so 2025/4/1 lands where 2025-04-01 does, and drop the
    separators so two spellings of the same day compare equal instead of
    comparing their punctuation. Left as plain text compare otherwise, a
    node wears the state of an event months out of date.
    """
    return "".join(m.group().zfill(4) for m in _DIGIT_RUN.finditer(text))


def _now() -> str:
    """Local time, with its offset — what an action stamps.

    To the microsecond, because an agent acts faster than a second — a loop
    of five actions stamped to the second claimed one instant between them,
    and a log whose rows all say the same time is not telling you when
    anything happened. Ties are still possible and still fine: history()
    settles them by the order they were written.
    """
    return datetime.datetime.now().astimezone().isoformat(timespec="microseconds")


# One of these attributes is what makes a triple a change event rather than
# a plain relation: it happened, and here is when. Shared with html.py,
# which draws events, and with identity(), which keeps two of them apart.
TIME_ATTRS = ("at", "when", "date", "time", "timestamp", "occurred", "recorded")

# What a predicate can declare about itself. The first two say what an action
# may connect; the second two say when it may run and who may run it. A
# semantic layer stops at the first two and leaves the rest to whatever code
# happens to perform the update — which is how an order gets delivered before
# it shipped, and how an approval ends up with nobody's name on it.
RULE_KEYS = ("domain", "range", "requires", "by")


@dataclass
class Triple:
    """A single subject-predicate-object statement, with optional attributes."""

    s: str
    p: str
    o: str
    attrs: dict = field(default_factory=dict)
    rdf_terms: dict = field(default_factory=dict)

    def spo(self) -> tuple:
        return (self.s, self.p, self.o)

    def to_dict(self) -> dict:
        result = {"s": self.s, "p": self.p, "o": self.o, **deepcopy(self.attrs)}
        if self.rdf_terms:
            result["rdf_terms"] = deepcopy(self.rdf_terms)
        return result

    def when(self) -> str:
        """When this says it happened, or "" if it is not an event."""
        for key in TIME_ATTRS:
            if key in self.attrs:
                return str(self.attrs[key])
        return ""

    def identity(self):
        # The time is part of what an event *is*. Without it, "restarted
        # after failure" in April and the same line in September are one
        # triple, and add() — an upsert on (s, p, o) — quietly overwrites
        # the April record with the September one. A log you can delete
        # from by appending to it is not a log.
        return self.spo() + (self.when(),
                             json.dumps(self.rdf_terms, sort_keys=True))

    def as_rdf(self, base="urn:trikedb:"):
        from rdflib import BNode, Literal, URIRef
        result = []
        for key, text in zip(("s", "p", "o"), self.spo()):
            spec = self.rdf_terms.get(key)
            if spec:
                value = spec.get("value", text)
                kind = spec["kind"]
                if kind == "literal":
                    term = Literal(value, lang=spec.get("language"),
                                   datatype=spec.get("datatype"), normalize=False)
                elif kind == "bnode":
                    term = BNode(value)
                else:
                    term = URIRef(value if "value" in spec else _iri_node(text, base))
            elif key == "o" and any(c.isspace() for c in text):
                term = Literal(text)
            else:
                term = URIRef(_iri_node(text, base))
            result.append(term)
        return tuple(result)

    @classmethod
    def from_rdf(cls, s, p, o, base="urn:trikedb:"):
        from rdflib import BNode, Literal, URIRef
        values = tuple(_shorten(t, base) if isinstance(t, URIRef) else str(t)
                       for t in (s, p, o))
        row = cls(*values)
        defaults = row.as_rdf(base)
        for key, term, default in zip(("s", "p", "o"), (s, p, o), defaults):
            if term == default:
                continue
            spec = {"kind": "literal" if isinstance(term, Literal) else
                    "bnode" if isinstance(term, BNode) else "iri", "value": str(term)}
            if isinstance(term, Literal):
                if term.datatype:
                    spec["datatype"] = str(term.datatype)
                if term.language:
                    spec["language"] = term.language
            row.rdf_terms[key] = spec
        return row

    @classmethod
    def from_dict(cls, data: dict) -> "Triple":
        d = dict(data)
        try:
            s, p, o = d.pop("s"), d.pop("p"), d.pop("o")
        except KeyError as exc:
            raise ValueError(f"triple is missing required key {exc}: {data!r}") from None
        terms = d.pop("rdf_terms", {})
        _validate_rdf_terms(terms)
        s, p = _term(s, "s", data), _term(p, "p", data)
        o = str(o) if terms.get("o", {}).get("kind") == "literal" and o is not None else _term(o, "o", data)
        return cls(s, p, o, _plain(d), deepcopy(terms))


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


def _is_pattern(need: str) -> bool:
    """Is this condition a step, or a whole shape to join?

    A predicate name is one token; anything with a space in it is an
    (s p o) pattern. That is the whole distinction, so that the short
    spelling stays short and the two never need a flag to tell apart.
    """
    return len(shlex.split(need)) == 3


def _term_match(pattern: Optional[str], value: str) -> bool:
    """None is a wildcard; '*'/'?' in a pattern enables glob matching."""
    if pattern is None:
        return True
    if any(ch in pattern for ch in "*?[") :
        return fnmatch.fnmatchcase(value, pattern)
    return pattern == value

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


def _iri_node(name, base):
    return name if name.startswith(("http://", "https://", "urn:")) else _iri(name, base)


def _validate_rdf_terms(terms):
    if not isinstance(terms, dict):
        raise ValueError("rdf_terms must be a mapping")
    for key, spec in terms.items():
        if key not in {"s", "p", "o"} or not isinstance(spec, dict):
            raise ValueError("rdf_terms keys must be s/p/o mappings")
        if set(spec) - {"kind", "value", "datatype", "language"}:
            raise ValueError("unknown RDF term metadata")
        kind = spec.get("kind")
        if kind not in {"iri", "literal", "bnode"} or (key == "p" and kind != "iri") or (key == "s" and kind == "literal"):
            raise ValueError("invalid RDF term kind for " + key)
        if any(not isinstance(v, str) for v in spec.values()):
            raise ValueError("RDF term metadata values must be strings")
        if ("datatype" in spec or "language" in spec) and kind != "literal":
            raise ValueError("only literals can have datatype/language")
        if "datatype" in spec and "language" in spec:
            raise ValueError("a literal cannot have both datatype and language")
