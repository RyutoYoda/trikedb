"""Optional semantic-web layers: OWL characteristics and SHACL validation.

This module owns everything that goes beyond plain triples — the core
store (db.py) stays installable and useful without pyshacl or owlrl.
New reasoning/validation capabilities belong here, exposed to users as
thin delegating methods on TrikeDB.
"""

from __future__ import annotations

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OWL_CHARACTERISTICS = {
    "transitive": "http://www.w3.org/2002/07/owl#TransitiveProperty",
    "symmetric": "http://www.w3.org/2002/07/owl#SymmetricProperty",
    "functional": "http://www.w3.org/2002/07/owl#FunctionalProperty",
}
OWL_INVERSE_OF = "http://www.w3.org/2002/07/owl#inverseOf"

# RDFS relations declared as `declare(x, "<kind>:<other>")`. subclass_of and
# subproperty_of relate two of the same kind; domain/range relate a predicate
# to a class. All stored as ordinary, reviewable triples with an rdfs: predicate.
RDFS_RELATIONS = {
    "subclass_of": RDFS + "subClassOf",
    "subproperty_of": RDFS + "subPropertyOf",
    "domain": RDFS + "domain",
    "range": RDFS + "range",
}
# rdf/rdfs predicates whose inferences are meaningful user facts (classification
# and hierarchy) rather than rdf/owl bookkeeping — surfaced by infer().
SURFACEABLE_PREDICATES = {RDF_TYPE, RDFS + "subClassOf", RDFS + "subPropertyOf"}


def declare(db, predicate: str, characteristic: str):
    """Store an RDFS/OWL semantic for a predicate (or class) as a reviewable triple.

    characteristic is one of:
      * an OWL property characteristic: 'transitive', 'symmetric', 'functional'
      * 'inverse_of:<PREDICATE>'
      * an RDFS relation: 'subclass_of:<CLASS>', 'subproperty_of:<PREDICATE>',
        'domain:<CLASS>', 'range:<CLASS>'

    infer() then materializes the entailments (transitive/inverse edges,
    subClassOf/subPropertyOf hierarchy, domain/range typing).
    """
    kind, sep, other = characteristic.partition(":")
    if sep:
        if kind == "inverse_of":
            return db.add(predicate, OWL_INVERSE_OF, other)
        if kind in RDFS_RELATIONS:
            return db.add(predicate, RDFS_RELATIONS[kind], other)
    try:
        uri = OWL_CHARACTERISTICS[characteristic]
    except KeyError:
        known = sorted(OWL_CHARACTERISTICS) + [f"{k}:<OTHER>" for k in
                                               ["inverse_of", *RDFS_RELATIONS]]
        raise ValueError(
            f"unknown characteristic {characteristic!r} (known: {known})"
        ) from None
    return db.add(predicate, RDF_TYPE, uri)


def infer(db, apply: bool = False, base: str = "urn:trikedb:") -> list:
    """Materialize OWL-RL inferences; see TrikeDB.infer for the contract."""
    try:
        from owlrl import DeductiveClosure, OWLRL_Semantics
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "OWL inference requires owlrl - pip install 'trikedb[owl]'"
        ) from exc
    from rdflib import Literal, URIRef

    from .db import _shorten

    g = db.to_rdflib(base, node_props=False, edge_attrs=False)
    before = set(g)
    DeductiveClosure(OWLRL_Semantics).expand(g)
    existing = {t.spo() for t in db}
    new = []
    for s, p, o in set(g) - before:
        # Keep only facts *about the user's own resources*. The OWL-RL closure
        # also emits mountains of rdf/owl bookkeeping (x rdf:type owl:Thing,
        # x subClassOf rdfs:Resource, bnodes …) — those have a non-base subject
        # or object and are dropped.
        if not (isinstance(s, URIRef) and str(s).startswith(base)):
            continue
        p_text = str(p)
        p_is_base = p_text.startswith(base)
        # predicate must be one of the user's own, or an RDFS classification /
        # hierarchy predicate (rdf:type, rdfs:subClassOf, rdfs:subPropertyOf)
        if not (p_is_base or p_text in SURFACEABLE_PREDICATES):
            continue
        if isinstance(o, Literal):
            o_out = str(o)
        elif isinstance(o, URIRef) and str(o).startswith(base):
            o_out = _shorten(o, base)
        else:
            continue  # object is rdfs:Resource / owl:Thing / a bnode → noise
        s_out = _shorten(s, base)
        if s_out == o_out and not p_is_base:
            continue  # reflexive classification noise (X subClassOf X, X type X)
        p_out = _shorten(p, base) if p_is_base else p_text
        row = (s_out, p_out, o_out)
        if row not in existing:
            new.append(row)
    new = sorted(set(new))
    if apply:
        for s, p, o in new:
            db.add(s, p, o, inferred=True)
    return new


def validate(db, shapes, base: str = "urn:trikedb:"):
    """SHACL-validate the graph; see TrikeDB.validate for the contract."""
    try:
        from pyshacl import validate as shacl_validate
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "SHACL validation requires pyshacl - pip install 'trikedb[shacl]'"
        ) from exc
    from rdflib import Graph

    sg = Graph()
    text = str(shapes)
    if "\n" in text or text.lstrip().startswith("@prefix"):
        sg.parse(data=text, format="turtle")
    else:
        sg.parse(text, format="turtle")
    conforms, _, report = shacl_validate(
        db.to_rdflib(base, edge_attrs=False), shacl_graph=sg, inference="none"
    )
    return bool(conforms), str(report)
