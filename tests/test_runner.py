"""End-to-end runs with a fake network (offline)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from conftest import FakePool, load, make_src

from ps5watcher.config import AppConfig
from ps5watcher.history import HistoryStore
from ps5watcher.notify import NotificationError
from ps5watcher.runner import run
from ps5watcher.state import StateStore

FRI = datetime(2026, 11, 27, 12, 1, tzinfo=timezone.utc)  # Friday 13:01 CET
TUE = datetime(2026, 11, 24, 12, 1, tzinfo=timezone.utc)  # Tuesday 13:01 CET


class RecordingNotifier:
    channel = "test"

    def __init__(self, fail=False):
        self.fail = fail
        self.batches: list[list[str]] = []

    def send(self, messages):
        if self.fail and messages:
            raise NotificationError("boom")
        if messages:
            self.batches.append(list(messages))

    @property
    def text(self):
        return "\n".join(m for b in self.batches for m in b)


def make_cfg(settings, spec):
    sources = (
        make_src(id="good", name="Good Shop", url="https://good.example/p"),
        make_src(id="blocked", name="Blocked Shop", url="https://blocked.example/p"),
        make_src(id="bundle", name="Bundle Shop", url="https://bundle.example/p"),
        make_src(id="todo", name="Not configured", url=""),
        make_src(id="idealo", name="idealo", kind="comparison", url="https://idealo.example/p"),
    )
    return AppConfig(settings=settings, product=spec, sources=sources)


PAGES = {
    "https://good.example/p": (200, load("jsonld_in_stock.html")),
    "https://blocked.example/p": (200, load("blocked_cloudflare.html")),
    "https://bundle.example/p": (200, load("jsonld_bundle.html")),
    "https://idealo.example/p": (200, load("jsonld_aggregate.html")),
}


def go(cfg, tmp_path, notifier, now, pages=PAGES, **kw):
    pool = FakePool(pages)
    code = run(cfg, StateStore(tmp_path / "state.json"), notifier, pool=pool, now=now,
               history=HistoryStore(tmp_path / "history"), **kw)
    return code, pool


def test_first_run_sends_full_report_with_alerts(tmp_path, settings, spec):
    n = RecordingNotifier()
    code, pool = go(make_cfg(settings, spec), tmp_path, n, FRI)
    assert code == 0 and len(n.batches) == 1
    text = n.text
    assert "status report" in text
    assert "PS5 Digital 825 GB at or below" in text and "479,00 €" in text      # verified purchase alert
    assert "Price comparison (not a retailer)" in text                          # idealo candidate
    assert "Bundle Shop" in text and "wrong product" in text                    # listed in report only
    assert "PS5 Digital 825 GB at or below 500,00 €</b>\nBundle" not in text
    assert "Not configured" in text and "not configured" in text
    assert "https://todo" not in "".join(pool.fetcher.calls)


def test_friday_quarter_hours_send_only_changes(tmp_path, settings, spec):
    cfg = make_cfg(settings, spec)
    n = RecordingNotifier()
    go(cfg, tmp_path, n, FRI)                                   # 13:01 report slot 12
    go(cfg, tmp_path, n, FRI + timedelta(minutes=15))           # 13:16 no change -> silent
    assert len(n.batches) == 1
    cheaper = dict(PAGES)
    cheaper["https://good.example/p"] = (200, load("jsonld_in_stock.html")
                                         .replace('"479.00"', '"459.00"').replace("479,00 €", "459,00 €"))
    go(cfg, tmp_path, n, FRI + timedelta(minutes=30), pages=cheaper)   # 13:31 lower price -> immediate alert
    assert len(n.batches) == 2
    assert "status report" not in n.batches[1][0]
    assert "459,00 €" in n.batches[1][0]


def test_report_every_three_hours_even_without_changes(tmp_path, settings, spec):
    cfg = make_cfg(settings, spec)
    n = RecordingNotifier()
    go(cfg, tmp_path, n, TUE)                                   # Tue 13:01 slot 12
    go(cfg, tmp_path, n, TUE + timedelta(minutes=40))           # same slot -> gate skips
    go(cfg, tmp_path, n, TUE + timedelta(hours=2))              # 15:01 slot 15 -> report again
    assert len(n.batches) == 2
    assert all("status report" in b[0] for b in n.batches)
    # second report has no duplicate purchase alert
    assert "at or below" not in n.batches[1][0].split("<b>Sources</b>")[0]


def test_friday_report_at_three_hour_boundary(tmp_path, settings, spec):
    cfg = make_cfg(settings, spec)
    n = RecordingNotifier()
    go(cfg, tmp_path, n, FRI)                                   # 13:01 report (slot 12)
    go(cfg, tmp_path, n, FRI + timedelta(minutes=45))           # 13:46 silent
    go(cfg, tmp_path, n, FRI + timedelta(hours=2, minutes=1))   # 15:02 new report slot 15
    assert len(n.batches) == 2 and "status report" in n.batches[1][0]


def test_gate_prevents_double_check(tmp_path, settings, spec):
    cfg = make_cfg(settings, spec)
    n = RecordingNotifier()
    _, p1 = go(cfg, tmp_path, n, FRI)
    _, p2 = go(cfg, tmp_path, n, FRI + timedelta(minutes=5))
    assert p1.fetcher.calls and not p2.fetcher.calls


def test_notification_failure_keeps_old_state(tmp_path, settings, spec):
    cfg = make_cfg(settings, spec)
    assert go(cfg, tmp_path, RecordingNotifier(fail=True), FRI)[0] == 1
    assert not (tmp_path / "state.json").exists()
    n = RecordingNotifier()
    go(cfg, tmp_path, n, FRI + timedelta(minutes=15))
    assert "479,00 €" in n.text and "status report" in n.text


def test_switching_channel_resets_alert_memory(tmp_path, settings, spec):
    cfg = make_cfg(settings, spec)
    dry = RecordingNotifier()
    dry.channel = "console"
    go(cfg, tmp_path, dry, FRI)
    real = RecordingNotifier()
    real.channel = "telegram"
    go(cfg, tmp_path, real, FRI + timedelta(minutes=15))
    assert "at or below" in real.text and "status report" in real.text


def test_only_does_not_advance_slot_or_report(tmp_path, settings, spec):
    cfg = make_cfg(settings, spec)
    n = RecordingNotifier()
    go(cfg, tmp_path, n, FRI, only={"good"})
    st = StateStore(tmp_path / "state.json").load()
    assert st["last_slot"] is None and st.get("last_report_slot") is None
    assert "status report" not in n.text


def test_history_written_every_check(tmp_path, settings, spec):
    cfg = make_cfg(settings, spec)
    n = RecordingNotifier()
    go(cfg, tmp_path, n, FRI)
    go(cfg, tmp_path, n, FRI + timedelta(minutes=15))
    rows = HistoryStore(tmp_path / "history").read()
    assert len(rows) == 8  # 4 fetched sources x 2 checks, skipped source not logged
    good = [r for r in rows if r["source"] == "good"]
    assert good[0]["price"] == "479.00" and good[0]["status"] == "verified"
    assert good[0]["t"].startswith("2026-11-27T12:01")


def test_corrupt_state_recovers(tmp_path, settings, spec):
    (tmp_path / "state.json").write_text("{not json")
    assert go(make_cfg(settings, spec), tmp_path, RecordingNotifier(), FRI)[0] == 0
    assert (tmp_path / "state.corrupt.json").exists()


def test_total_is_decimal_safe(tmp_path, settings, spec):
    go(make_cfg(settings, spec), tmp_path, RecordingNotifier(), FRI)
    st = StateStore(tmp_path / "state.json").load()
    assert Decimal(st["sources"]["good"]["total"]) == Decimal("479.00")
