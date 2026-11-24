"""Evidence files for live tests: what was fetched, how, and what was extracted.

`probe --record` and the live test suite write one JSON file per source and
run to evidence/probe/<source>/<UTC timestamp>-<fetcher>.json. Commit the
files that justify setting `integration_tested = true` for a source, so
"tested" is always backed by an auditable record. No HTML and no cookies are
stored.
"""

from __future__ import annotations

import json
import platform
from datetime import datetime, timezone
from pathlib import Path

from . import __version__


def build(result, fetch, now: datetime | None = None, where: str = "") -> dict:
    now = now or datetime.now(timezone.utc)
    o = result.offer
    return {
        "recorded_utc": now.replace(microsecond=0).isoformat(),
        "where": where or f"{platform.system()} {platform.machine()}",
        "tool_version": __version__,
        "source": result.source_id,
        "url": result.url,
        "final_url": fetch.final_url if fetch else None,
        "fetcher": fetch.fetcher if fetch else None,
        "http_status": fetch.http_status if fetch else None,
        "fetch_status": result.fetch_status.value,
        "fetch_error": fetch.error if fetch else None,
        "html_size": len(fetch.html) if fetch and fetch.html else 0,
        "extracted": None if o is None else {
            "title": o.title,
            "price": str(o.price) if o.price is not None else None,
            "currency": o.currency,
            "shipping": str(o.shipping) if o.shipping is not None else None,
            "availability": o.availability.value,
            "availability_note": o.availability_note,
            "seller": o.seller,
            "is_marketplace": o.is_marketplace,
            "gtin": o.gtin,
            "method": o.method,
            "price_visible": o.price_visible,
            "notes": o.notes,
        },
        "total": str(result.total) if result.total is not None else None,
        "match": result.match.value,
        "verification": result.verification.value,
        "reasons": result.reasons,
        "checklist_for_integration_tested": {
            "fetch_ok": result.fetch_status.value == "ok",
            "identity_match": result.match.value == "match",
            "price_or_explicit_unavailability": bool(o and (o.price is not None or o.availability.value == "out_of_stock")),
            "seller_known": bool(o and o.seller),
            "compare_with_browser": "MANUAL: open the URL and confirm price, stock, seller and shipping match",
        },
    }


def record(result, fetch, directory: Path, where: str = "") -> Path:
    now = datetime.now(timezone.utc)
    data = build(result, fetch, now, where)
    folder = Path(directory) / "probe" / result.source_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{now:%Y-%m-%dT%H%MZ}-{data['fetcher'] or 'none'}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
