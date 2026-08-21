"""Import triples from CSV/TSV files and Markdown tables.

Deliberately deterministic — no LLM extraction. A table (in either
format) is a triple source when its header contains s/p/o columns
(aliases: subject/predicate/object). Any other column becomes an edge
attribute. Markdown files may contain any amount of prose around the
tables; non-triple tables are simply ignored, so ordinary design docs
can double as graph sources.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import List, Optional, Union

_ALIASES = {
    "s": "s", "subject": "s",
    "p": "p", "predicate": "p", "pred": "p",
    "o": "o", "object": "o", "obj": "o",
}


def _coerce(value):
    if isinstance(value, str):
        text = value.strip()
        if text.lower() == "true":
            return True
        if text.lower() == "false":
            return False
        return text
    return value


def _rows_to_triples(header: List[str], rows: List[List[str]]) -> Optional[List[dict]]:
    """Map table rows to triple dicts, or None if the header lacks s/p/o."""
    cols = [_ALIASES.get(h.strip().lower(), h.strip()) for h in header]
    if not {"s", "p", "o"} <= set(cols):
        return None
    triples = []
    for row in rows:
        d = {}
        for col, val in zip(cols, row):
            # s/p/o name things and stay text. Coercing them turned a node
            # actually called "false" into the boolean False, which the store
            # then wrote back as the string "False" — a silent rename.
            val = val.strip() if col in ("s", "p", "o") and isinstance(val, str) \
                else _coerce(val)
            if val == "" or val is None:
                continue
            d[col] = val
        if {"s", "p", "o"} <= set(d):
            triples.append(d)
    return triples


def read_csv(path: Union[str, Path]) -> List[dict]:
    """Read triples from a CSV (or TSV) file with an s/p/o header."""
    path = Path(path)
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    with open(path, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.reader(f, delimiter=delimiter) if any(c.strip() for c in r)]
    if not rows:
        return []
    triples = _rows_to_triples(rows[0], rows[1:])
    if triples is None:
        raise ValueError(
            f"{path.name}: header must include s/p/o (or subject/predicate/object) columns"
        )
    return triples


def read_markdown(path: Union[str, Path]) -> List[dict]:
    """Read triples from every s/p/o table in a Markdown document."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    triples: List[dict] = []
    i = 0
    fenced = False
    while i < len(lines):
        stripped = lines[i].lstrip()
        if stripped.startswith(("```", "~~~")):
            # A fenced block is an example, not data. Documenting "do not
            # write this" used to import exactly that.
            fenced = not fenced
            i += 1
            continue
        if fenced:
            i += 1
            continue
        if _is_table_row(lines[i]) and i + 1 < len(lines) and _is_separator(lines[i + 1]):
            header = _cells(lines[i])
            i += 2
            body = []
            while i < len(lines) and _is_table_row(lines[i]):
                body.append(_cells(lines[i]))
                i += 1
            found = _rows_to_triples(header, body)
            if found:
                triples.extend(found)
        else:
            i += 1
    return triples


def _is_table_row(line: str) -> bool:
    return line.strip().startswith("|")


def _is_separator(line: str) -> bool:
    text = line.strip()
    if not text.startswith("|") or "-" not in text:
        return False
    return set(text) <= set("|-: \t")


def _cells(line: str) -> List[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]
