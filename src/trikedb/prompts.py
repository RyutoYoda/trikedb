"""Extraction prompts, as data rather than code.

A prompt is the part of an extractor that actually changes when the
accuracy changes, so it is kept where a change to it shows up as a
reviewable diff — beside the templates, not spliced into a function.

Every prompt here is built from the graph it will write into: the
predicates it may use are the predicates the ontology declares, and the
entities it is told to reuse are the nodes the graph already has. That
is the whole idea. An extractor that guesses a vocabulary and is
corrected afterwards loses the facts it guessed wrong; one that is given
the vocabulary up front never spends them.

Fields are substituted by literal `{{NAME}}` replacement, not `format()`,
because the document being extracted is pasted in whole and documents
contain braces.
"""

from __future__ import annotations

#: name -> (one-line description, body)
PROMPTS: dict = {}


def _prompt(name: str, summary: str, body: str) -> None:
    PROMPTS[name] = (summary, body.strip() + "\n")


def names() -> list:
    return sorted(PROMPTS)


def summary(name: str) -> str:
    return _get(name)[0]


def _get(name: str) -> tuple:
    try:
        return PROMPTS[name]
    except KeyError:
        raise ValueError(
            f"unknown prompt {name!r} (known: {', '.join(names())})"
        ) from None


def render(name: str, **fields) -> str:
    """Fill a prompt's `{{FIELD}}` slots. Unknown slots are left alone."""
    body = _get(name)[1]
    for key, value in fields.items():
        body = body.replace("{{" + key.upper() + "}}", str(value))
    return body


_prompt(
    "triples",
    "extract triples constrained to a declared ontology",
    """
You turn a document into subject-predicate-object triples for a knowledge
graph. Accuracy matters more than coverage: a fact you leave out costs a
line, a fact you invent costs the reader's trust in every other line.

## Predicates you may use

{{PREDICATES}}

Use no other predicate. Do not invent a spelling, a synonym, or a
variation in case. If something the document says does not fit one of the
predicates above, leave it out.

## Entities that already exist in the graph

{{NODES}}

If something in the document is one of these, write it with the spelling
listed above, character for character. Introducing a second name for a
thing that is already listed ("Acme Corp." when the graph says "Acme") is
the single most expensive mistake you can make here, because nothing
downstream can tell that the two are one thing.

For anything genuinely new, take the fullest name the document gives it
and drop only the legal form — "株式会社アクメ" and "グロベックス社" become
"アクメ" and "グロベックス"; "Acme Inc." becomes "Acme". Keep everything
that identifies the thing: a person introduced as "田中 亮" and later
called "田中" is "田中 亮" in every row, because a surname alone will
collide with the next 田中 the graph meets. Use that one name in every
row you write.

## What counts as a fact

- Extract what the document states. Do not infer, conclude, or combine
  facts into a new one.
- Resolve references before you write: "the company", "同社", "it", "they"
  must come out as the entity they refer to, never as a pronoun.
- One row per fact. If the same fact is stated twice, write it once.
- If the document gives a date for a fact, put it in the `at` column as
  YYYY-MM-DD. Leave `at` empty otherwise — do not guess a date.
- `prov` is a short verbatim quote from the document (under twenty words)
  that supports the row. Every row needs one. If you cannot quote a
  passage that says it, you are inferring — drop the row.

## The document is not one of the facts

A document has a name, headings, sections, a revision history and
sentences about itself. None of that is a fact about the world — it is
the paper the facts are written on. It is also the most prominent text
in the file, which is why it gets extracted, and the row it produces is
the one kind nothing downstream can repair: the graph grows a node for a
*file*, standing among the people and systems the file is about, and no
later pass can tell which is which.

So no row may take the document's title, a heading, a section number, a
figure or table caption, 「本書」, 「当資料」, "this document" or the
file's name as its subject or as its object. Drop the row entirely — do
not rewrite it onto some other subject.

Events are decided by the same question. An event is something that
happened in the world, not something that happened to the paper:
「2026-09-20 に権限を剥奪した」 is an event, and
「改訂履歴 1.2 2026-04-01 初版」 is the document keeping track of itself.
A revision table looks exactly like an event table and is not one.

{{CONTAINER}}

## Output

A single Markdown table and nothing else. No preamble, no explanation, no
code fence. Exactly these columns, in this order:

| s | p | o | at | prov |
|---|---|---|---|---|

If the document contains no extractable facts, output the header row alone.

## Document

{{TEXT}}
""",
)

# The baseline the constrained prompt is measured against, kept here
# rather than in the eval so that "what we compared ourselves to" is a
# reviewable line in the repository and not a string in a script someone
# can quietly improve until the comparison flatters us. It asks for the
# same output shape, and nothing else: no predicate list, no node list,
# no rule about quoting. Every difference `evals/score.py` reports comes
# from what the graph contributed to the prompt.
_prompt(
    "triples-naive",
    "the unconstrained baseline: extract triples with no vocabulary",
    """
Extract subject-predicate-object triples from the document below.

Output a Markdown table with the columns `| s | p | o | at | prov |`.

## Document

{{TEXT}}
""",
)
