import importlib
import pkgutil
import re
import string

import handtrack
from handtrack.i18n import STRINGS, Translator


def test_strings_are_english_only():
    for key, text in STRINGS.items():
        assert not re.search("[\u0400-\u04FF]", text), key


def test_placeholders_are_valid():
    for key, text in STRINGS.items():
        list(string.Formatter().parse(text))  # raises on a malformed template


def test_translator_formats_and_falls_back_to_key():
    tr = Translator()
    assert tr("settings_about_text", version="1.0") == "HandTrack 1.0 · MIT License"
    assert tr("no_such_key") == "no_such_key"


def test_all_modules_import():
    for module in pkgutil.walk_packages(handtrack.__path__, "handtrack."):
        if module.name != "handtrack.__main__":
            importlib.import_module(module.name)
