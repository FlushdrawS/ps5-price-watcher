from datetime import datetime, timedelta, timezone
from decimal import Decimal

from ps5watcher.alerts import EventType, evaluate
from ps5watcher.models import (
    Availability,
    CheckResult,
    ExtractedOffer,
    FetchStatus,
    MatchResult,
    Verification,
)
from ps5watcher.state import empty_state

T0 = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)


def res(price=None, total="auto", verification=Verification.VERIFIED, stock=Availability.IN_STOCK,
        sid="shop", kind="retailer", match=MatchResult.MATCH, reasons=None):
    offer = None
    if price is not None:
        offer = ExtractedOffer(title="PS5 Digital 825 GB", price=Decimal(str(price)), currency="EUR",
                               availability=stock, method="jsonld")
    if total == "auto":
        total = Decimal(str(price)) if price is not None else None
    elif total is not None:
        total = Decimal(str(total))
    return CheckResult(
        source_id=sid, source_name=sid.title(), kind=kind, url=f"https://{sid}.example/p",
        fetch_status=FetchStatus.OK if verification != Verification.ERROR else FetchStatus.BLOCKED,
        verification=verification, match=match, reasons=reasons or [], offer=offer, total=total,
    )


def types(events):
    return [e.type for e in events]


def test_target_hit_once_then_deduplicated(settings):
    st = empty_state()
    assert types(evaluate([res(489)], st, settings, T0)) == [EventType.TARGET_HIT]
    assert evaluate([res(489)], st, settings, T0 + timedelta(minutes=15)) == []
    assert evaluate([res(489)], st, settings, T0 + timedelta(hours=3)) == []


def test_target_refires_on_lower_price(settings):
    st = empty_state()
    evaluate([res(489)], st, settings, T0)
    ev = evaluate([res(469)], st, settings, T0 + timedelta(hours=1))
    assert EventType.TARGET_HIT in types(ev)


def test_target_reminder_after_24h(settings):
    st = empty_state()
    evaluate([res(489)], st, settings, T0)
    assert types(evaluate([res(489)], st, settings, T0 + timedelta(hours=24))) == [EventType.TARGET_HIT]


def test_blocked_check_does_not_reset_target(settings):
    st = empty_state()
    evaluate([res(489)], st, settings, T0)
    evaluate([res(verification=Verification.ERROR, reasons=["blocked"])], st, settings, T0 + timedelta(minutes=15))
    assert evaluate([res(489)], st, settings, T0 + timedelta(minutes=30)) == []


def test_target_rearms_after_condition_ends(settings):
    st = empty_state()
    evaluate([res(489)], st, settings, T0)
    evaluate([res(489, stock=Availability.OUT_OF_STOCK)], st, settings, T0 + timedelta(hours=1))
    ev = evaluate([res(489)], st, settings, T0 + timedelta(hours=2))
    assert EventType.TARGET_HIT in types(ev)


def test_above_target_no_target_alert(settings):
    st = empty_state()
    assert evaluate([res(529)], st, settings, T0) == []


def test_exactly_target_counts(settings):
    st = empty_state()
    assert types(evaluate([res(500)], st, settings, T0)) == [EventType.TARGET_HIT]


def test_unverified_candidate_labelled_separately(settings):
    st = empty_state()
    r = res(479, total=None, verification=Verification.UNVERIFIED, reasons=["shipping cost unknown"])
    assert types(evaluate([r], st, settings, T0)) == [EventType.CANDIDATE]
    assert evaluate([r], st, settings, T0 + timedelta(hours=3)) == []


def test_candidates_can_be_disabled(settings):
    from dataclasses import replace

    st = empty_state()
    s = replace(settings, notify_unverified_candidates=False)
    r = res(479, total=None, verification=Verification.UNVERIFIED)
    assert evaluate([r], st, s, T0) == []


def test_comparison_candidate(settings):
    st = empty_state()
    r = res(469, total=None, verification=Verification.COMPARISON, kind="comparison", sid="idealo",
            stock=Availability.UNKNOWN)
    assert types(evaluate([r], st, settings, T0)) == [EventType.CANDIDATE]


def test_significant_price_drop(settings):
    st = empty_state()
    evaluate([res(569)], st, settings, T0)
    ev = evaluate([res(549)], st, settings, T0 + timedelta(hours=3))
    assert types(ev) == [EventType.PRICE_DROP]
    assert ev[0].previous == Decimal("569")


def test_small_drop_ignored(settings):
    st = empty_state()
    evaluate([res(569)], st, settings, T0)
    assert evaluate([res(565)], st, settings, T0 + timedelta(hours=3)) == []


def test_drop_into_target_only_sends_target(settings):
    st = empty_state()
    evaluate([res(569)], st, settings, T0)
    assert types(evaluate([res(495)], st, settings, T0 + timedelta(hours=3))) == [EventType.TARGET_HIT]


def test_oscillating_price_not_spammed(settings):
    st = empty_state()
    evaluate([res(569)], st, settings, T0)
    assert types(evaluate([res(549)], st, settings, T0 + timedelta(hours=1))) == [EventType.PRICE_DROP]
    evaluate([res(569)], st, settings, T0 + timedelta(hours=2))
    assert evaluate([res(549)], st, settings, T0 + timedelta(hours=3)) == []


def test_unverified_prices_do_not_drive_drops(settings):
    st = empty_state()
    evaluate([res(569, verification=Verification.UNVERIFIED)], st, settings, T0)
    assert evaluate([res(529, verification=Verification.UNVERIFIED)], st, settings, T0 + timedelta(hours=3)) == []


def test_stock_changes(settings):
    st = empty_state()
    evaluate([res(549, stock=Availability.OUT_OF_STOCK)], st, settings, T0)
    assert types(evaluate([res(549)], st, settings, T0 + timedelta(hours=3))) == [EventType.BACK_IN_STOCK]
    ev = evaluate([res(549, stock=Availability.OUT_OF_STOCK)], st, settings, T0 + timedelta(hours=6))
    assert types(ev) == [EventType.OUT_OF_STOCK]


def test_no_stock_event_on_first_observation_or_unknown(settings):
    st = empty_state()
    assert evaluate([res(549)], st, settings, T0) == []
    assert evaluate([res(549, stock=Availability.UNKNOWN)], st, settings, T0 + timedelta(hours=3)) == []


def test_source_failing_once_per_streak_and_recovery(settings):
    st = empty_state()
    err = res(verification=Verification.ERROR, reasons=["blocked: cloudflare challenge"])
    for i in range(3):
        assert evaluate([err], st, settings, T0 + timedelta(hours=i)) == []
    assert types(evaluate([err], st, settings, T0 + timedelta(hours=3))) == [EventType.SOURCE_FAILING]
    assert evaluate([err], st, settings, T0 + timedelta(hours=4)) == []
    assert types(evaluate([res(549)], st, settings, T0 + timedelta(hours=5))) == [EventType.SOURCE_RECOVERED]


def test_skipped_sources_ignored(settings):
    st = empty_state()
    r = res(verification=Verification.SKIPPED)
    assert evaluate([r], st, settings, T0) == []
    assert "shop" not in st["sources"]


def test_events_sorted_by_priority(settings):
    st = empty_state()
    err = res(sid="b", verification=Verification.ERROR)
    for i in range(3):
        evaluate([err], st, settings, T0 + timedelta(minutes=i))
    ev = evaluate([err, res(489, sid="a")], st, settings, T0 + timedelta(minutes=5))
    assert types(ev) == [EventType.TARGET_HIT, EventType.SOURCE_FAILING]
