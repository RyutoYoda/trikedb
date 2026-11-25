"""R2RML row-to-RDF processor, independent of the virtual query fast path.

The mapping is a reviewed Turtle file and the DB-API connection must be
read-only. SQL queries in a mapping are restricted to one SELECT statement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
import re
from urllib.parse import quote, urlsplit

from rdflib import BNode, Dataset, Graph, Literal, Namespace, RDF, URIRef, XSD


RR = Namespace("http://www.w3.org/ns/r2rml#")
_REGULAR = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*$")
_SLOT = re.compile(r"\{([^{}]+)\}")
_LANGUAGE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_ALLOWED = {RDF.type, RR.logicalTable, RR.tableName, RR.sqlQuery, RR.sqlVersion,
            RR.subjectMap, RR.subject, RR.predicateObjectMap, RR.predicate,
            RR.predicateMap, RR.objectMap, RR.object, RR.graph, RR.graphMap,
            RR.template, RR.column, RR.constant, RR.termType, RR.datatype,
            RR.language, RR.parentTriplesMap, RR.joinCondition, RR.child,
            RR.parent, RR.inverseExpression, RR["class"]}


def _one(graph, subject, predicate, *, required=False):
    values = list(graph.objects(subject, predicate))
    if len(values) > 1 or (required and not values):
        raise ValueError(f"R2RML requires exactly one {predicate} for {subject}")
    return values[0] if values else None


def _identifier(text):
    """Return the SQL identifier value, never raw SQL syntax."""
    text = str(text)
    if len(text) >= 2 and text[0] == text[-1] == '"':
        inner = text[1:-1]
        if not inner or re.search(r'"(?!")', inner) or any(ord(c) < 32 for c in inner):
            raise ValueError(f"invalid SQL identifier: {text!r}")
        return inner.replace('""', '"')
    if _REGULAR.fullmatch(text):
        return text
    raise ValueError(f"invalid SQL identifier: {text!r}")


def _canonical_identifier(text):
    text = str(text)
    return _identifier(text) if text.startswith('"') else _identifier(text).upper()


def _qualified(text):
    text = str(text)
    pieces = []
    start = 0
    quoted = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == '"':
            if quoted and index + 1 < len(text) and text[index + 1] == '"':
                index += 2
                continue
            quoted = not quoted
        elif char == '.' and not quoted:
            pieces.append(_identifier(text[start:index]))
            start = index + 1
        index += 1
    if quoted:
        raise ValueError("unclosed SQL identifier")
    pieces.append(_identifier(text[start:]))
    return tuple(pieces)


def _quote(name, dialect):
    mark = '`' if dialect in {"bigquery", "databricks"} else '"'
    return mark + name.replace(mark, mark + mark) + mark


def _literal(value, sql_type, datatype=None, language=None):
    if datatype is not None:
        return Literal(value, datatype=datatype)
    if language is not None:
        return Literal(str(value), lang=language)
    sql_type = (sql_type or "").upper()
    fixed = re.fullmatch(r"CHAR\s*\(\s*(\d+)\s*\)", sql_type)
    if fixed and isinstance(value, str):
        value = value.ljust(int(fixed.group(1)))
    if isinstance(value, bytes):
        return Literal(value.hex().upper(), datatype=XSD.hexBinary)
    if isinstance(value, bool) or "BOOL" in sql_type:
        return Literal(bool(value), datatype=XSD.boolean)
    if isinstance(value, datetime) or "TIMESTAMP" in sql_type:
        return Literal(str(value).replace(' ', 'T'), datatype=XSD.dateTime)
    if isinstance(value, date) or sql_type == "DATE":
        return Literal(str(value), datatype=XSD.date)
    if isinstance(value, int):
        return Literal(value, datatype=XSD.integer)
    if isinstance(value, float):
        return Literal(value, datatype=XSD.double)
    return Literal(str(value))


@dataclass(frozen=True)
class Term:
    node: object
    kind: str
    value: object
    term_type: URIRef
    base: str
    datatype: URIRef | None = None
    language: str | None = None

    def references(self):
        if self.kind == "column":
            return (str(self.value),)
        if self.kind == "template":
            return tuple(_SLOT.findall(str(self.value)))
        return ()

    def columns(self):
        return {_identifier(ref) for ref in self.references()}

    def evaluate(self, row, types):
        if self.kind == "constant":
            return self.value
        if self.kind == "column":
            name = _identifier(self.value)
            value = row.get(name)
            if value is None:
                return None
            if self.term_type == RR.Literal:
                return _literal(value, types.get(name), self.datatype, self.language)
            lexical = value.hex().upper() if isinstance(value, bytes) else str(value)
        else:
            if any(row.get(_identifier(ref)) is None for ref in self.references()):
                return None
            safe = "-._~" if self.term_type == RR.IRI else ""
            lexical = _SLOT.sub(lambda m: quote(row[_identifier(m.group(1))].hex().upper()
                                              if isinstance(row[_identifier(m.group(1))], bytes)
                                              else str(row[_identifier(m.group(1))]), safe=safe)
                                if self.term_type == RR.IRI else str(row[_identifier(m.group(1))]),
                                str(self.value))
            lexical = lexical.replace('\\{', '{').replace('\\}', '}')
        if self.term_type == RR.Literal:
            return Literal(lexical, datatype=self.datatype, lang=self.language)
        if self.term_type == RR.BlankNode:
            key = lexical.encode()
            return BNode('r2rml' + sha256(key).hexdigest())
        # R2RML resolves generated relative IRIs by concatenating the base IRI.
        # RFC 3986 path resolution would change values containing ../ or /.
        iri = lexical if urlsplit(lexical).scheme else self.base + lexical
        if not urlsplit(iri).scheme or any(c.isspace() for c in iri):
            raise ValueError(f"invalid IRI value in R2RML source: {lexical!r}")
        return URIRef(iri)


@dataclass(frozen=True)
class Object:
    term: Term | None
    parent: object | None
    joins: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class PredicateObject:
    predicates: tuple[Term, ...]
    objects: tuple[Object, ...]
    graphs: tuple[Term, ...]


@dataclass(frozen=True)
class Map:
    node: object
    table: tuple[str, ...] | None
    query: str | None
    subject: Term
    classes: tuple[URIRef, ...]
    graphs: tuple[Term, ...]
    pos: tuple[PredicateObject, ...]
    columns: tuple[str, ...]
    types: dict[str, str]
    canonical_columns: frozenset[str]


class R2RMLProcessor:
    """Build RDF quads from source rows according to a R2RML mapping."""

    def __init__(self, mapping, connection, dialect="sqlite", base_iri=None):
        self.connection = connection
        self.dialect = dialect
        source = Path(mapping).read_text(encoding="utf-8") if isinstance(mapping, Path) or (
            isinstance(mapping, str) and "\n" not in mapping and Path(mapping).exists()) else str(mapping)
        base_match = re.search(r'@base\s+<([^>]+)>', source)
        self.base = base_iri or (base_match.group(1) if base_match else "http://example.org/")
        graph = Graph().parse(data=source, format="turtle", publicID=self.base)
        for _, predicate, _ in graph:
            if str(predicate).startswith(str(RR)) and predicate not in _ALLOWED:
                raise ValueError(f"unsupported R2RML property: {predicate}")
        self.maps = {}
        # rdf:type rr:TriplesMap is optional in R2RML. The logicalTable
        # predicate identifies a triples map even without a type declaration.
        for node in set(graph.subjects(RR.logicalTable, None)):
            logical = _one(graph, node, RR.logicalTable, required=True)
            table_node = _one(graph, logical, RR.tableName)
            query_node = _one(graph, logical, RR.sqlQuery)
            if (table_node is None) == (query_node is None):
                raise ValueError("R2RML logical table needs one tableName or sqlQuery")
            sql_version = _one(graph, logical, RR.sqlVersion)
            if sql_version is not None and sql_version != RR.SQL2008:
                raise ValueError("unsupported rr:sqlVersion")
            table = _qualified(table_node) if table_node is not None else None
            query = str(query_node).strip().removesuffix(';').strip() if query_node is not None else None
            if query and (not re.match(r'^SELECT\b', query, re.I) or ';' in query):
                raise ValueError("rr:sqlQuery must be one SELECT statement")
            subject_nodes = list(graph.objects(node, RR.subjectMap)) + list(graph.objects(node, RR.subject))
            if len(subject_nodes) != 1:
                raise ValueError("R2RML requires exactly one subject map")
            subject_node = subject_nodes[0]
            subject = self._term(graph, subject_node, "subject", shortcut=(node, RR.subject))
            graph_terms = self._graphs(graph, subject_node)
            classes = tuple(graph.objects(subject_node, RR["class"]))
            pos = []
            for pom in graph.objects(node, RR.predicateObjectMap):
                predicate_nodes = list(graph.objects(pom, RR.predicateMap)) + list(graph.objects(pom, RR.predicate))
                object_nodes = list(graph.objects(pom, RR.objectMap)) + list(graph.objects(pom, RR.object))
                if not predicate_nodes or not object_nodes:
                    raise ValueError("R2RML predicateObjectMap requires predicate and object")
                predicates = tuple(self._term(graph, pred, "predicate", shortcut=(pom, RR.predicate))
                                   for pred in predicate_nodes)
                objects = []
                for obj in object_nodes:
                    parent = _one(graph, obj, RR.parentTriplesMap)
                    if parent is not None:
                        joins = tuple((_identifier(_one(graph, j, RR.child, required=True)),
                                       _identifier(_one(graph, j, RR.parent, required=True)))
                                      for j in graph.objects(obj, RR.joinCondition))
                        objects.append(Object(None, parent, joins))
                    else:
                        objects.append(Object(self._term(graph, obj, "object", shortcut=(pom, RR.object)), None, ()))
                pos.append(PredicateObject(predicates, tuple(objects), self._graphs(graph, pom)))
            columns, types, canonical_columns = self._describe(table, query)
            mapping_obj = Map(node, table, query, subject, classes, graph_terms,
                              tuple(pos), columns, types, canonical_columns)
            self._validate_columns(mapping_obj)
            self.maps[node] = mapping_obj
        if not self.maps:
            raise ValueError("R2RML has no rr:TriplesMap")
        for mapping_obj in self.maps.values():
            for pom in mapping_obj.pos:
                for obj in pom.objects:
                    if obj.parent not in (None, *self.maps):
                        raise ValueError("R2RML parentTriplesMap not found")
                    if obj.parent is not None and not obj.joins:
                        parent = self.maps[obj.parent]
                        if (mapping_obj.table, mapping_obj.query) != (parent.table, parent.query):
                            raise ValueError("missing joinCondition between distinct logical tables")

    def _term(self, graph, node, position, shortcut=None):
        is_shortcut = shortcut is not None and (shortcut[0], shortcut[1], node) in graph
        if is_shortcut:
            kind, value = "constant", node
            term_type = RR.Literal if isinstance(node, Literal) else RR.BlankNode if isinstance(node, BNode) else RR.IRI
            return Term((str(shortcut[0]), str(shortcut[1]), str(node)), kind, value,
                        term_type, self.base)
        choices = [(kind, _one(graph, node, predicate)) for kind, predicate in
                   (("column", RR.column), ("template", RR.template), ("constant", RR.constant))]
        choices = [(kind, value) for kind, value in choices if value is not None]
        if len(choices) != 1:
            raise ValueError("R2RML term map requires one column, template, or constant")
        kind, value = choices[0]
        datatype = _one(graph, node, RR.datatype)
        language = _one(graph, node, RR.language)
        term_type = _one(graph, node, RR.termType)
        if term_type is None:
            term_type = (RR.Literal if position == "object" and kind == "column" else
                         RR.Literal if kind == "constant" and isinstance(value, Literal) else RR.IRI)
        if term_type not in {RR.IRI, RR.BlankNode, RR.Literal}:
            raise ValueError("invalid rr:termType")
        if position in {"subject", "predicate", "graph"} and term_type == RR.Literal:
            raise ValueError(f"R2RML {position} cannot be a literal")
        if position == "predicate" and term_type != RR.IRI:
            raise ValueError("R2RML predicate must be an IRI")
        if position == "graph" and term_type != RR.IRI:
            raise ValueError("R2RML graph must be an IRI")
        if datatype is not None and language is not None:
            raise ValueError("R2RML term cannot have datatype and language")
        if (datatype is not None or language is not None) and term_type != RR.Literal:
            raise ValueError("datatype/language require literal term")
        if language is not None and not _LANGUAGE.fullmatch(str(language)):
            raise ValueError("invalid rr:language")
        if kind == "constant":
            actual = RR.Literal if isinstance(value, Literal) else RR.BlankNode if isinstance(value, BNode) else RR.IRI
            if term_type != actual:
                raise ValueError("rr:termType incompatible with constant")
        return Term(node, kind, value, term_type, self.base,
                    datatype, str(language) if language is not None else None)

    def _graphs(self, graph, node):
        result = []
        for iri in graph.objects(node, RR.graph):
            if iri == RR.defaultGraph:
                result.append(Term((str(node), "defaultGraph"), "constant", iri, RR.IRI, self.base))
            else:
                result.append(Term((str(node), str(iri)), "constant", iri, RR.IRI, self.base))
        result.extend(self._term(graph, term, "graph") for term in graph.objects(node, RR.graphMap))
        return tuple(result)

    def _describe(self, table, query):
        cursor = self.connection.cursor()
        try:
            if query:
                cursor.execute(query + " LIMIT 0")
            else:
                cursor.execute("SELECT * FROM " + ".".join(_quote(n, self.dialect) for n in table) + " LIMIT 0")
            names = tuple(column[0] for column in cursor.description)
            if len(set(names)) != len(names):
                raise ValueError("duplicate SQL query column names")
            types = {}
            if table and self.dialect == "sqlite":
                cursor.execute("PRAGMA table_info(" + _quote(table[-1], self.dialect) + ")")
                types = {row[1]: row[2] for row in cursor.fetchall()}
            canonical = {name.upper() for name in names}
            if table and self.dialect == "sqlite":
                cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table[-1],))
                record = cursor.fetchone()
                if record and record[0]:
                    canonical = set()
                    definition = record[0]
                    body = definition[definition.find('(') + 1:definition.rfind(')')]
                    for match in re.finditer(r'(?:^|,)\s*("(?:[^"]|"")*"|[A-Za-z_][A-Za-z_0-9]*)\s+', body):
                        token = match.group(1)
                        if token.upper() not in {"PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT"}:
                            canonical.add(_canonical_identifier(token))
            return names, types, frozenset(canonical)
        finally:
            cursor.close()

    def _validate_columns(self, mapping):
        available = set(mapping.columns)
        terms = [mapping.subject, *mapping.graphs]
        for pom in mapping.pos:
            terms.extend((*pom.predicates, *pom.graphs))
            terms.extend(obj.term for obj in pom.objects if obj.term is not None)
            for obj in pom.objects:
                if obj.parent is not None:
                    for child, _ in obj.joins:
                        if child not in available:
                            raise ValueError(f"undefined SQL column: {child}")
        for term in terms:
            for reference in term.references():
                column = _identifier(reference)
                if column not in available or (mapping.table and self.dialect == "sqlite"
                                               and _canonical_identifier(reference) not in mapping.canonical_columns):
                    raise ValueError(f"undefined SQL column: {column}")

    def _rows(self, mapping):
        if mapping.query:
            source = "(" + mapping.query + ") AS rr_source"
        else:
            source = ".".join(_quote(n, self.dialect) for n in mapping.table)
        cursor = self.connection.cursor()
        try:
            cursor.execute("SELECT * FROM " + source)
            while batch := cursor.fetchmany(1000):
                for values in batch:
                    yield dict(zip(mapping.columns, values))
        finally:
            cursor.close()

    def dataset(self):
        dataset = Dataset()
        for mapping in self.maps.values():
            for row in self._rows(mapping):
                subject = mapping.subject.evaluate(row, mapping.types)
                if subject is None:
                    continue
                subject_graphs = self._graph_names(mapping.graphs, row, mapping.types)
                for cls in mapping.classes:
                    for graph in subject_graphs:
                        self._add(dataset, (subject, RDF.type, cls), graph)
                for pom in mapping.pos:
                    graphs = self._graph_names(mapping.graphs + pom.graphs, row, mapping.types)
                    for predicate_map in pom.predicates:
                        predicate = predicate_map.evaluate(row, mapping.types)
                        if predicate is None:
                            continue
                        for object_map in pom.objects:
                            for obj in self._objects(mapping, row, object_map):
                                if obj is None:
                                    continue
                                for graph in graphs:
                                    self._add(dataset, (subject, predicate, obj), graph)
        return dataset

    def _objects(self, mapping, row, obj):
        if obj.term is not None:
            yield obj.term.evaluate(row, mapping.types)
            return
        parent = self.maps[obj.parent]
        if not obj.joins:
            yield parent.subject.evaluate(row, parent.types)
            return
        for parent_row in self._rows(parent):
            if all(row.get(child) is not None and row[child] == parent_row.get(parent_col)
                   for child, parent_col in obj.joins):
                yield parent.subject.evaluate(parent_row, parent.types)

    @staticmethod
    def _graph_names(terms, row, types):
        if not terms:
            return (RR.defaultGraph,)
        return tuple(term.evaluate(row, types) for term in terms)

    @staticmethod
    def _add(dataset, triple, graph):
        if graph is None:
            return
        if graph == RR.defaultGraph:
            dataset.default_graph.add(triple)
        else:
            dataset.graph(graph).add(triple)
