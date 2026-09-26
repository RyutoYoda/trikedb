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
import re
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


#: How far into a document to look for its head. A title that has not
#: appeared in forty lines is not a title, it is a sentence in a preamble.
_HEAD_LINES = 40

#: A title is a name, so it stops; a sentence ends. Anything closing with
#: these is prose that happens to be first, and naming a file after it
#: produces `本書は取り込み方針について述べるものである.yaml`.
_ENDS_A_SENTENCE = "。．.!?！？、,:：;；"

#: Openers that address a reader instead of naming a document. A letter,
#: a notice and a forwarded mail all start with one, and without this the
#: head of every such document is 「各位」 — which is not wrong so much as
#: useless: it names nothing, and every letter would get the same filename.
_SALUTATIONS = frozenset((
    "各位", "関係者各位", "社員各位", "皆様", "皆さま", "皆さん",
    "お疲れ様です", "お疲れさまです", "おつかれさまです",
    "拝啓", "謹啓", "前略", "こんにちは", "はじめまして",
))
#: The same thing in English, where the reader's name follows the opener.
_ADDRESSES = ("dear ", "hi ", "hello ", "to whom it may concern")

#: `====` or `----` under a line is what makes it a Setext heading.
_SETEXT = re.compile(r"^(=+|-+)$")

#: A forwarded mail arrives with its headers intact, and `From:` is not
#: a title even though it is the first line.
_MAIL_HEADER = re.compile(r"(?i)(from|to|subject|date|cc|sent)\s*:")

#: Everything that is not a letter, a digit or an underscore, which is the
#: separator in a filename as much as a space is. Taking the whole class at
#: once — rather than only the characters Windows forbids — is what keeps
#: 「Q3 — 取り込み見直し」 from becoming `q3-—-torikomi.yaml`, and it removes
#: what is illegal or would redirect the write (`/`, `:`, a control byte) on
#: the way past. `\w` is Unicode here, so 漢字 and かな are letters and stay.
_NOT_A_NAME = re.compile(r"[^\w]+")


def document_title(text: str) -> str:
    """The head of a document — what it is called, not something it says.

    This exists because of the one mistake extraction makes that nothing
    downstream can repair: the title of a document is the most prominent
    string in it, so a model hands it back as an entity, and the graph
    grows a node for a *file* sitting beside the people and systems the
    file is about. The head is not a fact. It is the name of the
    container the facts go into, which is why the caller turns it into a
    filename (`graph_filename`) and the prompt is told to leave it alone.

    A heading wins, because a heading is the document saying which line
    is its name rather than us guessing. Failing that, a short opening
    line that does not end like a sentence is a title; a paragraph is
    not, and an empty answer is the honest one — the caller still has
    the file's own name to fall back on.
    """
    # A byte order mark in front of `# heading` would hide the heading.
    # `read_document` has already eaten it, but this takes plain text from
    # anywhere, and a leading zero-width space costs one call to strip.
    lines = text.lstrip("\ufeff\u200b").splitlines()
    # Three formats state their own title outright, and each of them puts
    # something else on line one — so ask them before guessing.
    for stated in (_front_matter_title, _mail_subject):
        found = stated(lines)
        if found:
            return found
    lines = lines[:_HEAD_LINES]
    fenced = False
    first = first_at = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced or not stripped:
            continue
        heading = re.match(r"#{1,6}\s+(.*)", stripped)
        if heading:
            return heading.group(1).strip().rstrip("#").strip()
        if first is None:
            first, first_at = stripped, i
    if first is None:
        return ""
    # Setext: the line under it is what makes it a heading, and a document
    # written this way has no `#` anywhere for the branch above to find.
    if first_at + 1 < len(lines) and _SETEXT.match(lines[first_at + 1].strip()):
        return first
    if len(first) > 80 or first[-1] in _ENDS_A_SENTENCE:
        return ""
    # A bullet, a table row or a horizontal rule is structure, not a name.
    if first[0] in "-*+|>=_":
        return ""
    # Only the guessed path is filtered. A document that put 「はじめに」
    # behind a `#` said it was a heading, and second-guessing a document
    # about its own structure is how a detector starts being wrong on the
    # documents it was working on.
    plain = first.rstrip("、。,.!！:：").strip()
    if plain in _SALUTATIONS or plain.lower().startswith(_ADDRESSES):
        return ""
    return first


