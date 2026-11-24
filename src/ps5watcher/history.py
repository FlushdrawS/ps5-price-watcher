"""Timestamped price/stock observations, one JSON line per source per check.

Files: <data dir>/history/YYYY-MM.jsonl (UTC month). They are persisted
between GitHub Actions runs together with state.json on the `watcher-state`
branch (see scripts/state_branch.sh). Months older than
`history_retention_days` are deleted. Standard library only.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

FIELDS = ["t", "source", "status", "fetch", "match", "price", "shipping", "total", "stock",
          "seller", "marketplace", "method", "reasons"]


def observation(r, now: datetime) -> dict:
    o = r.offer
    return {
        "t": now.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
        "source": r.source_id,
        "status": r.verification.value,
        "fetch": r.fetch_status.value,
        "match": r.match.value,
        "price": str(o.price) if o and o.price is not None else None,
        "shipping": str(o.shipping) if o and o.shipping is not None else None,
        "total": str(r.total) if r.total is not None else None,
        "stock": r.availability.value,
        "seller": (o.seller if o else None),
        "marketplace": (o.is_marketplace if o else None),
        "method": (o.method if o else None),
        "reasons": [x[:160] for x in r.reasons[:3]],
    }


class HistoryStore:
    def __init__(self, directory: str | Path):
        self.dir = Path(directory)

    def _file(self, when: datetime) -> Path:
        return self.dir / f"{when.astimezone(timezone.utc):%Y-%m}.jsonl"

    def append(self, results: Iterable, now: datetime) -> int:
        rows = [observation(r, now) for r in results if r.verification.value != "skipped"]
        if not rows:
            return 0
        self.dir.mkdir(parents=True, exist_ok=True)
        with self._file(now).open("a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return len(rows)

    def read(self, since: datetime | None = None, source: str | None = None) -> list[dict]:
        if not self.dir.exists():
            return []
        out = []
        for path in sorted(self.dir.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if source and row.get("source") != source:
                    continue
                if since:
                    t = datetime.fromisoformat(row["t"])
                    if t < since:
                        continue
                out.append(row)
        return out

    def prune(self, retention_days: int, now: datetime) -> list[str]:
        if not self.dir.exists() or retention_days <= 0:
            return []
        cutoff = (now - timedelta(days=retention_days)).astimezone(timezone.utc)
        cutoff_month = f"{cutoff:%Y-%m}"
        removed = []
        for path in self.dir.glob("*.jsonl"):
            if path.stem < cutoff_month:
                path.unlink()
                removed.append(path.name)
        return removed

    def export_csv(self, rows: list[dict], path: str | Path) -> None:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader()
            for row in rows:
                row = dict(row)
                row["reasons"] = " | ".join(row.get("reasons") or [])
                w.writerow(row)
