"""Where runtime data lives. Standard library only.

PS5W_DATA_DIR (default: <project>/data) contains
    state.json        last observations, alert memory, last slots
    history/*.jsonl   timestamped observations
On GitHub Actions this directory is restored from / saved to the
`watcher-state` branch by scripts/state_branch.sh.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    return Path(os.environ.get("PS5W_DATA_DIR") or (PROJECT_ROOT / "data"))


def state_file() -> Path:
    return data_dir() / "state.json"


def history_dir() -> Path:
    return data_dir() / "history"


def evidence_dir() -> Path:
    return Path(os.environ.get("PS5W_EVIDENCE_DIR") or (PROJECT_ROOT / "evidence"))
