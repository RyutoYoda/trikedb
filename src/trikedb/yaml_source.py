"""Preserve human-authored YAML layout and comments while updating values."""

from __future__ import annotations

import json
import re
from io import StringIO

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .model import TIME_ATTRS, _plain


def _roundtrip_yaml() -> YAML:
    """Match PyYAML's YAML 1.1 booleans when preserving source formatting."""
    parser = YAML()
    parser.preserve_quotes = True
    parser.resolver.add_implicit_resolver(
        "tag:yaml.org,2002:bool",
        re.compile(r"^(?:yes|no|on|off|true|false)$", re.IGNORECASE),
        list("yYnNoOtTfF"),
    )
    return parser


def _sync_authored_workflow(original, desired: dict) -> None:
    """Patch the round-trip YAML tree without erasing comments on edited steps."""
    old_steps = {str(step.get("id")): step for step in original.get("steps", [])
                 if isinstance(step, dict)}
    new_steps = []
    for index, step in enumerate(desired["steps"], 1):
        old = old_steps.get(step["id"])
        if old is None:
            new_steps.append(step)
            continue
        wanted = dict(step)
        if old.get("order") == index and "order" not in wanted:
            wanted["order"] = index
        if "next" in wanted and old.get("next") == wanted["next"][0] and len(wanted["next"]) == 1:
            wanted["next"] = old["next"]
        for key in list(old):
            if key not in wanted:
                del old[key]
        for key, value in wanted.items():
            if isinstance(old.get(key), dict) and isinstance(value, dict):
                _sync_mapping(old[key], value)
            elif _plain(old.get(key)) != _plain(value):
                old[key] = value
        new_steps.append(old)
    old_sequence = original.get("steps")
    if old_sequence is not None:
        _replace_sequence(old_sequence, new_steps)
    else:
        original["steps"] = new_steps
    for key in list(original):
        if key != "steps" and key not in desired:
            del original[key]
    for key, value in desired.items():
        if key == "steps":
            continue
        if isinstance(original.get(key), dict) and isinstance(value, dict):
            _sync_mapping(original[key], value)
        elif _plain(original.get(key)) != _plain(value):
            original[key] = value


def _sync_mapping(original, desired: dict) -> None:
    """Apply value changes while leaving comments on unchanged YAML keys."""
    for key in list(original):
        if key not in desired:
            del original[key]
    for key, value in desired.items():
        if key not in original:
            original[key] = value
        elif isinstance(original[key], dict) and isinstance(value, dict):
            _sync_mapping(original[key], value)
        elif _plain(original[key]) != _plain(value):
            original[key] = value


def _replace_sequence(original, updated: list) -> None:
    """Keep each item's YAML comment attached when list positions change."""
    comments = {id(item): original.ca.items.get(index)
                for index, item in enumerate(original)
                if hasattr(original, "ca") and index in original.ca.items}
    original[:] = updated
    if hasattr(original, "ca"):
        original.ca.items.clear()
        for index, item in enumerate(updated):
            if id(item) in comments:
                original.ca.items[index] = comments[id(item)]


def _sync_triples(original, desired: list[dict]) -> None:
    """Keep comments attached to matching triples when a graph is edited."""
    def identity(item):
        event_time = next((str(item[key]) for key in TIME_ATTRS if key in item), "")
        rdf_terms = json.dumps(_plain(item.get("rdf_terms", {})), sort_keys=True)
        return (str(item.get("s")), str(item.get("p")), str(item.get("o")),
                event_time, rdf_terms)

    by_identity = {}
    for item in original:
        if isinstance(item, dict):
            by_identity.setdefault(identity(item), []).append(item)
    updated = []
    for item in desired:
        candidates = by_identity.get(identity(item), [])
        old = candidates.pop(0) if candidates else None
        if old is not None:
            _sync_mapping(old, item)
        updated.append(old if old is not None else item)
    _replace_sequence(original, updated)


def parse_source(document):
    """Parse formatting metadata only when a writer needs it."""
    return _roundtrip_yaml().load(document) if isinstance(document, str) else document


