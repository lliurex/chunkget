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
