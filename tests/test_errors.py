from chunkget.errors import ExitCode

# Table 7.5 of specs/001-chunkget-mvp/plan.md
EXPECTED = {
    "OK": 0,
    "UNEXPECTED": 1,
    "USAGE": 2,
    "SOURCE_ERROR": 3,
    "USER_DECLINED": 4,
    "MANIFEST_INVALID": 5,
    "NETWORK_ERROR": 6,
    "RETRIES_EXHAUSTED": 7,
    "GLOBAL_HASH_MISMATCH": 8,
    "NO_SPACE": 9,
    "FILESYSTEM_ERROR": 10,
    "SERVER_INCOMPATIBLE": 11,
    "ALREADY_RUNNING": 12,
    "STATE_INVALID": 13,
    "INTERRUPTED": 130,
    "TERMINATED": 143,
}


def test_exit_code_names_and_values_match_table():
    assert {member.name: member.value for member in ExitCode} == EXPECTED


def test_exit_code_values_are_unique():
    values = [member.value for member in ExitCode]
    assert len(values) == len(set(values))


def test_ok_is_zero():
    assert ExitCode.OK == 0


# --- Exception hierarchy (T04) ---

import gettext

import pytest

from chunkget import errors, i18n

EXCEPTION_CODES = [
    (errors.UsageError, ExitCode.USAGE),
    (errors.SourceError, ExitCode.SOURCE_ERROR),
    (errors.UserDeclinedError, ExitCode.USER_DECLINED),
    (errors.ManifestInvalidError, ExitCode.MANIFEST_INVALID),
    (errors.NetworkError, ExitCode.NETWORK_ERROR),
    (errors.RetriesExhaustedError, ExitCode.RETRIES_EXHAUSTED),
    (errors.GlobalHashMismatchError, ExitCode.GLOBAL_HASH_MISMATCH),
    (errors.NoSpaceError, ExitCode.NO_SPACE),
    (errors.FilesystemError, ExitCode.FILESYSTEM_ERROR),
    (errors.ServerIncompatibleError, ExitCode.SERVER_INCOMPATIBLE),
    (errors.AlreadyRunningError, ExitCode.ALREADY_RUNNING),
    (errors.StateInvalidError, ExitCode.STATE_INVALID),
    (errors.InterruptedByUser, ExitCode.INTERRUPTED),
    (errors.OutputExistsError, ExitCode.USER_DECLINED),
    (errors.DestinationExistsError, ExitCode.USER_DECLINED),
]


class UpperTranslations(gettext.NullTranslations):
    def gettext(self, message):
        return message.upper()


@pytest.fixture
def upper_translation():
    previous = i18n.get_translation()
    i18n.set_translation(UpperTranslations())
    yield
    i18n.set_translation(previous)


@pytest.mark.parametrize("exc_class, code", EXCEPTION_CODES)
def test_exception_exposes_exit_code(exc_class, code):
    assert issubclass(exc_class, errors.ChunkgetError)
    assert exc_class("boom").exit_code == code


@pytest.mark.parametrize("exc_class, code", EXCEPTION_CODES)
def test_exception_message_goes_through_translation(
    exc_class, code, upper_translation
):
    assert str(exc_class("boom")) == "BOOM"


def test_message_is_formatted_after_translation():
    class PrefixTranslations(gettext.NullTranslations):
        def gettext(self, message):
            return "T: " + message

    previous = i18n.get_translation()
    i18n.set_translation(PrefixTranslations())
    try:
        exc = errors.NoSpaceError("need {needed} bytes", needed=5)
    finally:
        i18n.set_translation(previous)
    assert str(exc) == "T: need 5 bytes"


def test_terminated_exit_code_can_be_selected():
    exc = errors.InterruptedByUser("stop", exit_code=ExitCode.TERMINATED)
    assert exc.exit_code == ExitCode.TERMINATED


def test_base_error_defaults_to_unexpected():
    assert errors.ChunkgetError("x").exit_code == ExitCode.UNEXPECTED
