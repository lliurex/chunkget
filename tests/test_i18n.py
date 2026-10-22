import gettext

import pytest

from chunkget import i18n


class UpperTranslations(gettext.NullTranslations):
    def gettext(self, message):
        return message.upper()

    def ngettext(self, msgid1, msgid2, n):
        return (msgid1 if n == 1 else msgid2).upper()


@pytest.fixture(autouse=True)
def restore_translation():
    previous = i18n.get_translation()
    yield
    i18n.set_translation(previous)


def test_without_catalog_returns_source_text():
    i18n.set_translation(gettext.NullTranslations())
    assert i18n._("x") == "x"
    assert i18n.ngettext("one chunk", "many chunks", 1) == "one chunk"
    assert i18n.ngettext("one chunk", "many chunks", 2) == "many chunks"


def test_default_translation_falls_back_to_source_text():
    assert i18n._("x") == "x"


def test_injected_translation_is_used_by_gettext():
    i18n.set_translation(UpperTranslations())
    assert i18n._("x") == "X"


def test_injected_translation_is_used_by_ngettext():
    i18n.set_translation(UpperTranslations())
    assert i18n.ngettext("one chunk", "many chunks", 1) == "ONE CHUNK"
    assert i18n.ngettext("one chunk", "many chunks", 3) == "MANY CHUNKS"
