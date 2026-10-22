from chunkget import config

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
