import importlib
import pkgutil
import string

import handtrack
from handtrack.i18n import STRINGS, Translator


def fields(text):
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_languages_have_same_keys():
    assert set(STRINGS["ru"]) == set(STRINGS["en"])


def test_placeholders_match():
    for key, ru in STRINGS["ru"].items():
        assert fields(ru) == fields(STRINGS["en"][key]), key


def test_translator_falls_back_to_key():
    tr = Translator("xx")
    assert tr.lang == "ru"
    assert tr("no_such_key") == "no_such_key"


def test_all_modules_import():
    for module in pkgutil.walk_packages(handtrack.__path__, "handtrack."):
        if module.name != "handtrack.__main__":
            importlib.import_module(module.name)
