"""Preserve human-authored YAML layout and comments while updating values."""

from __future__ import annotations

import json
import re

from ruamel.yaml import YAML

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