def _front_matter_title(lines: list) -> str:
    """`title:` out of YAML front matter — Obsidian, Hugo, Notion exports.

    The front matter is the document being explicit about its own name,
    which beats every heuristic below it, and without this the first
    thing a guess lands on is the `---` fence.
    """
    if not lines or lines[0].strip() not in ("---", "+++"):
        return ""
    fence = lines[0].strip()
    for line in lines[1:_HEAD_LINES]:
        if line.strip() == fence:
            return ""
        match = re.match(r'(?i)title\s*[:=]\s*(.*)', line.strip())
        if match:
            return match.group(1).strip().strip("\"'")
    return ""


def _mail_subject(lines: list) -> str:
    """The `Subject:` of a forwarded mail, which arrives headers and all.

    Without this the head of every mail is whoever sent it.
    """
    if not lines or not _MAIL_HEADER.match(lines[0]):
        return ""
    for line in lines[:_HEAD_LINES]:
        if not line.strip():
            return ""
        if line.lower().startswith("subject:"):
            return line.split(":", 1)[1].strip()
    return ""


def graph_filename(title: str) -> str:
    """The YAML file a document's head becomes. `""` when it has no head.

    Non-ASCII is kept. A graph of Japanese documents named
    `jinji-idou-no-oshirase.yaml` is a graph nobody can find a file
    in, and every filesystem trikedb runs on has handled these bytes for
    twenty years — the characters worth removing are the ones that are
    illegal or that would redirect the write, not the ones that are
    foreign. Everything else — spaces, dashes, punctuation — is a
    separator and collapses to a single hyphen.
    """
    name = "-".join(_NOT_A_NAME.sub(" ", title).split()).strip("-_").lower()
    return f"{name[:60].rstrip('-_')}.yaml" if name else ""


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
    text = _docx_runs(node).strip()
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
            # Paragraphs inside one cell are one cell, and a Markdown row
            # is one line, so whatever shape the cell had collapses here.
            # Runs inside one paragraph split mid-word, which is why the
            # runs themselves join with nothing.
            text = " ".join(" ".join(_docx_runs(p) for p in tc.iter(f"{_W}p"))
                            .split())
            cells.append(text.replace("|", "\\|"))
            # A merged cell covers the columns it spans. Written as one
            # cell and padded at the end of the row, every value after it
            # slides left and ends up under someone else's heading — the
            # one way a table can be wrong without looking wrong.
            cells += [""] * (_span(tc) - 1)
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    out = ["| " + " | ".join(r + [""] * (width - len(r))) + " |" for r in rows]
    out.insert(1, "|" + "|".join(["---"] * width) + "|")
    return "\n".join(out)


def _span(cell) -> int:
    """How many columns a table cell covers (`w:gridSpan`), at least one."""
    grid = cell.find(f"{_W}tcPr/{_W}gridSpan")
    try:
        return max(1, int(grid.get(f"{_W}val"))) if grid is not None else 1
    except (TypeError, ValueError):
        return 1


def _docx_runs(node) -> str:
    """Every run of text under a node, joined as written.

    `w:t` is the only tag holding text a reader sees; deleted text is
    `w:delText` and is therefore skipped by not being looked for.

    A break and a tab hold no text but are not nothing: they are where
    the author ended one line and started another. Joining across them
    welds the last word of one line to the first of the next, which is
    both unreadable and a fact the document never stated.
    """
    out = []
    for element in node.iter():
        if element.tag == f"{_W}t":
            out.append(element.text or "")
        elif element.tag == f"{_W}br":
            out.append("\n")
        elif element.tag == f"{_W}tab":
            out.append(" ")
    return "".join(out)


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
