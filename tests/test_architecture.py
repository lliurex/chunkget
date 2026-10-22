"""The core must not depend on the CLI (RNF4)."""

import ast
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "chunkget"
CLI_FILES = {"cli.py", "__main__.py"}
FORBIDDEN_CALLS = {"input", "print"}


def find_violations(source):
    """Return a list of descriptions of CLI-only constructs used in source."""
    violations = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root == "argparse":
                    violations.append("import argparse")
                if alias.name == "chunkget.cli":
                    violations.append("import chunkget.cli")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = {alias.name for alias in node.names}
            if module.split(".")[0] == "argparse":
                violations.append("from argparse import ...")
            if module == "chunkget.cli" or (
                node.level > 0 and module == "cli"
            ):
                violations.append("import from chunkget.cli")
            if (module == "chunkget" or (node.level > 0 and not module)) and (
                "cli" in names
            ):
                violations.append("import chunkget.cli")
            if module == "sys" and "exit" in names:
                violations.append("from sys import exit")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALLS:
                violations.append("call to %s()" % func.id)
            elif (
                isinstance(func, ast.Attribute)
                and func.attr == "exit"
                and isinstance(func.value, ast.Name)
                and func.value.id == "sys"
            ):
                violations.append("call to sys.exit()")
    return violations


def core_files():
    return sorted(
        path for path in PACKAGE_DIR.glob("*.py") if path.name not in CLI_FILES
    )


def test_core_modules_do_not_use_cli_constructs():
    assert core_files()
    found = {
        path.name: find_violations(path.read_text(encoding="utf-8"))
        for path in core_files()
    }
    assert {name: v for name, v in found.items() if v} == {}


def test_detector_flags_argparse_in_temporary_file(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text("import argparse\n", encoding="utf-8")
    assert find_violations(sample.read_text(encoding="utf-8")) == [
        "import argparse"
    ]


def test_detector_flags_each_forbidden_construct():
    cases = [
        "from argparse import ArgumentParser",
        "import chunkget.cli",
        "from chunkget.cli import main",
        "from chunkget import cli",
        "from . import cli",
        "from .cli import main",
        "input('?')",
        "print('x')",
        "import sys\nsys.exit(1)",
        "from sys import exit",
    ]
    for source in cases:
        assert find_violations(source), source


def test_detector_accepts_clean_code():
    source = "import os\nfrom chunkget.errors import ExitCode\nos.getcwd()\n"
    assert find_violations(source) == []
