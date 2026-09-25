"""Turn a document into candidate triples — without holding an LLM.

Three things happen between a paragraph and a row in the graph: a prompt
is built, a model answers it, and the answer is parsed. trikedb does the
first and the third. The second is one call to whatever model you already
pay for, passed in as `llm`, so this module has no provider, no API key,
no network, and nothing to keep up to date when a vendor renames a
parameter. `pip install trikedb` does not grow by a byte for it.

What makes the first part worth having is that the prompt is built *from
the graph being written into*: the predicates offered are the ones the
ontology declares, and the entities offered are the nodes that already
exist. A model that is handed the vocabulary does not invent
`employed_by` beside `WORKS_AT`, and a model that is handed the node list
does not open a second node for a company already in the file. Both are
mistakes no amount of cleanup afterwards fully repairs — the first loses
the fact, the second splits an entity — and both are cheap to prevent
here, at the only moment the graph's own contents are still in front of
the extractor.

Handing over the whole node vocabulary is possible because the graph is
one small file. It is the first place where being small is a capability
rather than a limit.

Nothing here writes. `parse` returns the same list-of-dicts shape the CSV
and Markdown importers return, which is what `merge.preview` judges and
what `TrikeDB.add` takes, so an extraction is reviewed on exactly the
path a hand-written row is.
"""

from __future__ import annotations

from typing import Callable, Iterable, List, Optional

from . import prompts

#: How many existing node names to offer by default. Past a few hundred the
#: list stops being context and starts being the document; a graph that big
#: should pass `relevant_to` and let retrieval choose.
DEFAULT_NODE_LIMIT = 200


def build_prompt(text: str, *, ontology: Optional[dict] = None,
                 predicate_rules: Optional[dict] = None,
                 nodes: Iterable = (), node_types: Optional[dict] = None,
                 prompt: str = "triples") -> str:
    """The extraction prompt for `text`, constrained by a vocabulary.

    Takes plain data rather than a graph so it can be tested, diffed and
    used against a vocabulary that is not in a graph yet.
    """
    ontology, predicate_rules = ontology or {}, predicate_rules or {}
    return prompts.render(
        prompt,
        predicates=_predicate_block(ontology, predicate_rules),
        nodes=_node_block(_entities(nodes, ontology), node_types or {}),
        text=text,
    )


def prompt_for(db, text: str, *, relevant_to: Optional[str] = None,
               limit: int = DEFAULT_NODE_LIMIT, prompt: str = "triples") -> str:
    """The extraction prompt for `text`, built from `db`'s own vocabulary.

    `relevant_to` narrows the offered nodes by semantic search (the
    [semantic] extra) instead of taking the first `limit` of them — worth
    it once the graph outgrows the prompt. It is the *document* you are
    extracting that it should describe, not the facts you hope to find.
    """
    # Filter before slicing, so `limit` counts entities and not the
    # bookkeeping nodes an OWL declaration leaves behind.
    nodes = _entities(db.nodes(), db.ontology)
    if relevant_to is not None and len(nodes) > limit:
        ranked = [hit.get("node") or hit.get("s") for hit in
                  db.search(relevant_to, k=limit)]
        keep = [n for n in ranked if n in set(nodes)]
        nodes = keep or nodes
    return build_prompt(
        text,
        ontology=db.ontology,
        predicate_rules=db.predicate_rules,
        nodes=nodes[:limit],
        node_types={n: db.nodes_meta.get(n, {}).get("type")
                    for n in nodes[:limit]},
        prompt=prompt,
    )


def parse(output: str) -> List[dict]:
    """Candidate triples from a model's answer. Writes nothing.

    The answer is Markdown tables with s/p/o columns — the format the
    Markdown importer already reads, so a model's output and a table
    typed into a design doc travel the same path.
    """
    from . import importers        # same layer: imported where it is used

    return importers.parse_markdown(_unfence(output))


def extract(text: str, *, llm: Callable[[str], str], db=None, **kwargs) -> List[dict]:
    """Document in, candidate triples out, using the `llm` you pass.

    `llm` takes the prompt and returns the model's text. Any SDK wraps to
    that in three lines; see examples/extract_providers.py. There is no
    default, on purpose — a library that can call a paid API without
    being handed one is a library that can call it by accident.
    """
    if not callable(llm):
        raise TypeError(
            "extract() needs llm=<callable taking the prompt, returning text>; "
            "see examples/extract_providers.py"
        )
    prompt = (prompt_for(db, text, **kwargs) if db is not None
              else build_prompt(text, **kwargs))
    return parse(llm(prompt))


# ----------------------------------------------------------------- blocks


def _predicate_block(ontology: dict, predicate_rules: dict) -> str:
    if not ontology:
        # A graph that declares nothing cannot constrain anything, and
        # saying so beats printing an empty list the model has to guess at.
        return ("This graph declares no predicates yet, so choose them "
                "yourself — but choose a small set and use each one "
                "consistently: SCREAMING_SNAKE_CASE, and the same predicate "
                "for the same kind of fact every time.")
    lines = []
    for name in sorted(ontology):
        shape = _shape(predicate_rules.get(name, {}))
        desc = str(ontology[name] or "").strip()
        lines.append(f"- `{name}`" + (f" — {desc}" if desc else "") +
                     (f"  [{shape}]" if shape else ""))
    return "\n".join(lines)


def _shape(rule: dict) -> str:
    """`domain -> range` for a predicate that declares one."""
    if not rule:
        return ""
    domain, range_ = rule.get("domain"), rule.get("range")
    if not domain and not range_:
        return ""
    return f"{_side(domain)} -> {_side(range_)}"


def _side(want) -> str:
    return "|".join(str(w) for w in want) if want else "any"


def _entities(nodes: Iterable, ontology: dict) -> list:
    """The names worth offering as entities — which is not every node.

    A graph holds more than its subject matter. Declaring a predicate
    functional stores `(WORKS_AT, rdf:type, owl#FunctionalProperty)`, so
    the predicate and an OWL URI both become nodes; whatever else that is
    useful for, it is not a company the document might mention. Offering
    them invites a row whose subject is a predicate, and the guardrail
    below would be right to reject it — better not to suggest it.
    """
    return [name for name in nodes
            if name not in ontology and "://" not in str(name)]


def _node_block(nodes: list, node_types: dict) -> str:
    if not nodes:
        return "The graph is empty — every entity you find is a new one."
    lines = []
    for name in nodes:
        kind = node_types.get(name)
        lines.append(f"- {name}" + (f"  ({kind})" if kind else ""))
    return "\n".join(lines)


def _unfence(text: str) -> str:
    """Drop code-fence lines so a fenced table is read as a table.

    The Markdown importer skips fenced blocks on purpose: a design doc
    that documents "do not write this" used to import exactly that. A
    model's answer is the opposite case — the fence is packaging around
    the only content there is — so here the fences come off first.
    """
    lines = text.splitlines()
    if not any(line.lstrip().startswith(("```", "~~~")) for line in lines):
        return text
    return "\n".join(line for line in lines
                     if not line.lstrip().startswith(("```", "~~~")))
