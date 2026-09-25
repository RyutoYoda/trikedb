"""The language switch.

Most of these are about the ways a translation layer fails *quietly*. A
missing Japanese string does not raise; a stale key does not raise; a
`{placeholder}` renamed on one side and not the other raises only for the
reader who happens to be in that language. So each of those gets a test
that fails on the machine of whoever introduced it.
"""
from __future__ import annotations

import ast
import os
import re
import string
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import curation  # noqa: E402
import i18n  # noqa: E402


#: Keys whose value carries no natural language at all -- an identifier, a
#: name supplied by the graph, an example value. They are the same in every
#: language on purpose, and listing them here is what makes that a decision
#: rather than an oversight: a genuinely untranslated sentence still fails.
NOT_PROSE = {
    "side.content_hash",   # a label and a hex string
    "hint.pred_known",     # the predicate's own name and its own description
    "ph.attr_name",        # example attribute name
    "ph.attr_value",       # example attribute value
}


def _placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


class TestEveryKeyHasEveryLanguage(unittest.TestCase):
    """The failure this catches is invisible in the product.

    A key with no `ja` renders in English on a Japanese screen, which looks
    like a translation nobody got to rather than a bug, so it survives
    review and ships.
    """

    def test_no_language_is_missing(self) -> None:
        for key, entry in i18n.TEXT.items():
            for lang in i18n.LANGUAGES:
                self.assertIn(lang, entry, f"{key} has no {lang}")
                self.assertTrue(entry[lang].strip(), f"{key}/{lang} is empty")

    def test_no_language_was_left_as_a_copy_of_the_other(self) -> None:
        # A placeholder copy ("fill this in later") is the other way a
        # missing translation hides. Keys whose value is genuinely the same
        # in both languages are listed, so adding one is a deliberate act.
        for key, entry in i18n.TEXT.items():
            if key in NOT_PROSE:
                continue
            self.assertNotEqual(entry["en"], entry["ja"],
                                f"{key} is identical in both languages")

    def test_the_default_language_is_one_of_the_listed_ones(self) -> None:
        self.assertIn(i18n.DEFAULT_LANGUAGE, i18n.LANGUAGES)


class TestThePicker(unittest.TestCase):

    class _Where:
        def __init__(self): self.drawn = []
        def radio(self, label, codes, **kw): self.drawn.append((label, codes))

    def test_it_offers_every_language(self) -> None:
        where = self._Where()
        i18n.picker(where)
        self.assertEqual(len(where.drawn), 1)
        self.assertEqual(where.drawn[0][1], list(i18n.LANGUAGES))

    def test_one_language_draws_no_switch(self) -> None:
        # README tells people to cut LANGUAGES down if they want one
        # language. A switch with one position is furniture.
        where = self._Where()
        before = i18n.LANGUAGES
        i18n.LANGUAGES = {"en": "English"}
        try:
            i18n.picker(where)
        finally:
            i18n.LANGUAGES = before
        self.assertEqual(where.drawn, [])

    def test_each_language_is_named_in_its_own_language(self) -> None:
        # Somebody who cannot read the current language still has to be
        # able to find their way out of it.
        self.assertEqual(i18n.LANGUAGES["ja"], "日本語")
        self.assertEqual(i18n.LANGUAGES["en"], "English")


class TestPlaceholdersMatch(unittest.TestCase):
    """`{name}` renamed on one side only breaks one language at a time."""

    def test_both_languages_take_the_same_arguments(self) -> None:
        for key, entry in i18n.TEXT.items():
            self.assertEqual(_placeholders(entry["en"]),
                             _placeholders(entry["ja"]),
                             f"{key} takes different arguments per language")

    def test_every_string_formats_with_its_own_placeholders(self) -> None:
        for key, entry in i18n.TEXT.items():
            args = {n: "x" for n in _placeholders(entry["en"])}
            for lang in i18n.LANGUAGES:
                with i18n.using(lang):
                    i18n.t(key, **args)   # must not raise


class TestMissingKeysAreVisible(unittest.TestCase):

    def test_an_unknown_key_does_not_raise(self) -> None:
        # Half a screen is worse than one odd-looking label.
        self.assertEqual(i18n.t("no.such.key"), "⟦no.such.key⟧")

    def test_an_unknown_key_is_obvious_on_screen(self) -> None:
        # Falling back to the key *unbracketed* would read as a real label
        # and ship unnoticed.
        self.assertNotEqual(i18n.t("no.such.key"), "no.such.key")


