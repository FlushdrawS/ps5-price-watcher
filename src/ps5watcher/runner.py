"""Orchestrates one watcher run.

Messages per run
  * Report slot not yet reported (every 3 h Berlin time, Fridays included):
      one full status report = all sources + any changes since the last check.
  * Otherwise (the extra 15-minute checks on Fridays):
      immediate alerts only, and only if something meaningful changed.
Nothing is ever sent twice: events are de-duplicated in alerts.py, the report
once per report slot. If Telegram fails, state is not saved so the same
messages are regenerated on the next run.
"""

from __future__ import annotations

import logging
import os
import random
import time
from datetime import datetime, timezone

from .alerts import evaluate
from .config import AppConfig
from .fetch import FetcherPool
from .history import HistoryStore
from .models import CheckResult
from .notify import (
    ConsoleNotifier,
    NotificationError,
    TelegramNotifier,
    build_messages,
    build_report,
    summary_markdown,
)
from .paths import history_dir, state_file
from .schedule import decide
from .sources import check_source
from .state import StateStore

log = logging.getLogger(__name__)


def make_notifier(dry_run: bool):
    enabled = os.environ.get("TELEGRAM_ENABLED", "").strip().lower() == "true"
    if dry_run or not enabled:
        return ConsoleNotifier()
    return TelegramNotifier(os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", ""))


def needs_browser(cfg: AppConfig) -> bool:
    return any(s.enabled and s.url and s.fetcher == "playwright" for s in cfg.sources)


def write_step_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def check_all(cfg: AppConfig, pool, only: set[str] | None = None, now: datetime | None = None) -> list[CheckResult]:
    now = now or datetime.now(timezone.utc)
    checked_at = now.replace(microsecond=0).isoformat()
    results: list[CheckResult] = []
    fetched_before = False
    for src in cfg.sources:
        if only and src.id not in only:
            continue
        if fetched_before and src.enabled and src.url and cfg.settings.delay_between_sources_s > 0:
            time.sleep(cfg.settings.delay_between_sources_s * (0.5 + random.random()))
        result, fetch = check_source(src, pool, cfg.product, cfg.settings, checked_at)
        fetched_before = fetched_before or fetch is not None
        log.info(
            "%-11s %-11s price=%s total=%s stock=%s %s",
            src.id, result.verification.value, result.price, result.total,
            result.availability.value, "; ".join(result.reasons)[:160],
        )
        results.append(result)
    return results


def run(
    cfg: AppConfig,
    store: StateStore | None = None,
    notifier=None,
    force: bool = False,
    only: set[str] | None = None,
    pool=None,
    now: datetime | None = None,
    history: HistoryStore | None = None,
    force_report: bool = False,
) -> int:
    now = now or datetime.now(timezone.utc)
    store = store or StateStore(state_file())
    history = history or HistoryStore(history_dir())
    notifier = notifier or ConsoleNotifier()
    state = store.load()
    s = cfg.settings
    decision = decide(
        state.get("last_slot"), s.timezone, s.normal_interval_hours, s.friday_interval_minutes,
        now, force or bool(only), s.report_interval_hours,
    )
    log.info("Berlin time %s - %s", decision.local_time, decision.reason)
    if not decision.due:
        return 0

    if state.get("alert_channel") != notifier.channel:
        # Alerts recorded during dry runs must not suppress the first real Telegram alerts.
        state["alerts"] = {}
        state["alert_channel"] = notifier.channel
        state["last_report_slot"] = None

    own_pool = pool is None
    pool = pool or FetcherPool(timeout=s.request_timeout_s)
    try:
        results = check_all(cfg, pool, only, now)
    finally:
        if own_pool:
            pool.close()

    # Observations are facts regardless of notification success.
    try:
        history.append(results, now)
        history.prune(s.history_retention_days, now)
    except OSError as exc:
        log.warning("Could not write history: %s", exc)

    events = evaluate(results, state, s, now)
    send_report = not only and (force_report or state.get("last_report_slot") != decision.report_slot)
    if send_report:
        messages = build_report(results, events, s.target_total_eur, decision.local_time)
    else:
        messages = build_messages(events, s.target_total_eur, decision.local_time)

    summary = summary_markdown(
        results, f"PS5 watcher - {decision.local_time} - {len(events)} event(s) - "
        f"{'report' if send_report else 'alerts only'}"
    )
    print(summary)

    try:
        notifier.send(messages)
    except NotificationError as exc:
        log.error("Notification failed, state not saved: %s", exc)
        write_step_summary(summary + f"\n**Notification failed:** {exc}\n")
        return 1

    if not only:
        state["last_slot"] = decision.slot
    if send_report:
        state["last_report_slot"] = decision.report_slot
    state["last_run_utc"] = now.replace(microsecond=0).isoformat()
    store.save(state)
    write_step_summary(summary)
    log.info("Done: %d event(s), %d message(s) via %s", len(events), len(messages), notifier.channel)
    return 0
