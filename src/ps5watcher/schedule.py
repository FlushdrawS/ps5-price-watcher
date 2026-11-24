"""Europe/Berlin time-slot gating.

GitHub Actions cron runs in UTC, starts late (often 5-30 min) and can
occasionally skip a run. Instead of trusting the cron minute, every run maps
"now in Berlin" onto a slot and only checks if that slot has not been checked
yet:

  * Friday (Berlin):  one slot per 15 minutes  -> "fri:2026-11-27T14:15"
  * Other days:       one slot per 3 hours     -> "std:2026-11-24T09"

The workflow can therefore fire a little too often (cheap: the gate exits in
seconds) without ever double-checking a slot, and DST changes are handled by
zoneinfo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

FRIDAY = 4  # Monday == 0


@dataclass
class GateDecision:
    due: bool
    slot: str
    local_time: str
    reason: str
    report_slot: str = ""  # one full status report per report slot (every 3 h, Berlin time)


def local_now(tz_name: str, now_utc: datetime | None = None) -> datetime:
    now_utc = now_utc or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    return now_utc.astimezone(ZoneInfo(tz_name))


def slot_id(local: datetime, normal_hours: int = 3, friday_minutes: int = 15) -> str:
    if local.weekday() == FRIDAY:
        minute = (local.minute // friday_minutes) * friday_minutes
        return f"fri:{local:%Y-%m-%d}T{local.hour:02d}:{minute:02d}"
    hour = (local.hour // normal_hours) * normal_hours
    return f"std:{local:%Y-%m-%d}T{hour:02d}"


def report_slot_id(local: datetime, report_hours: int = 3) -> str:
    """Same on every weekday, Fridays included: 00, 03, 06 ... 21 Berlin time."""
    hour = (local.hour // report_hours) * report_hours
    return f"rep:{local:%Y-%m-%d}T{hour:02d}"


def decide(
    last_slot: str | None,
    tz_name: str = "Europe/Berlin",
    normal_hours: int = 3,
    friday_minutes: int = 15,
    now_utc: datetime | None = None,
    force: bool = False,
    report_hours: int = 3,
) -> GateDecision:
    local = local_now(tz_name, now_utc)
    slot = slot_id(local, normal_hours, friday_minutes)
    rep = report_slot_id(local, report_hours)
    stamp = local.strftime("%a %Y-%m-%d %H:%M %Z")
    if force:
        return GateDecision(True, slot, stamp, "forced run", rep)
    if slot == last_slot:
        return GateDecision(False, slot, stamp, f"slot {slot} already checked", rep)
    return GateDecision(True, slot, stamp, f"new slot {slot}", rep)