class TestTheScreenUsesKeysThatExist(unittest.TestCase):
    """Guards the other direction: a key spelled wrong in the source.

    Reads the source rather than importing, so it sees every call site
    including the ones on branches these tests never reach.
    """

    SOURCES = ("curation.py", "streamlit_app.py")

    def _keys_used(self):
        here = os.path.join(os.path.dirname(__file__), "..")
        for name in self.SOURCES:
            with open(os.path.join(here, name), encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), name)
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "t"
                        and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)):
                    yield name, node.args[0].value

    def test_every_key_on_screen_is_defined(self) -> None:
        used = list(self._keys_used())
        self.assertTrue(used, "no t() calls found -- did the parser break?")
        for where, key in used:
            self.assertIn(key, i18n.TEXT, f"{where} uses undefined {key!r}")

    def test_the_screen_really_is_translated(self) -> None:
        # A regression where somebody adds a field with a bare English
        # string would leave this count flat while the screen grows.
        self.assertGreater(len({k for _, k in self._keys_used()}), 50)


class TestSwitchingLanguageKeepsWhatWasTyped(unittest.TestCase):
    """Switching language must not empty the form.

    Streamlit identifies a widget by its `key`. Translate the keys and
    every widget becomes a different widget the moment the language
    changes, which throws away everything typed -- at exactly the moment
    somebody is most likely to switch, which is partway through a form they
    cannot read.
    """

    def test_widget_keys_are_not_translated(self) -> None:
        here = os.path.join(os.path.dirname(__file__), "..")
        for name in ("curation.py", "streamlit_app.py"):
            with open(os.path.join(here, name), encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), name)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for kw in node.keywords:
                    if kw.arg != "key":
                        continue
                    self.assertNotIn("i18n", ast.dump(kw.value), name)
                    self.assertNotIn("'t'", ast.dump(kw.value), name)

    def test_the_field_keys_are_stable_across_languages(self) -> None:
        class Col:
            def __init__(self): self.keys = []
            def markdown(self, *a, **k): pass
            def columns(self, n): return [self, self]
            def text_input(self, label, **k):
                self.keys.append(k.get("key")); return ""

        seen = []
        for lang in i18n.LANGUAGES:
            col = Col()
            with i18n.using(lang):
                curation._props_field(col, "x", "s")
            seen.append(col.keys)
        self.assertEqual(seen[0], seen[1])
        self.assertTrue(all(seen[0]))


class TestMessagesFromTheGuardStayEnglish(unittest.TestCase):
    """`outbox.domain` must not learn about language.

    Its sentences are written into PR bodies and into the `ERROR` column,
    read by people who did not press the button and whose screen language
    is unknowable from there. One language is the correct answer for those,
    and it keeps `domain` free of any dependency on the screen.
    """

    def test_domain_does_not_import_the_language_layer(self) -> None:
        here = os.path.join(os.path.dirname(__file__), "..", "outbox")
        for name in ("domain.py", "service.py", "ports.py"):
            with open(os.path.join(here, name), encoding="utf-8") as fh:
                source = fh.read()
            self.assertNotIn("i18n", source, name)

    def test_a_refusal_from_the_guard_is_the_same_in_both_languages(self):
        said = []
        for lang in i18n.LANGUAGES:
            with i18n.using(lang):
                _, problem = curation._target("workspace.yaml", [])
            said.append(problem.text)
        self.assertEqual(said[0], said[1])


class TestTheWholeScreenSpeaksBothLanguages(unittest.TestCase):
    """Spot-check that choosing a language actually changes the words."""

    def test_a_refusal_changes_language(self) -> None:
        said = []
        for lang in i18n.LANGUAGES:
            with i18n.using(lang):
                _, problem = curation._bundle(
                    "", None, "", False, "", "", None, at="2026-09-25")
            said.append(problem.text)
        self.assertEqual(len(set(said)), len(i18n.LANGUAGES))
        self.assertEqual(problem.field, "event")

    def test_japanese_is_actually_japanese(self) -> None:
        # Cheap, but it catches a Japanese column filled in with English.
        kana = re.compile(r"[぀-ゟ゠-ヿ一-鿿]")
        missing = [k for k, e in i18n.TEXT.items()
                   if k not in NOT_PROSE and not kana.search(e["ja"])]
        self.assertEqual(missing, [], f"no Japanese in: {missing}")


if __name__ == "__main__":
    unittest.main()
