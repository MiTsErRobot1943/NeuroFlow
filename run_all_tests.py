"""Compatibility launcher for the unified test runner."""

import sys

from scripts.runtime.run_all_tests import main


if __name__ == "__main__":
    sys.exit(main())

