"""Turn check results + previous state into notification events, without duplicates.

Event types
-----------
TARGET_HIT        verified, in stock, total <= target            (the main alert)
CANDIDATE         unverified / comparison price <= target         (check manually)
PRICE_DROP        significant drop vs. last trusted observation
DEAL_ENDED        a previously alerted verified deal is gone (price up / sold out)
BACK_IN_STOCK     identity-confirmed retailer listing became orderable
OUT_OF_STOCK      ... and went away again (optional)
SOURCE_FAILING    N consecutive failed checks for a source
SOURCE_RECOVERED  a failing source works again

Deduplication
-------------
* TARGET_HIT / CANDIDATE fire once when the condition becomes true, again only
  if the price falls further, or after `target_reminder_hours`.
  A temporarily blocked fetch does NOT reset them (no re-alert after a captcha).
* PRICE_DROP compares to the last trusted observation; identical drop values
  are suppressed for 12 h (prevents spam from oscillating prices).
* Stock events need a known previous availability.
* SOURCE_FAILING fires once per failure streak.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from .config import Settings
from .models import Availability, CheckResult, MatchResult, Verification
from .state import parse_iso

DROP_COOLDOWN = timedelta(hours=12)


class EventType(str, Enum):
    TARGET_HIT = "target_hit"
    CANDIDATE = "candidate"
    PRICE_DROP = "price_drop"
    DEAL_ENDED = "deal_ended"
    BACK_IN_STOCK = "back_in_stock"
    OUT_OF_STOCK = "out_of_stock"
    SOURCE_FAILING = "source_failing"
    SOURCE_RECOVERED = "source_recovered"


PRIORITY = {
    EventType.TARGET_HIT: 0,
    EventType.CANDIDATE: 1,
    EventType.PRICE_DROP: 2,
    EventType.DEAL_ENDED: 3,
    EventType.BACK_IN_STOCK: 4,
    EventType.OUT_OF_STOCK: 5,
    EventType.SOURCE_FAILING: 6,
    EventType.SOURCE_RECOVERED: 7,
}


@dataclass
class Event:
    type: EventType
    result: CheckResult
    previous: Decimal | None = None
    note: str = ""


def _d(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _threshold_alert(
    alerts: dict, key: str, condition: bool, value: Decimal | None, now: datetime, reminder_hours: int
) -> str | None:
    """Shared dedup logic for TARGET_HIT and CANDIDATE.

    Returns "fire" (send alert), "ended" (an active alert's condition stopped) or None.
    """
    entry = alerts.get(key) or {}
    if not condition or value is None:
        if entry.get("active"):
            entry["active"] = False
            alerts[key] = entry
            return "ended"
        return None
    fire = False
    if not entry.get("active"):
        fire = True
    else:
        last_value = _d(entry.get("value"))
        if last_value is not None and value < last_value:
            fire = True
        sent = parse_iso(entry.get("sent_utc"))
        if reminder_hours > 0 and sent and now - sent >= timedelta(hours=reminder_hours):
            fire = True
    if fire:
        alerts[key] = {"active": True, "value": str(value), "sent_utc": _iso(now)}
        return "fire"
    return None


def _is_drop(prev: Decimal, new: Decimal, settings: Settings) -> bool:
    if new >= prev:
        return False
    diff = prev - new
    pct = diff / prev * 100
    return diff >= settings.significant_drop_eur or pct >= settings.significant_drop_pct


def evaluate(
    results: list[CheckResult], state: dict, settings: Settings, now: datetime | None = None
) -> list[Event]:
    now = now or datetime.now(timezone.utc)
    sources = state.setdefault("sources", {})
    alerts = state.setdefault("alerts", {})
    target = settings.target_total_eur
    events: list[Event] = []

    for r in results:
        if r.verification == Verification.SKIPPED:
            continue
        prev = sources.get(r.source_id, {})
        cur = dict(prev)
        cur["last_checked_utc"] = _iso(now)
        cur["verification"] = r.verification.value

        # ---------------- health ----------------
        health_key = f"health:{r.source_id}"
        if r.verification in (Verification.ERROR, Verification.REJECTED):
            failures = int(prev.get("consecutive_failures", 0)) + 1
            cur["consecutive_failures"] = failures
            cur["last_error"] = "; ".join(r.reasons)[:500]
            health = alerts.get(health_key) or {}
            if failures >= settings.failure_alert_after and not health.get("active"):
                alerts[health_key] = {"active": True, "sent_utc": _iso(now)}
                events.append(Event(EventType.SOURCE_FAILING, r, note=f"{failures} failed checks in a row"))
            sources[r.source_id] = cur
            continue  # no price/stock logic on failed checks

        cur["consecutive_failures"] = 0
        cur.pop("last_error", None)
        cur["last_ok_utc"] = _iso(now)
        if (alerts.get(health_key) or {}).get("active"):
            alerts[health_key] = {"active": False, "sent_utc": _iso(now)}
            events.append(Event(EventType.SOURCE_RECOVERED, r))

        basis = r.price_basis
        cur["price"] = str(r.price) if r.price is not None else None
        cur["total"] = str(r.total) if r.total is not None else None
        cur["title"] = r.offer.title if r.offer else None
        cur["method"] = r.offer.method if r.offer else None

        # ---------------- target / candidate ----------------
        is_target = r.verification == Verification.VERIFIED and r.in_stock and r.total is not None and r.total <= target
        target_state = _threshold_alert(
            alerts, f"target:{r.source_id}", is_target, r.total, now, settings.target_reminder_hours
        )
        deal_ended = target_state == "ended"
        if target_state == "fire":
            events.append(Event(EventType.TARGET_HIT, r))
        elif deal_ended:
            events.append(Event(EventType.DEAL_ENDED, r, previous=_d(prev.get("total"))))

        is_candidate = (
            settings.notify_unverified_candidates
            and r.verification in (Verification.UNVERIFIED, Verification.COMPARISON)
            and basis is not None
            and basis <= target
            and r.availability != Availability.OUT_OF_STOCK
        )
        if _threshold_alert(
            alerts, f"candidate:{r.source_id}", is_candidate, basis, now, settings.target_reminder_hours
        ) == "fire":
            events.append(Event(EventType.CANDIDATE, r))

        # ---------------- price drop (trusted observations only) ----------------
        if r.verification in (Verification.VERIFIED, Verification.COMPARISON) and basis is not None:
            is_total = r.total is not None
            prev_basis = _d(prev.get("baseline"))
            if prev_basis is not None and prev.get("baseline_is_total") == is_total and _is_drop(prev_basis, basis, settings):
                drop_key = f"drop:{r.source_id}"
                last = alerts.get(drop_key) or {}
                sent = parse_iso(last.get("sent_utc"))
                recently_same = last.get("value") == str(basis) and sent and now - sent < DROP_COOLDOWN
                if not recently_same and not is_target:  # target alert already covers it
                    alerts[drop_key] = {"value": str(basis), "sent_utc": _iso(now)}
                    events.append(Event(EventType.PRICE_DROP, r, previous=prev_basis))
            cur["baseline"] = str(basis)
            cur["baseline_is_total"] = is_total

        # ---------------- stock changes (identity-confirmed retailers) ----------------
        if r.kind == "retailer" and r.match == MatchResult.MATCH and r.availability != Availability.UNKNOWN:
            was = prev.get("stock")
            now_in = r.in_stock
            if was is not None and was != now_in:
                if now_in and not is_target:
                    events.append(Event(EventType.BACK_IN_STOCK, r))
                elif not now_in and settings.notify_out_of_stock and not deal_ended:
                    events.append(Event(EventType.OUT_OF_STOCK, r))
            cur["stock"] = now_in
            cur["availability"] = r.availability.value

        sources[r.source_id] = cur

    events.sort(key=lambda e: PRIORITY[e.type])
    return events
