from decimal import Decimal

import pytest

from ps5watcher import notify
from ps5watcher.alerts import Event, EventType
from ps5watcher.models import (
    Availability,
    CheckResult,
    ExtractedOffer,
    FetchStatus,
    MatchResult,
    Verification,
)
from ps5watcher.notify import (
    NotificationError,
    TelegramNotifier,
    build_messages,
    format_event,
    html_to_text,
    summary_markdown,
)


def result(verification=Verification.VERIFIED, total="489.00", name="Shop <&>"):
    offer = ExtractedOffer(title="PS5", price=Decimal("489.00"), currency="EUR",
                           availability=Availability.IN_STOCK, method="jsonld")
    return CheckResult(
        source_id="shop", source_name=name, kind="retailer", url="https://shop.example/p?a=1&b=2",
        fetch_status=FetchStatus.OK, verification=verification, match=MatchResult.MATCH,
        reasons=["shipping cost unknown"] if verification != Verification.VERIFIED else [],
        offer=offer, total=Decimal(total) if total else None,
    )


def test_target_message_contains_link_and_price():
    text = format_event(Event(EventType.TARGET_HIT, result()), Decimal("500"))
    assert "489,00 €" in text
    assert 'href="https://shop.example/p?a=1&amp;b=2"' in text
    assert "Shop &lt;&amp;&gt;" in text  # HTML-escaped for Telegram
    assert "Verified" in text


def test_candidate_message_says_why():
    text = format_event(Event(EventType.CANDIDATE, result(Verification.UNVERIFIED, total=None)), Decimal("500"))
    assert "Unverified listing" in text
    assert "shipping cost unknown" in text
    assert "check manually" in text


def test_price_drop_message():
    e = Event(EventType.PRICE_DROP, result(total="529.00"), previous=Decimal("569.00"))
    text = html_to_text(format_event(e, Decimal("500")))
    assert "569,00 € → 529,00 €" in text
    assert "-40,00 €" in text


def test_messages_split_under_telegram_limit():
    events = [Event(EventType.CANDIDATE, result(Verification.UNVERIFIED, total=None, name=f"S{i}" * 30))
              for i in range(40)]
    msgs = build_messages(events, Decimal("500"), "Fri 12:00")
    assert len(msgs) > 1
    assert all(len(m) <= notify.TELEGRAM_LIMIT for m in msgs)
    assert all(m.count("<a ") == m.count("</a>") for m in msgs)


def test_no_events_no_messages():
    assert build_messages([], Decimal("500"), "x") == []


def test_summary_markdown_lists_sources():
    md = summary_markdown([result()], "Header")
    assert "| Shop <&> | ✅ verified |" in md


class FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


def test_telegram_success(monkeypatch):
    sent = []

    def fake_post(url, data, timeout):
        sent.append((url, data))
        return FakeResp(200, {"ok": True})

    monkeypatch.setattr(notify.requests, "post", fake_post)
    TelegramNotifier("123:ABC", "42").send(["hello"])
    assert sent[0][1]["chat_id"] == "42"
    assert sent[0][1]["parse_mode"] == "HTML"


def test_telegram_error_does_not_leak_token(monkeypatch):
    monkeypatch.setattr(notify.requests, "post", lambda *a, **k: FakeResp(401, {"description": "Unauthorized"}))
    with pytest.raises(NotificationError) as exc:
        TelegramNotifier("123:SECRET", "42").send(["hello"])
    assert "SECRET" not in str(exc.value)


def test_telegram_requires_credentials():
    with pytest.raises(NotificationError):
        TelegramNotifier("", "")
