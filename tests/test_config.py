from pathlib import Path

import pytest

from chunkget import config
from chunkget.errors import UsageError

KIB = 1024
MIB = 1024 * KIB


def test_defaults_match_plan_section_2():
    assert config.DEFAULT_CHUNK_SIZE == 100 * MIB
    assert config.DEFAULT_ALGORITHM == "sha256"
    assert config.DEFAULT_MAX_RETRIES == 5
    assert config.DEFAULT_TIMEOUT == 30
    assert config.BUFFER_SIZE == 1 * MIB
    assert config.MAX_MANIFEST_BYTES == 64 * MIB
    assert config.MAX_CHUNKS == 250_000
    assert config.MAX_CONSECUTIVE_NETWORK_FAILURES == 3


@pytest.mark.parametrize(
    "text, expected",
    [
        ("4096", 4096),
        ("0", 0),
        ("1", 1),
        ("4K", 4 * KIB),
        ("100M", 100 * MIB),
        ("1G", 1024 * MIB),
    ],
)
def test_parse_size_valid(text, expected):
    assert config.parse_size(text) == expected


@pytest.mark.parametrize(
    "text",
    ["", " ", "-1", "-4K", "4T", "4KB", "K", "1.5M", "1,5M", "abc", "4 K", "4K\n", "+4"],
)
def test_parse_size_invalid_reports_accepted_format(text):
    with pytest.raises(UsageError) as excinfo:
        config.parse_size(text)
    message = str(excinfo.value)
    assert "K, M or G" in message
    assert "100M" in message


GIB = 1024 * MIB

RANGES = [
    (config.validate_chunk_size, 1, GIB),
    (config.validate_max_retries, 0, 100),
    (config.validate_timeout, 1, 3600),
]


@pytest.mark.parametrize("validator, low, high", RANGES)
def test_validators_accept_inclusive_limits(validator, low, high):
    assert validator(low) == low
    assert validator(high) == high
    assert validator((low + high) // 2) == (low + high) // 2


@pytest.mark.parametrize("validator, low, high", RANGES)
def test_validators_reject_out_of_range_with_valid_range(validator, low, high):
    for value in (low - 1, high + 1):
        with pytest.raises(UsageError) as excinfo:
            validator(value)
        message = str(excinfo.value)
        assert str(low) in message
        assert str(high) in message


def test_state_dir_uses_xdg_state_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert config.default_state_dir() == tmp_path / "state" / "chunkget"


def test_state_dir_without_xdg_state_home(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert config.default_state_dir() == (
        tmp_path / ".local" / "state" / "chunkget"
    )


def test_state_dir_ignores_empty_or_relative_xdg_state_home(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("HOME", str(tmp_path))
    expected = tmp_path / ".local" / "state" / "chunkget"
    for value in ("", "relative/dir"):
        monkeypatch.setenv("XDG_STATE_HOME", value)
        assert config.default_state_dir() == expected


def test_default_manifest_path():
    assert config.default_manifest_path("image.iso") == Path(
        "image.iso.chunkget.manifest"
    )


def test_default_destination():
    assert config.default_destination("image.iso") == Path("image.iso")