def patch_source_entries(original_text: str, source, original_values: dict) -> str | None:
    """Replace edited mapping entries while retaining unrelated source bytes."""
    if set(source) != set(original_values):
        return None
    if any(_plain(value) != original_values[key]
           for key, value in source.items() if key not in {"nodes", "workflows"}):
        return None
    lines = original_text.splitlines(keepends=True)
    patches = []
    for section in ("nodes", "workflows"):
        if section not in source:
            continue
        entries = source[section]
        old_entries = original_values[section]
        if not isinstance(entries, dict) or set(entries) != set(old_entries):
            return None
        keys = list(entries)
        changed = [key for key in keys if _plain(entries[key]) != old_entries[key]]
        if any(attached_comment(entries, key) for key in changed):
            return None
        section_line = source.lc.key(section)[0]
        later_sections = [source.lc.key(key)[0] for key in source
                          if source.lc.key(key)[0] > section_line]
        section_end = min(later_sections, default=len(lines))
        for key in changed:
            index = keys.index(key)
            line, column = entries.lc.key(key)
            next_line = (entries.lc.key(keys[index + 1])[0]
                         if index + 1 < len(keys) else section_end)
            if section == "workflows":
                step_patches = _changed_step_patches(
                    lines, entries[key], old_entries[key], next_line
                )
                if step_patches is not None:
                    patches.extend(step_patches)
                    continue
            # Comments immediately before the next entry belong to that entry.
            end = _end_before_comments(lines, line, next_line)
            document = CommentedMap()
            document[key] = entries[key]
            rendered = _render_fragment(document)
            replacement = [" " * column + part for part in rendered]
            patches.append((line, end, replacement))

    if not patches:
        return None
    for start, end, replacement in sorted(patches, key=lambda item: item[0], reverse=True):
        lines[start:end] = replacement
    result = "".join(lines)
    try:
        return result if _plain(yaml.safe_load(result)) == _plain(source) else None
    except yaml.YAMLError:
        return None


def _end_before_comments(lines: list[str], start: int, boundary: int) -> int:
    end = boundary
    while end > start + 1 and (not lines[end - 1].strip()
                               or lines[end - 1].lstrip().startswith("#")):
        end -= 1
    return end


def _render_fragment(value) -> list[str]:
    writer = _roundtrip_yaml()
    writer.allow_unicode = True
    writer.width = 4096
    writer.indent(mapping=2, sequence=4, offset=2)
    output = StringIO()
    writer.dump(value, output)
    return output.getvalue().splitlines(keepends=True)


def _changed_step_patches(lines, workflow, original_workflow, workflow_end):
    """Use step spans when the workflow's structure and metadata are stable."""
    if not isinstance(workflow, dict) or not isinstance(original_workflow, dict):
        return None
    metadata = {key: _plain(value) for key, value in workflow.items() if key != "steps"}
    old_metadata = {key: value for key, value in original_workflow.items() if key != "steps"}
    if metadata != old_metadata:
        return None
    steps = workflow.get("steps")
    old_steps = original_workflow.get("steps")
    if not isinstance(steps, list) or not isinstance(old_steps, list):
        return None
    if [step.get("id") for step in steps] != [step.get("id") for step in old_steps]:
        return None
    step_section = workflow.lc.key("steps")[0]
    later_fields = [workflow.lc.key(key)[0] for key in workflow
                    if workflow.lc.key(key)[0] > step_section]
    section_end = min(later_fields, default=workflow_end)
    patches = []
    for index, step in enumerate(steps):
        if _plain(step) == old_steps[index]:
            continue
        if attached_comment(steps, index):
            return None
        start = steps.lc.item(index)[0]
        next_line = (steps.lc.item(index + 1)[0]
                     if index + 1 < len(steps) else section_end)
        end = _end_before_comments(lines, start, next_line)
        rendered = _render_fragment(CommentedSeq([step]))
        prefix_width = lines[start].find("-") - rendered[0].find("-")
        if prefix_width < 0:
            return None
        replacement = [" " * prefix_width + part for part in rendered]
        patches.append((start, end, replacement))
    return patches


def attached_comment(collection, key) -> bool:
    """Whether removing this mapping key or list item would discard a note."""
    return bool(hasattr(collection, "ca") and collection.ca.items.get(key))


def has_comments(value) -> bool:
    """Whether a YAML value contains notes that need manual placement."""
    if hasattr(value, "ca") and (value.ca.comment or value.ca.items):
        return True
    if isinstance(value, dict):
        return any(has_comments(child) for child in value.values())
    if isinstance(value, list):
        return any(has_comments(child) for child in value)
    return False


def format_long_inline(document, *, width: int = 100) -> None:
    """Expand long flow collections while leaving short entries compact."""
    def visit(value) -> None:
        if isinstance(value, dict):
            for child in value.values():
                visit(child)
            if hasattr(value, "fa") and value.fa.flow_style():
                length = sum(len(str(k)) + len(str(v)) + 4 for k, v in value.items())
                if length > width:
                    value.fa.set_block_style()
        elif isinstance(value, list):
            for child in value:
                visit(child)
            if hasattr(value, "fa") and value.fa.flow_style():
                length = sum(len(str(item)) + 2 for item in value)
                if length > width:
                    value.fa.set_block_style()

    visit(document)
