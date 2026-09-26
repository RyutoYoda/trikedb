"""Import triples from CSV/TSV files and Markdown tables.

Deliberately deterministic — no LLM extraction. A table (in either
format) is a triple source when its header contains s/p/o columns
(aliases: subject/predicate/object). Any other column becomes an edge
attribute. Markdown files may contain any amount of prose around the
tables; non-triple tables are simply ignored, so ordinary design docs
can double as graph sources.

`read_document` answers a different question from the rest of this
module: not "what triples does this file already state" but "what does
this file say", which is where an extraction starts. It is here anyway
because both questions are about turning a file somebody else wrote
into something the graph can look at.
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
    return parse_markdown(Path(path).read_text(encoding="utf-8"))


def parse_markdown(text: str) -> List[dict]:
    """Triples from every s/p/o table in a Markdown string.

    Split out from read_markdown because the tables worth reading do not
    all arrive as files — an extractor hands back the same Markdown a
    design doc contains, and there is no reason for a second parser to
    exist for it.
    """
    lines = text.splitlines()
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


#: WordprocessingML, the only namespace a .docx body uses
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def read_document(path: Union[str, Path]) -> str:
    """A document's text, for handing to an extractor.

    The document people actually have is rarely a Markdown file — it is
    a Word file somebody emailed, or a Google Doc. Google Docs exports
    Markdown directly and needs nothing from us; .docx is a zip with an
    XML document inside it, so reading one costs no dependency either.
    That is the whole reason this is worth having: the format that keeps
    documents out of the graph is not a hard format, it is just one
    nobody bothered to open.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return docx_text(path.read_bytes())
    if suffix == ".doc":
        # Saying "not utf-8" about a binary Word file helps nobody.
        raise ValueError(
            f"{path.name}: .doc is the old binary Word format, which cannot "
            "be read without a converter — save it as .docx"
        )
    return _text(path)


#: A byte order mark is a file saying what it is. Reading one is not guessing.
_BOMS = ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16"),
         (b"\xfe\xff", "utf-16"))


def _text(path: Path) -> str:
    """The file as text, and a sentence worth reading when it is not.

    Encodings are not detected here: anything past a byte order mark is
    a guess, and a guess that lands on the wrong one turns a document
    into plausible nonsense rather than into an error — the one outcome
    worse than refusing. What a Windows-exported .txt gets instead is
    the name of the file, the word UTF-8, and the command that converts
    it, because "'utf-8' codec can't decode byte 0x93 in position 0"
    names neither the file nor anything the reader can act on.
    """
    blob = path.read_bytes()
    for mark, encoding in _BOMS:
        if blob.startswith(mark):
            return blob.decode(encoding)
    try:
        return blob.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"{path.name} is not UTF-8 ({exc.reason} at byte {exc.start}) — "
            f"a text file saved on Windows is usually cp932 or latin-1. "
            f"Convert it first: iconv -f cp932 -t utf-8 {path.name} > utf8.txt"
        ) from None


def docx_text(blob: bytes) -> str:
    """The body of a .docx, as Markdown.

    Markdown rather than flat text because the shape of a document is
    part of what it says: a heading tells a reader — and a model —
    which section a fact came from, and a table's rows are separate
    facts even when the prose around them is one paragraph.

    Comments and footnotes live in other parts of the zip and are not
    read: a remark in the margin is somebody's second thought, and it
    should not become a fact without a person deciding that it is one.
    Deleted text is skipped for the same reason; text marked as an
    insertion is kept, because that is what the document now says.
    """
    # Imported here so that reading a CSV does not also load an XML parser.
    import io
    import zipfile
    from xml.etree import ElementTree

    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            xml = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise ValueError(
            f"not a readable .docx ({type(exc).__name__}: {exc}) — a .docx is "
            "a zip holding word/document.xml"
        ) from None

    body = ElementTree.fromstring(xml).find(f"{_W}body")
    blocks = []
    for node in body if body is not None else []:
        if node.tag == f"{_W}p":
            block = _docx_paragraph(node)
        elif node.tag == f"{_W}tbl":
            block = _docx_table(node)
        else:
            continue
        if not block:
            continue
        # Consecutive bullets are one list, not a run of paragraphs. A blank
        # line between them nearly doubles the length of a document that is
        # mostly a list — minutes, a weekly report — and every line of that
        # is something the model is handed and pays for.
        if blocks and block.startswith("- ") and blocks[-1].startswith("- "):
            blocks[-1] += "\n" + block
        else:
            blocks.append(block)
    return "\n\n".join(blocks) + "\n" if blocks else ""


def _docx_paragraph(node) -> str:
    text = _docx_runs(node)
    if not text:
        return ""
    props = node.find(f"{_W}pPr")
    if props is None:
        return text
    style = props.find(f"{_W}pStyle")
    level = _heading_level(style.get(f"{_W}val", "") if style is not None else "")
    if level:
        return "#" * level + " " + text
    if props.find(f"{_W}numPr") is not None:
        return "- " + text
    return text


def _docx_table(node) -> str:
    """A table as Markdown, with the first row taken as the header.

    Word does not mark which row is the header — `w:tblHeader` is
    optional and usually absent — and a Markdown table has to have one.
    The first row is what a reader treats as the header, so it is what
    this does, rather than dropping the shape entirely.
    """
    rows = []
    for tr in node.findall(f"{_W}tr"):
        cells = []
        for tc in tr.findall(f"{_W}tc"):
            # Paragraphs inside one cell are one cell; runs inside one
            # paragraph split mid-word, which is why they join with nothing.
            parts = [_docx_runs(p) for p in tc.iter(f"{_W}p")]
            cells.append(" ".join(p for p in parts if p).replace("|", "\\|"))
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    out = ["| " + " | ".join(r + [""] * (width - len(r))) + " |" for r in rows]
    out.insert(1, "|" + "|".join(["---"] * width) + "|")
    return "\n".join(out)


def _docx_runs(node) -> str:
    """Every run of text under a node, joined as written.

    `w:t` is the only tag holding text a reader sees; deleted text is
    `w:delText` and is therefore skipped by not being looked for.
    """
    return "".join(t.text or "" for t in node.iter(f"{_W}t"))


def _heading_level(style: str) -> int:
    """The heading depth a paragraph style names, or 0 for body text."""
    name = "".join(style.split()).replace("-", "").lower()
    for prefix in ("heading", "見出し"):
        if name.startswith(prefix) and name[len(prefix):].isdigit():
            return min(int(name[len(prefix):]), 6)
    return 1 if name == "title" else 0


def _is_table_row(line: str) -> bool:
    return line.strip().startswith("|")


def _is_separator(line: str) -> bool:
    text = line.strip()
    if not text.startswith("|") or "-" not in text:
        return False
    return set(text) <= set("|-: \t")


def _cells(line: str) -> List[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]
