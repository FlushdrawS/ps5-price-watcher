"""Persistent JSON state: last observations per source and sent alerts.

The file is small and human-readable so you can inspect it on the
`watcher-state` branch on GitHub.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def empty_state() -> dict[str, Any]:
    return {
        "version": SCHEMA_VERSION,
        "last_slot": None,
        "last_run_utc": None,
        "alert_channel": None,
        "sources": {},
        "alerts": {},
    }


class StateStore:
    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return empty_state()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("version") != SCHEMA_VERSION:
                raise ValueError("unexpected schema")
        except (ValueError, OSError) as exc:
            backup = self.path.with_suffix(".corrupt.json")
            log.warning("State file unreadable (%s); backing up to %s and starting fresh", exc, backup)
            try:
                shutil.copy(self.path, backup)
            except OSError:
                pass
            return empty_state()
        base = empty_state()
        base.update(data)
        return base

    def save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)
