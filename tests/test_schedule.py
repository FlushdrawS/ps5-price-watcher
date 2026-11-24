from datetime import datetime, timezone

from ps5watcher.schedule import decide, local_now, slot_id


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_friday_slots_winter():
    # Thu 2026-11-26 23:20 UTC == Fri 00:20 CET -> Friday slot
    d = decide(None, now_utc=utc(2026, 11, 26, 23, 20))
    assert d.slot == "fri:2026-11-27T00:15"
    assert d.due


def test_friday_ends_at_berlin_midnight_summer():
    # Fri 2026-07-03 22:10 UTC == Sat 00:10 CEST -> back to 3-hour slots
    d = decide(None, now_utc=utc(2026, 7, 3, 22, 10))
    assert d.slot == "std:2026-07-04T00"


def test_friday_starts_at_berlin_midnight_summer():
    # Thu 2026-07-02 22:05 UTC == Fri 00:05 CEST
    assert decide(None, now_utc=utc(2026, 7, 2, 22, 5)).slot == "fri:2026-07-03T00:00"


def test_normal_three_hour_slots():
    # Mon 2026-11-23 10:59 UTC == 11:59 CET -> slot 09
    assert decide(None, now_utc=utc(2026, 11, 23, 10, 59)).slot == "std:2026-11-23T09"
    assert decide(None, now_utc=utc(2026, 11, 23, 11, 0)).slot == "std:2026-11-23T12"


def test_same_slot_not_due_twice():
    first = decide(None, now_utc=utc(2026, 11, 23, 9, 7))
    again = decide(first.slot, now_utc=utc(2026, 11, 23, 9, 40))
    assert first.due and not again.due


def test_delayed_cron_still_runs_once():
    # cron meant for 09:07 UTC arrives 35 min late: still a new slot, and only once
    last = decide(None, now_utc=utc(2026, 11, 23, 6, 7)).slot
    late = decide(last, now_utc=utc(2026, 11, 23, 9, 42))
    assert late.due


def test_friday_every_15_minutes():
    t1 = decide(None, now_utc=utc(2026, 11, 27, 12, 1))
    t2 = decide(t1.slot, now_utc=utc(2026, 11, 27, 12, 14))
    t3 = decide(t1.slot, now_utc=utc(2026, 11, 27, 12, 16))
    assert t1.due and not t2.due and t3.due


def test_force():
    d = decide("std:2026-11-23T09", now_utc=utc(2026, 11, 23, 9, 30), force=True)
    assert d.due


def test_dst_change_day():
    # Sun 2026-10-25: clocks go back 03:00 CEST -> 02:00 CET
    local = local_now("Europe/Berlin", utc(2026, 10, 25, 1, 30))
    assert slot_id(local) == "std:2026-10-25T00"
