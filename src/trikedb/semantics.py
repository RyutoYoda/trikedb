"""Optional semantic-web layers: OWL characteristics and SHACL validation.

This module owns everything that goes beyond plain triples — the core
store (db.py) stays installable and useful without pyshacl or owlrl.
New reasoning/validation capabilities belong here, exposed to users as
thin delegating methods on TrikeDB.
"""

from __future__ import annotations

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
OWL_CHARACTERISTICS = {
    "transitive": "http://www.w3.org/2002/07/owl#TransitiveProperty",
    "symmetric": "http://www.w3.org/2002/07/owl#SymmetricProperty",
    "functional": "http://www.w3.org/2002/07/owl#FunctionalProperty",
}
OWL_INVERSE_OF = "http://www.w3.org/2002/07/owl#inverseOf"


def declare(db, predicate: str, characteristic: str):
    """Store an OWL characteristic for a predicate as a reviewable triple."""
    if characteristic.startswith("inverse_of:"):
        other = characteristic.split(":", 1)[1]
        return db.add(predicate, OWL_INVERSE_OF, other)
    try:
        uri = OWL_CHARACTERISTICS[characteristic]
    except KeyError:
        raise ValueError(
            f"unknown characteristic {characteristic!r} "
            f"(known: {sorted(OWL_CHARACTERISTICS)} or 'inverse_of:<PRED>')"
        ) from None
    return db.add(predicate, RDF_TYPE, uri)


def infer(db, apply: bool = False, base: str = "urn:trikedb:") -> list:
    """Materialize OWL-RL inferences; see TrikeDB.infer for the contract."""
    try:
        from owlrl import DeductiveClosure, OWLRL_Semantics
    except ImportError:  # pragma: no cover
        raise ImportError(
            "OWL inference requires owlrl — pip install 'trikedb[owl]'"
        ) from None
    from rdflib import Literal

    from .db import _shorten

    g = db.to_rdflib(base, node_props=False, edge_attrs=False)
    before = set(g)
    DeductiveClosure(OWLRL_Semantics).expand(g)
    existing = {t.spo() for t in db}
    new = []
    for s, p, o in set(g) - before:
        row = []
        for term in (s, p, o):
            if isinstance(term, Literal):
                row.append(str(term))
                continue
            text = str(term)
            if not text.startswith(base):
                row = None  # axiomatic rdf/owl vocabulary noise or bnode
                break
            row.append(_shorten(term, base))
        if row and tuple(row) not in existing:
            new.append(tuple(row))
    new.sort()
    if apply:
        for s, p, o in new:
            db.add(s, p, o, inferred=True)
    return new


def validate(db, shapes, base: str = "urn:trikedb:"):
    """SHACL-validate the graph; see TrikeDB.validate for the contract."""
    try:
        from pyshacl import validate as shacl_validate
    except ImportError:  # pragma: no cover
        raise ImportError(
            "SHACL validation requires pyshacl — pip install 'trikedb[shacl]'"
        ) from None
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
