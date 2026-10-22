"""gettext initialisation for user-facing messages."""

import gettext

DOMAIN = "chunkget"

_translation = gettext.translation(DOMAIN, fallback=True)


def get_translation():
    return _translation


def set_translation(translation):
    """Replace the active translation object (used by tests)."""
    global _translation
    _translation = translation


def _(message):
    return _translation.gettext(message)


def ngettext(singular, plural, n):
    return _translation.ngettext(singular, plural, n)
