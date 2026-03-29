#!/usr/bin/env python
"""
Unified NeuroFlow test runner.

Discovers and executes the full test suite (unit + integration) in a single
command.  Exit code mirrors pytest: 0 = all passed, non-zero = failures.

Usage
-----
    python run_all_tests.py               # run everything
    python run_all_tests.py -v            # verbose output
    python run_all_tests.py --cov         # include coverage report
    python run_all_tests.py --unit-only   # unit tests only
    python run_all_tests.py --integ-only  # integration tests only
"""

import argparse
import sys


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run all NeuroFlow unit and integration tests."
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose pytest output.",
    )
    parser.add_argument(
        "--cov",
        action="store_true",
        help="Enable coverage reporting (requires pytest-cov).",
    )
    exclusive = parser.add_mutually_exclusive_group()
    exclusive.add_argument(
        "--unit-only",
        action="store_true",
        help="Run unit tests only (tests/unit/).",
    )
    exclusive.add_argument(
        "--integ-only",
        action="store_true",
        help="Run integration tests only (tests/integration/).",
    )
    return parser.parse_args()


def main() -> int:
    try:
        import pytest
    except ImportError:
        print(
            "pytest is not installed. Install dev dependencies with:\n"
            "    pip install pytest pytest-cov",
            file=sys.stderr,
        )
        return 1

    args = _parse_args()

    # ── Build target path list ────────────────────────────────────────────────
    if args.unit_only:
        targets = ["tests/unit/"]
    elif args.integ_only:
        targets = ["tests/integration/"]
    else:
        # Run all tests: existing smoke tests + new unit + integration suites
        targets = [
            "smoke_auth_test.py",
            "smoke_desktop_startup_test.py",
            "tests/unit/",
            "tests/integration/",
        ]

    # ── Build pytest argument list ────────────────────────────────────────────
    pytest_args: list[str] = list(targets)

    if args.verbose:
        pytest_args.append("-v")

    pytest_args.extend(["--tb=short"])

    if args.cov:
        pytest_args.extend(["--cov=src", "--cov-report=term-missing"])

    # ── Execute ───────────────────────────────────────────────────────────────
    print("=" * 70)
    print("NeuroFlow test suite")
    print("Targets:", " ".join(targets))
    print("=" * 70)

    return pytest.main(pytest_args)


if __name__ == "__main__":
    sys.exit(main())
