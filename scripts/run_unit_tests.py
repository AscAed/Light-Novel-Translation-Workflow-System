"""Run all unit tests except the mock-server-only E2E module."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"


def main() -> int:
    modules = sorted(
        f"tests.{path.stem}"
        for path in TESTS.glob("test_*.py")
        if path.name != "test_e2e.py"
    )
    if not modules:
        print("No unit test modules were found.", file=sys.stderr)
        return 2

    result = subprocess.run(
        [sys.executable, "-m", "unittest", *modules, "-q"],
        cwd=ROOT,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
