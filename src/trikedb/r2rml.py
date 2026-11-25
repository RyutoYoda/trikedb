"""Read-only virtual RDF graph over DB-API tables using R2RML mappings.

The database remains the source of truth. Mapping and query results are never
written to the TrikeDB YAML store. Eligible queries use a SQL fast path;
other mappings use the graph-aware R2RML processor.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from urllib.parse import quote

from rdflib import Graph, Literal, Namespace, RDF, URIRef, Variable
from rdflib.plugins.sparql.processor import prepareQuery
from rdflib.query import Result
from rdflib.store import Store
from .r2rml_processor import R2RMLProcessor


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
    if len(text) >= 2 and text[0] == text[-1] == '"':
        inner = text[1:-1].replace('""', '"')
        if inner and all(ord(char) >= 32 for char in inner):
            return inner
    if _IDENT.fullmatch(text):
        return text
    raise ValueError(f"unsafe SQL identifier: {text!r}")


def _plain_string_filter(term, obj):
    """Only equality that preserves RDF literal terms across SQL type systems."""
    return (term.kind == "column" and term.datatype is None and term.language is None
            and isinstance(obj, Literal) and obj.datatype is None and obj.language is None)


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
        uri = _SLOT.sub(lambda match: quote(str(values[_identifier(match.group(1))]), safe=""),
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
        return ".".join(mark + part.replace(mark, mark + mark) + mark
                        for part in identifier.split("."))

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
            if params:
                cursor.execute(sql, tuple(params))
            else:
                cursor.execute(sql)
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
                    if _plain_string_filter(term, obj):
                        where.append(str(term.value))
                        params.append(str(obj))
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
                        if subject_params:
                            cursor.execute(sql, subject_params)
                        else:
                            cursor.execute(sql)
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


class _ProcessorStore(Store):
    """Expose the processor's default graph through the existing Graph API."""

    context_aware = False
    formula_aware = False
    graph_aware = False

    def __init__(self, processor):
        super().__init__()
        self.processor = processor

    def triples(self, triple_pattern, context=None):
        for triple in self.processor.dataset().default_graph.triples(triple_pattern):
            yield triple, iter(())

    def __len__(self, context=None):
        return len(self.processor.dataset().default_graph)


