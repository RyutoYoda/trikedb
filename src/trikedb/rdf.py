"""The RDF face of the store: rdflib graphs, SPARQL reads and updates.

trikedb keeps its own list of triples and projects that list into RDF on
demand, rather than storing RDF and reading it back. Everything that
knows what an IRI is lives here, so the store itself never has to.

Reads go to Oxigraph when it is installed and fall back to rdflib when it
is not; updates always go through rdflib, which is the one that has them.
Free functions taking the store, with thin delegating methods on TrikeDB
for the three that are public: to_rdflib, sparql and update.
"""

from __future__ import annotations

import re

from .model import OntologyError, Triple, _iri_node, _shorten


def to_rdflib(db, base: str = "urn:trikedb:", node_props: bool = True,
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
    from rdflib import Graph
    g = Graph()
    g.bind("t", base)
    for triple in statements(db, base, node_props, edge_attrs):
        g.add(triple)
    return g


def statements(db, base: str, node_props: bool = True,
                edge_attrs: bool = True):
    """One typed RDF projection shared by every exporter and engine."""
    from rdflib import BNode, Literal, RDF, URIRef
    # User blank nodes and synthetic statement nodes must not collide.
    used = {str(term) for t in db._triples for term in t.as_rdf(base)
            if isinstance(term, BNode)}
    for i, t in enumerate(db._triples):
        s, p, o = t.as_rdf(base)
        yield s, p, o
        if edge_attrs and t.attrs:
            name = f"trikedb-statement-{i}"
            while name in used:
                name += "-"
            used.add(name)
            st = BNode(name)
            yield st, RDF.type, RDF.Statement
            yield st, RDF.subject, s
            yield st, RDF.predicate, p
            yield st, RDF.object, o
            for key, value in t.attrs.items():
                yield st, URIRef(_iri_node(str(key), base)), Literal(value)
    if node_props:
        for name, props in db.nodes_meta.items():
            for key, value in props.items():
                yield URIRef(_iri_node(name, base)), URIRef(_iri_node(str(key), base)), Literal(value)


def oxigraph_store(db, base: str):
    """Load the shared, typed RDF projection into Oxigraph."""
    from pyoxigraph import Store, RdfFormat
    store = Store()
    data = db.to_rdflib(base).serialize(format="nt")
    store.load(input=data, format=RdfFormat.N_TRIPLES)
    return store


def query_graph(db, base: str, engine: str = "rdflib"):
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
    if db._rdf_cache is not None and db._rdf_cache[0] == key:
        return db._rdf_cache[1]
    graph = (oxigraph_store(db, base) if engine == "oxigraph"
             else db.to_rdflib(base))
    db._rdf_cache = (key, graph)
    return graph


def sparql(db, query: str, base: str = "urn:trikedb:"):
    """Run real SPARQL 1.1 (via rdflib) against the graph — reads and writes.

    The prefix `t:` is bound to `base`, so predicates are written
    `t:PROVIDES`. SELECT returns a list of {var: value} dicts with URIs
    shortened back to plain names; ASK returns a bool. Update forms
    (INSERT DATA, DELETE WHERE, ...) mutate the store and return the
    change in triple count.

    >>> db.sparql("SELECT ?v ?t WHERE { ?v t:PROVIDES ?j . ?j t:INGESTS_TO ?t }")
    >>> db.sparql("INSERT DATA { t:figly t:PROVIDES t:figly-export-job }")
    """
    if not isinstance(query, str):
        raise TypeError("SPARQL query must be a string")
    # Parse only ambiguous forms. Common read queries keep their fast path.
    import re
    leading = re.sub(r"(?m)^\s*#[^\n]*(?:\n|$)", "", query).lstrip()
    word = re.match(r"[A-Za-z]+", leading)
    first = word.group().upper() if word else ""
    if first not in {"SELECT", "ASK", "CONSTRUCT", "DESCRIBE"}:
        from rdflib.plugins.sparql.parser import parseQuery, parseUpdate
        try:
            parseUpdate(query)
        except Exception:
            parseQuery(query)  # report the read parser's actual syntax error
        else:
            return db.update(query, base=base)

    prefixed = (
        f"PREFIX t: <{base}>\n"
        "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n" + query
    )
    if db.sparql_engine == "oxigraph":
        rows = query_oxigraph(db, prefixed, base)
        if rows is not NotImplemented:
            return rows
        # a CONSTRUCT or DESCRIBE: rdflib owns those, unchanged

    result = query_graph(db, base).query(prefixed)
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


def query_oxigraph(db, prefixed: str, base: str):
    """Answer a SELECT or ASK through oxigraph, in the same shape.

    Returns ``NotImplemented`` for query forms this path does not cover
    (CONSTRUCT, DESCRIBE) so the caller can fall back rather than this
    having to parse the query to find out which form it is.
    """
    result = query_graph(db, base, "oxigraph").query(prefixed)
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


def update(db, query: str, base: str = "urn:trikedb:") -> int:
    """Apply a SPARQL 1.1 Update and sync the result back to the store.

    Attributes of surviving triples are preserved; triples inserted via
    SPARQL start with no attributes. The ontology (if any) is enforced
    on inserted predicates. Returns the net change in triple count.
    """
    db._guard_writable()
    from rdflib.plugins.sparql.parser import parseUpdate
    from rdflib.plugins.sparql.algebra import translateUpdate
    prefixed = (f"PREFIX t: <{base}>\n"
                "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n" + query)
    parsed = translateUpdate(parseUpdate(prefixed))
    # This is a single default graph, not an RDF dataset. Reject dataset
    # operations explicitly instead of accepting and silently losing them.
    for operation in parsed.algebra:
        if operation.name not in {"InsertData", "DeleteData", "DeleteWhere", "Modify", "Clear", "Drop"}:
            raise ValueError("only default-graph INSERT/DELETE/CLEAR/DROP updates are supported")
        if operation.get("withClause") is not None and "withClause" in operation:
            raise ValueError("named graphs and WITH are not supported")
        if "using" in operation:
            raise ValueError("USING datasets are not supported")
        if operation.name in {"Clear", "Drop"} and operation.get("graphiri") != "DEFAULT":
            raise ValueError("only the DEFAULT graph can be cleared")
        for clause in (operation, operation.get("insert"), operation.get("delete")):
            if isinstance(clause, dict) and clause.get("quads") and "quads" in clause:
                raise ValueError("named graphs are not supported")
    g = db.to_rdflib(base)
    before_full = set(g)
    facts = {t.as_rdf(base) for t in db._triples}
    g.update(parsed)
    after_full = set(g)
    # Synthetic metadata is readable in WHERE but not writable through RDF.
    if (before_full - after_full) - facts:
        raise ValueError("update deletes projected metadata; use set_node or edge attributes")
    wanted = (facts - (before_full - after_full)) | (after_full - before_full)
    kept = [t for t in db._triples if t.as_rdf(base) in wanted]
    existing = {t.as_rdf(base) for t in kept}
    for triple in sorted(wanted - existing, key=lambda row: tuple(t.n3() for t in row)):
        row = Triple.from_rdf(*triple, base=base)
        if db.ontology and row.p not in db.ontology and not row.p.startswith(("http://", "https://")):
            raise OntologyError(f"update inserts predicate {row.p!r} not in the ontology")
        db._check_link(row.s, row.p, row.o)
        kept.append(row)
    before = len(db._triples)
    if wanted != facts:
        db._triples = kept
        db._index = db._pidx = db._eidx = None
        db._autosave()
    return len(db._triples) - before
