"""Checks that every test and file named in docs/requirements-matrix.md really exists.

    python scripts/check_matrix.py

References are written in backticks: `test_file.py::test_name` for a test, and a path such as
`agent/verify.py` or `scripts/docker_smoke.sh` for a file. A renamed or deleted test makes this
fail, so the matrix cannot quietly go stale. Exits non-zero if anything is missing.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "insurance_claims"
TESTS = APP / "tests"
MATRIX = ROOT / "docs" / "requirements-matrix.md"

TEST_REF = re.compile(r"`(test_[A-Za-z0-9_]+\.py)::(test_[A-Za-z0-9_]+)`")
FILE_REF = re.compile(r"`([A-Za-z0-9_./-]+\.(?:py|tsx?|sh|md|ya?ml|json|toml))`")


def test_names(path: Path) -> set[str]:
    """Names of the test functions defined at the top level of a test file."""
    tree = ast.parse(path.read_text())
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def file_exists(reference: str) -> bool:
    return any((base / reference).is_file() for base in (ROOT, APP, TESTS))


def main() -> int:
    text = MATRIX.read_text()
    problems: list[str] = []
    cache: dict[str, set[str]] = {}

    test_refs = sorted(set(TEST_REF.findall(text)))
    for filename, name in test_refs:
        path = TESTS / filename
        if not path.is_file():
            problems.append(f"missing test file: {filename} (for {name})")
            continue
        names = cache.setdefault(filename, test_names(path))
        if name not in names:
            problems.append(f"missing test: {filename}::{name}")

    file_refs = sorted(set(FILE_REF.findall(text)))
    for reference in file_refs:
        if not file_exists(reference):
            problems.append(f"missing file: {reference}")

    print(f"checked {len(test_refs)} test references and {len(file_refs)} file references")
    if problems:
        print("\n".join(f"  - {p}" for p in problems))
        return 1
    print("every reference in the requirements matrix exists")
    return 0


if __name__ == "__main__":
    sys.exit(main())
