"""Read-only virtual RDF graph over DB-API tables using a strict R2RML subset.

The database remains the source of truth. Mapping and query results are never
written to the TrikeDB YAML store. Unsupported R2RML features fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from urllib.parse import quote

from rdflib import Graph, Literal, Namespace, RDF, URIRef
from rdflib.store import Store


RR = Namespace("http://www.w3.org/ns/r2rml#")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_SLOT = re.compile(r"\{([^{}]+)\}")
_SUPPORTED = {RR.logicalTable, RR.tableName, RR.subjectMap,
              RR.template, RR.predicateObjectMap, RR.predicate,
              RR.objectMap, RR.column,
              RR.constant, RR.parentTriplesMap, RR.joinCondition, RR.child,
              RR.parent, RR.datatype, RR.language, RR.termType}
_SUPPORTED.add(RR["class"])


def _one(graph, subject, predicate, required=True):
    values = list(graph.objects(subject, predicate))
    if len(values) != 1:
        if not values and not required:
            return None
        raise ValueError(f"R2RML requires exactly one {predicate} for {subject}")
    return values[0]


def _identifier(name):
    text = str(name)
    if not _IDENT.fullmatch(text):
        raise ValueError(f"unsafe SQL identifier: {text!r}")
    return text


@dataclass(frozen=True)
class _TermMap:
    kind: str
    value: object
    datatype: URIRef | None = None
    language: str | None = None

    def columns(self):
        if self.kind == "column":
            return {_identifier(self.value)}
        if self.kind == "template":
            return {_identifier(s) for s in _SLOT.findall(str(self.value))}
        return set()

    def evaluate(self, row):
        if self.kind == "constant":
            return self.value
        if self.kind == "column":
            value = row[_identifier(self.value)]
            return None if value is None else Literal(value, datatype=self.datatype,
                                                       lang=self.language)
        values = {column: row[column] for column in self.columns()}
        if any(value is None for value in values.values()):
            return None
        uri = _SLOT.sub(lambda match: quote(str(values[match.group(1)]), safe=""),
                        str(self.value))
        return URIRef(uri)


def _term_map(graph, node, *, subject=False):
    choices = [(name, _one(graph, node, predicate, False)) for name, predicate in
               (("template", RR.template), ("column", RR.column), ("constant", RR.constant))]
    choices = [(name, value) for name, value in choices if value is not None]
    if len(choices) != 1:
        raise ValueError("R2RML term map requires one template, column, or constant")
    kind, value = choices[0]
    if subject and kind != "template":
        raise ValueError("unsupported R2RML subject map; use an IRI template")
    if kind == "template" and not str(value).startswith(("http://", "https://", "urn:")):
        raise ValueError("unsupported relative R2RML template")
    datatype = _one(graph, node, RR.datatype, False)
    language = _one(graph, node, RR.language, False)
    term_type = _one(graph, node, RR.termType, False)
    if term_type is not None:
        expected = RR.IRI if kind == "template" or subject else RR.Literal
        if term_type != expected:
            raise ValueError("unsupported R2RML termType")
    if datatype and language:
        raise ValueError("R2RML object cannot have both datatype and language")
    return _TermMap(kind, value, datatype, str(language) if language else None)


@dataclass(frozen=True)
class _ObjectMap:
    term: _TermMap | None
    parent_map: object | None
    joins: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class _TriplesMap:
    name: object
    table: str
    subject: _TermMap
    classes: tuple[URIRef, ...]
    predicate_objects: tuple[tuple[URIRef, _ObjectMap], ...]


def _parse(mapping):
    graph = Graph()
    if isinstance(mapping, Path) or (isinstance(mapping, str) and "\n" not in mapping
                                     and Path(mapping).exists()):
        graph.parse(str(mapping), format="turtle")
    else:
        graph.parse(data=str(mapping), format="turtle")
    maps = {}
    for node in graph.subjects(RDF.type, RR.TriplesMap):
        logical = _one(graph, node, RR.logicalTable)
        table = _one(graph, logical, RR.tableName, False)
        if table is None:
            raise ValueError("unsupported R2RML logical table: only rr:tableName is supported")
        table = ".".join(_identifier(part) for part in str(table).split("."))
        subject_node = _one(graph, node, RR.subjectMap, False)
        if subject_node is None:
            raise ValueError("unsupported R2RML shorthand subject")
        subject = _term_map(graph, subject_node, subject=True)
        classes = tuple(graph.objects(subject_node, RR["class"]))
        pos = []
        for pom in graph.objects(node, RR.predicateObjectMap):
            predicates = list(graph.objects(pom, RR.predicate))
            if not predicates or any(not isinstance(p, URIRef) for p in predicates):
                raise ValueError("unsupported R2RML predicate map")
            objects = list(graph.objects(pom, RR.objectMap))
            if len(objects) != 1:
                raise ValueError("unsupported R2RML object map")
            obj = objects[0]
            parent = _one(graph, obj, RR.parentTriplesMap, False)
            if parent is not None:
                joins = tuple((_identifier(_one(graph, j, RR.child)),
                               _identifier(_one(graph, j, RR.parent)))
                              for j in graph.objects(obj, RR.joinCondition))
                if not joins:
                    raise ValueError("unsupported parentTriplesMap without joinCondition")
                object_map = _ObjectMap(None, parent, joins)
            else:
                object_map = _ObjectMap(_term_map(graph, obj), None, ())
            pos.extend((p, object_map) for p in predicates)
        maps[node] = _TriplesMap(node, table, subject, classes, tuple(pos))
    if not maps:
        raise ValueError("R2RML has no rr:TriplesMap")
    for mapping_node in maps.values():
        for _, object_map in mapping_node.predicate_objects:
            if object_map.parent_map is not None and object_map.parent_map not in maps:
                raise ValueError("R2RML parentTriplesMap not found")
    # Every statement must be accounted for; silently dropping mapping rules
    # would produce a graph that looks valid but is incomplete.
    allowed_predicates = _SUPPORTED | {RDF.type}
    for _, predicate, _ in graph:
        if predicate not in allowed_predicates:
            raise ValueError(f"unsupported R2RML property: {predicate}")
    return maps


class _VirtualStore(Store):
    context_aware = False
    formula_aware = False
    graph_aware = False

    def __init__(self, maps, connection, dialect, placeholder):
        super().__init__()
        self.maps = maps
        self.connection = connection
        self.dialect = dialect
        self.placeholder = placeholder

    def _q(self, identifier):
        mark = "`" if self.dialect in {"bigquery", "databricks"} else '"'
        return ".".join(mark + _identifier(part) + mark for part in identifier.split("."))

    def _rows(self, table, columns, where=(), params=()):
        names = sorted(set(columns))
        if not names:
            raise ValueError("R2RML mapping requires at least one column")
        sql = ("SELECT " + ", ".join(self._q(n) for n in names) +
               " FROM " + self._q(table))
        if where:
            sql += " WHERE " + " AND ".join(self._q(c) + " = " + self.placeholder
                                            for c in where)
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql, tuple(params))
            while batch := cursor.fetchmany(1000):
                for values in batch:
                    yield dict(zip(names, values))
        finally:
            cursor.close()

    def _subject_filter(self, term, subject):
        if subject is None or term.kind != "template" or not isinstance(subject, URIRef):
            return (), ()
        template = str(term.value)
        slots = _SLOT.findall(template)
        if len(slots) != 1:
            return (), ()
        prefix, suffix = template.split("{" + slots[0] + "}")
        value = str(subject)
        if not value.startswith(prefix) or not value.endswith(suffix):
            return ("__no_match__",), ()
        from urllib.parse import unquote
        captured = value[len(prefix):len(value) - len(suffix) if suffix else None]
        return (slots[0],), (unquote(captured),)

    def triples(self, triple_pattern, context=None):
        subject, predicate, obj = triple_pattern
        for mapping in self.maps.values():
            subject_where, subject_params = self._subject_filter(mapping.subject, subject)
            if subject_where == ("__no_match__",):
                continue
            columns = mapping.subject.columns()
            for cls in mapping.classes:
                if predicate not in (None, RDF.type) or obj not in (None, cls):
                    continue
                for row in self._rows(mapping.table, columns, subject_where, subject_params):
                    s = mapping.subject.evaluate(row)
                    if s is not None and subject in (None, s):
                        yield (s, RDF.type, cls), iter(())
            for p, object_map in mapping.predicate_objects:
                if predicate not in (None, p):
                    continue
                if object_map.term is not None:
                    term = object_map.term
                    where, params = list(subject_where), list(subject_params)
                    if obj is not None and term.kind == "column" and isinstance(obj, Literal):
                        where.append(str(term.value))
                        params.append(obj.toPython())
                    for row in self._rows(mapping.table, columns | term.columns(), where, params):
                        s, o = mapping.subject.evaluate(row), term.evaluate(row)
                        if s is not None and o is not None and subject in (None, s) and obj in (None, o):
                            yield (s, p, o), iter(())
                else:
                    parent = self.maps[object_map.parent_map]
                    child_cols = {c for c, _ in object_map.joins}
                    parent_cols = {c for _, c in object_map.joins}
                    # Read the joined rows directly; the graph is never copied.
                    aliases = [("c_" + c, c) for c in sorted(columns | child_cols)] + [
                        ("p_" + c, c) for c in sorted(parent.subject.columns() | parent_cols)]
                    sql = ("SELECT " + ", ".join(
                        ("c." if alias.startswith("c_") else "p.") + self._q(col) +
                        " AS " + self._q(alias) for alias, col in aliases) +
                        " FROM " + self._q(mapping.table) + " c JOIN " +
                        self._q(parent.table) + " p ON " + " AND ".join(
                            "c." + self._q(c) + " = p." + self._q(pc)
                            for c, pc in object_map.joins))
                    if subject_where:
                        sql += " WHERE " + " AND ".join(
                            "c." + self._q(c) + " = " + self.placeholder for c in subject_where)
                    cursor = self.connection.cursor()
                    try:
                        cursor.execute(sql, subject_params)
                        while batch := cursor.fetchmany(1000):
                            for values in batch:
                                combined = dict(zip((a for a, _ in aliases), values))
                                s = mapping.subject.evaluate({c: combined["c_" + c]
                                                              for c in columns})
                                o = parent.subject.evaluate({c: combined["p_" + c]
                                                             for c in parent.subject.columns()})
                                if s is not None and o is not None and subject in (None, s) and obj in (None, o):
                                    yield (s, p, o), iter(())
                    finally:
                        cursor.close()

    def __len__(self, context=None):
        return sum(1 for _ in self.triples((None, None, None)))


class R2RMLVirtualGraph:
    """A read-only RDF view of R2RML-mapped tables on a DB-API connection.

    Supported dialects: sqlite, snowflake, bigquery, databricks. Supply a
    connection with read-only credentials. The caller owns its lifecycle.
    ``placeholder`` is connector-specific: ``?`` or ``%s``.
    """

    def __init__(self, mapping, connection, *, dialect="sqlite", placeholder=None):
        if dialect not in {"sqlite", "snowflake", "bigquery", "databricks"}:
            raise ValueError(f"unsupported SQL dialect: {dialect}")
        self.mapping = _parse(mapping)
        if placeholder is None:
            placeholder = "%s" if dialect == "snowflake" else "?"
        if placeholder not in {"?", "%s"}:
            raise ValueError("unsupported DB-API placeholder")
        self.graph = Graph(store=_VirtualStore(self.mapping, connection, dialect, placeholder))

    def sparql(self, query):
        """Run a SPARQL query against the live virtual graph."""
        return self.graph.query(query)

    def export_rdf(self, format="nt"):
        """Materialize an interoperable RDF snapshot (e.g. N-Triples for n10s)."""
        if format not in {"nt", "turtle"}:
            raise ValueError("supported RDF exports: nt, turtle")
        snapshot = Graph()
        for triple, _ in self.graph.store.triples((None, None, None)):
            snapshot.add(triple)
        return snapshot.serialize(format=format)