class R2RMLVirtualGraph:
    """A read-only RDF view of R2RML-mapped tables on a DB-API connection.

    Supported dialects: sqlite, snowflake, bigquery, databricks. Supply a
    connection with read-only credentials. The caller owns its lifecycle.
    ``placeholder`` is connector-specific: ``?`` or ``%s``.
    """

    def __init__(self, mapping, connection, *, dialect="sqlite", placeholder=None, base_iri=None):
        if dialect not in {"sqlite", "snowflake", "bigquery", "databricks"}:
            raise ValueError(f"unsupported SQL dialect: {dialect}")
        self.processor = R2RMLProcessor(mapping, connection, dialect=dialect, base_iri=base_iri)
        try:
            self.mapping = _parse(mapping)
        except ValueError:
            self.mapping = None
        if base_iri is not None:
            self.mapping = None
        # The legacy direct store does not model fixed-width CHAR padding,
        # temporal values, binary data, or SQL boolean conversion. Use the
        # full processor for these maps even when their syntax is otherwise
        # simple enough for the SQL BGP fast path.
        if any(re.match(r"^\s*CHAR\s*\(", sql_type, re.I) or
               any(token in sql_type.upper() for token in
                   ("DATE", "TIME", "BINARY", "BLOB", "BOOL"))
               for source in self.processor.maps.values() for sql_type in source.types.values()):
            self.mapping = None
        if placeholder is None:
            placeholder = "%s" if dialect == "snowflake" else "?"
        if placeholder not in {"?", "%s"}:
            raise ValueError("unsupported DB-API placeholder")
        self.graph = (Graph(store=_VirtualStore(self.mapping, connection, dialect, placeholder))
                      if self.mapping is not None else Graph(store=_ProcessorStore(self.processor)))

    def sparql(self, query):
        """Run a SPARQL query against the live virtual graph."""
        if self.mapping is None:
            return self.processor.dataset().query(query)
        pushed = self._pushdown_bgp(query)
        if pushed is not None:
            return pushed
        return self.graph.query(query)

    def _pushdown_bgp(self, query):
        """Combine a same-subject basic graph pattern into one source SELECT.

        Other SPARQL shapes still run through RDFLib. In particular, FILTER,
        OPTIONAL, UNION, aggregates, and cross-map graph joins must retain
        their general SPARQL semantics rather than be partly rewritten.
        """
        try:
            algebra = prepareQuery(query).algebra
        except Exception:
            return None  # Let RDFLib report malformed SPARQL as usual.
        if algebra.name not in {"SelectQuery", "AskQuery"} or algebra.datasetClause:
            return None
        project = algebra.p
        if project.name != "Project" or project.p.name != "BGP":
            return None
        patterns = project.p.triples
        if not patterns or any(not isinstance(p, URIRef) for _, p, _ in patterns):
            return None
        subjects = {s for s, _, _ in patterns}
        if len(subjects) != 1:
            return None
        if not isinstance(patterns[0][0], (Variable, URIRef)):
            return None

        candidates = []
        for mapping in self.mapping.values():
            selected = []
            for _, predicate, obj in patterns:
                if predicate == RDF.type and isinstance(obj, URIRef) and obj in mapping.classes:
                    selected.append((predicate, obj, None))
                    continue
                matches = [om for p, om in mapping.predicate_objects if p == predicate]
                if len(matches) != 1:
                    break
                selected.append((predicate, obj, matches[0]))
            else:
                candidates.append((mapping, selected))
        if len(candidates) != 1:
            return None

        mapping, selected = candidates[0]
        # A subject may collect triples from more than one triples map.
        # A one-map rewrite is safe only if no other map can supply a
        # predicate used by this basic graph pattern.
        requested_predicates = {predicate for _, predicate, _ in patterns}
        for other in self.mapping.values():
            if other is mapping:
                continue
            if (RDF.type in requested_predicates and other.classes or
                    any(p in requested_predicates for p, _ in other.predicate_objects)):
                return None
        store = self.graph.store
        subject_term = patterns[0][0]
        bound_subject = subject_term if isinstance(subject_term, URIRef) else None
        subject_where, subject_params = store._subject_filter(mapping.subject, bound_subject)
        if subject_where == ("__no_match__",):
            return self._empty_result(algebra)

        subject_columns = set(mapping.subject.columns())
        if len(selected) > 1 and not subject_columns:
            return None
        child_columns = {"c" + str(i): set(subject_columns) for i in range(len(selected))}
        parents = {}
        conditions = [("c0", col, value) for col, value in zip(subject_where, subject_params)]
        for i, (_, obj, object_map) in enumerate(selected):
            if object_map is None:
                continue
            if object_map.term is not None:
                term, alias = object_map.term, "c" + str(i)
                child_columns[alias].update(term.columns())
            else:
                parent = self.mapping[object_map.parent_map]
                alias = "p" + str(i)
                parents[i] = (alias, parent)
                term = parent.subject
                child_columns["c" + str(i)].update(child for child, _ in object_map.joins)
            if object_map.term is not None and _plain_string_filter(term, obj):
                conditions.append((alias, str(term.value), str(obj)))
            elif isinstance(obj, URIRef) and term.kind == "template":
                where, params = store._subject_filter(term, obj)
                if where == ("__no_match__",):
                    return self._empty_result(algebra)
                conditions.extend((alias, col, value) for col, value in zip(where, params))

        selections = [(alias, col) for alias, columns in child_columns.items()
                      for col in sorted(columns)]
        for i, (alias, parent) in parents.items():
            parent_columns = set(parent.subject.columns())
            parent_columns.update(col for _, col in selected[i][2].joins)
            selections.extend((alias, col) for col in sorted(parent_columns))
        sql = "SELECT " + ", ".join(
            f"{alias}.{store._q(col)} AS {store._q(alias + '_' + col)}"
            for alias, col in selections)
        sql += " FROM " + store._q(mapping.table) + " c0"
        for i in range(1, len(selected)):
            alias = "c" + str(i)
            sql += (" JOIN " + store._q(mapping.table) + " " + alias + " ON " +
                    " AND ".join(f"c0.{store._q(col)} = {alias}.{store._q(col)}"
                                 for col in sorted(subject_columns)))
        for i, (alias, parent) in parents.items():
            object_map = selected[i][2]
            sql += (" JOIN " + store._q(parent.table) + " " + alias + " ON " +
                    " AND ".join(f"c{i}.{store._q(child)} = {alias}.{store._q(parent_col)}"
                                 for child, parent_col in object_map.joins))
        if conditions:
            sql += " WHERE " + " AND ".join(
                f"{alias}.{store._q(col)} = {store.placeholder}" for alias, col, _ in conditions)
        params = tuple(value for _, _, value in conditions)

        cursor = store.connection.cursor()
        bindings = []
        seen = set()
        try:
            cursor.execute(sql, params) if params else cursor.execute(sql)
            while batch := cursor.fetchmany(1000):
                for values in batch:
                    row = dict(zip((alias + "_" + col for alias, col in selections), values))
                    subject = mapping.subject.evaluate({
                        col: row["c0_" + col] for col in subject_columns})
                    if subject is None or bound_subject not in (None, subject):
                        continue
                    binding = {}
                    if isinstance(subject_term, Variable):
                        binding[subject_term] = subject
                    valid = True
                    for i, (_, requested, object_map) in enumerate(selected):
                        if object_map is None:
                            value = requested
                        elif object_map.term is not None:
                            alias = "c" + str(i)
                            value = object_map.term.evaluate({
                                col: row[alias + "_" + col] for col in child_columns[alias]})
                        else:
                            alias, parent = parents[i]
                            parent_row = {col: row[alias + "_" + col]
                                          for col in parent.subject.columns()}
                            value = parent.subject.evaluate(parent_row)
                        if value is None or (not isinstance(requested, Variable)
                                             and value != requested):
                            valid = False
                            break
                        if isinstance(requested, Variable):
                            if requested in binding and binding[requested] != value:
                                valid = False
                                break
                            binding[requested] = value
                    if not valid:
                        continue
                    key = tuple(sorted(binding.items(), key=lambda pair: str(pair[0])))
                    if key not in seen:
                        seen.add(key)
                        bindings.append(binding)
                        if algebra.name == "AskQuery":
                            result = Result("ASK")
                            result.askAnswer = True
                            return result
        finally:
            cursor.close()
        if algebra.name == "AskQuery":
            return self._empty_result(algebra)
        result = Result("SELECT")
        result.vars = project.PV
        result.bindings = [{variable: binding[variable] for variable in result.vars
                            if variable in binding} for binding in bindings]
        return result

    @staticmethod
    def _empty_result(algebra):
        if algebra.name == "AskQuery":
            result = Result("ASK")
            result.askAnswer = False
        else:
            result = Result("SELECT")
            result.vars = algebra.PV
            result.bindings = []
        return result

    def export_rdf(self, format="nt"):
        """Materialize an interoperable RDF snapshot (e.g. N-Triples for n10s)."""
        if format not in {"nt", "turtle", "nquads"}:
            raise ValueError("supported RDF exports: nt, turtle, nquads")
        dataset = self.processor.dataset()
        if format == "nquads":
            return dataset.serialize(format="nquads")
        return dataset.default_graph.serialize(format=format)
