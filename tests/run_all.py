#!/usr/bin/env python3
"""Runs every check in this directory and reports one pass/fail.

Each test file is a standalone script that prints PASS/FAIL lines and exits
non-zero on failure, so they can be run individually while debugging:

    python tests/test_agent.py

Run the lot with:

    python tests/run_all.py

They run in separate processes deliberately. The app is a chain of modules
that patch routes onto one shared FastAPI instance and cache state in module
globals, so tests that share an interpreter would contaminate each other.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent

# What each file covers, so a failure points somewhere useful.
DESCRIPTIONS = {
    "test_agent.py": "autonomous agent safety gates",
    "test_strategies.py": "strategy registry and multi-strategy scanning",
    "test_sl.py": "stop-loss and take-profit triggering",
    "test_goldcap.py": "gold position risk cap",
    "test_endpoint.py": "trade history repair endpoint",
    "test_pricing.py": "executable entry fills and backtest dealing costs",
    "test_notify.py": "alerting and the run watchdog",
    "test_stale.py": "market-closed detection",
    "test_cronauth.py": "scheduled-job authentication and its error messages",
}


def main() -> int:
    files = sorted(p for p in HERE.glob("test_*.py"))
    if not files:
        print("No tests found.")
        return 1

    failed = []
    for path in files:
        label = DESCRIPTIONS.get(path.name, path.stem)
        print(f"\n=== {path.name} - {label} ".ljust(70, "="))
        result = subprocess.run([sys.executable, str(path)], cwd=str(REPO))
        if result.returncode != 0:
            failed.append(path.name)

    print("\n" + "=" * 70)
    if failed:
        print(f"FAILED: {len(failed)} of {len(files)} suites")
        for name in failed:
            print(f"  - {name} ({DESCRIPTIONS.get(name, '')})")
        return 1
    print(f"All {len(files)} suites passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
