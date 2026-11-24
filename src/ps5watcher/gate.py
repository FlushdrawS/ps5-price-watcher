"""Dependency-free time-slot gate, run BEFORE `pip install` in the workflow.

    python -m ps5watcher.gate [--force]

Prints a summary and writes `due`, `report` and `needs_browser` to
$GITHUB_OUTPUT. Imports only the standard library and stdlib-only modules,
so skipped runs finish in seconds.
"""

from __future__ import annotations

import argparse
import os
import sys

from .config import ConfigError, load_config
from .paths import state_file
from .schedule import decide
from .state import StateStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ps5watcher.gate")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    try:
        cfg = load_config()
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    state = StateStore(state_file()).load()
    s = cfg.settings
    d = decide(
        state.get("last_slot"), s.timezone, s.normal_interval_hours, s.friday_interval_minutes,
        force=args.force, report_hours=s.report_interval_hours,
    )
    report = d.due and state.get("last_report_slot") != d.report_slot
    browser = any(x.enabled and x.url and x.fetcher == "playwright" for x in cfg.sources)
    print(
        f"due={str(d.due).lower()} report={str(report).lower()} slot={d.slot} "
        f"local={d.local_time} ({d.reason}) needs_browser={str(browser).lower()}"
    )
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"due={str(d.due).lower()}\nreport={str(report).lower()}\nneeds_browser={str(browser).lower()}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
