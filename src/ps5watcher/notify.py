"""Message formatting and delivery (Telegram or console dry-run)."""

from __future__ import annotations

import html
import logging
import re
import time

import requests

from .alerts import Event, EventType
from .models import CheckResult, Verification
from .prices import fmt_eur

log = logging.getLogger(__name__)

TELEGRAM_LIMIT = 4000  # hard limit is 4096; keep headroom


class NotificationError(RuntimeError):
    pass


def esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def _link(r: CheckResult) -> str:
    return f'<a href="{esc(r.url)}">Open product page</a>'


def _price_line(r: CheckResult) -> str:
    if r.total is not None and r.offer and r.offer.price is not None:
        ship = r.total - r.offer.price
        return f"{fmt_eur(r.total)} total ({fmt_eur(r.offer.price)} + {fmt_eur(ship)} shipping)"
    return f"{fmt_eur(r.price)} (shipping unknown)"


def _stock(r: CheckResult) -> str:
    return {
        "in_stock": "In stock",
        "out_of_stock": "Out of stock",
        "preorder": "Pre-order",
        "unknown": "Availability unknown",
    }[r.availability.value]


def format_event(e: Event, target_eur) -> str:
    r = e.result
    name = f"<b>{esc(r.source_name)}</b>"
    if e.type == EventType.TARGET_HIT:
        return (
            f"🚨 <b>PS5 Digital 825 GB at or below {esc(fmt_eur(target_eur))}</b>\n"
            f"{name}: {esc(_price_line(r))}\n"
            f"✅ Verified price · {esc(_stock(r))}\n{_link(r)}"
        )
    if e.type == EventType.CANDIDATE:
        label = "Price comparison (not a retailer)" if r.verification == Verification.COMPARISON else "Unverified listing"
        why = "; ".join(r.reasons[:3])
        return (
            f"⚠️ <b>{label} at or below {esc(fmt_eur(target_eur))} - check manually</b>\n"
            f"{name}: {esc(_price_line(r))} · {esc(_stock(r))}\n"
            f"<i>Why not verified: {esc(why)}</i>\n{_link(r)}"
        )
    if e.type == EventType.PRICE_DROP:
        new = r.price_basis
        diff = (e.previous - new) if (e.previous is not None and new is not None) else None
        pct = (diff / e.previous * 100) if diff is not None and e.previous else None
        tag = "comparison" if r.verification == Verification.COMPARISON else "verified"
        pct_txt = f", -{pct:.1f} %".replace(".", ",") if pct is not None else ""
        return (
            f"📉 <b>Price drop</b> ({tag})\n"
            f"{name}: {esc(fmt_eur(e.previous))} → {esc(fmt_eur(new))} (-{esc(fmt_eur(diff))}{esc(pct_txt)})\n"
            f"{esc(_stock(r))}\n{_link(r)}"
        )
    if e.type == EventType.DEAL_ENDED:
        return (
            f"⌛ <b>Deal ended</b>: {name} - now {esc(_short_status(r))}\n{_link(r)}"
        )
    if e.type == EventType.BACK_IN_STOCK:
        tag = "verified" if r.verification == Verification.VERIFIED else "unverified"
        return f"📦 <b>Back in stock</b> ({tag})\n{name}: {esc(_price_line(r))}\n{_link(r)}"
    if e.type == EventType.OUT_OF_STOCK:
        return f"❌ <b>Out of stock</b>: {name}"
    if e.type == EventType.SOURCE_FAILING:
        why = "; ".join(r.reasons[:2])
        return f"🛠 <b>Source failing</b>: {name} - {esc(e.note)}\n<i>{esc(why)}</i>"
    if e.type == EventType.SOURCE_RECOVERED:
        return f"✅ <b>Source working again</b>: {name}"
    return f"{esc(e.type.value)}: {name}"


def build_messages(events: list[Event], target_eur, local_time: str) -> list[str]:
    if not events:
        return []
    blocks = [format_event(e, target_eur) for e in events]
    footer = f"\n\n<i>Checked {esc(local_time)}</i>"
    messages, current = [], ""
    # Split only between blocks so HTML tags are never cut in half.
    # (A single block is a few hundred characters at most.)
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) + len(footer) > TELEGRAM_LIMIT and current:
            messages.append(current + footer)
            current = block
        else:
            current = candidate
    if current:
        messages.append(current + footer)
    return messages


def _short_status(r: CheckResult) -> str:
    if r.verification in (Verification.ERROR, Verification.REJECTED):
        return (r.reasons[0] if r.reasons else r.verification.value)[:90]
    if r.price is None:
        return "not offered"
    return f"{_price_line(r)}, {_stock(r).lower()}"


STATUS_ICON = {
    Verification.VERIFIED: "✅",
    Verification.UNVERIFIED: "⚠️",
    Verification.COMPARISON: "🔎",
    Verification.REJECTED: "🚫",
    Verification.ERROR: "❌",
    Verification.SKIPPED: "⏭",
}


def _report_line(r: CheckResult) -> str:
    icon = STATUS_ICON[r.verification]
    name = f'<a href="{esc(r.url)}">{esc(r.source_name)}</a>' if r.url else esc(r.source_name)
    if r.verification == Verification.SKIPPED:
        return f"{icon} {name}: not configured"
    if r.verification in (Verification.ERROR, Verification.REJECTED):
        label = "wrong product" if r.verification == Verification.REJECTED else "check failed"
        why = (r.reasons[0] if r.reasons else "")[:80]
        return f"{icon} {name}: {label} - <i>{esc(why)}</i>"
    if r.price is None:
        line = f"{icon} {name}: not offered"
    elif r.verification == Verification.COMPARISON:
        seller = f" ({r.offer.seller})" if r.offer and r.offer.seller else ""
        line = f"{icon} {name}: from {esc(fmt_eur(r.price_basis))}{esc(seller)} · comparison only"
    else:
        line = f"{icon} {name}: {esc(_price_line(r))} · {esc(_stock(r).lower())}"
    if r.verification == Verification.UNVERIFIED and r.price is not None and r.reasons:
        specific = [x for x in r.reasons if not x.startswith("integration not live-tested")]
        main = (specific or r.reasons)[0][:90]
        more = len(r.reasons) - 1
        line += f"\n      <i>unverified: {esc(main)}{f' (+{more} more)' if more else ''}</i>"
    return line


def build_report(results: list[CheckResult], events: list[Event], target_eur, local_time: str) -> list[str]:
    """Full status report (sent once per 3-hour Berlin slot, Fridays included)."""
    header = (
        f"📊 <b>PS5 Digital 825 GB - status report</b>\n"
        f"<i>{esc(local_time)} · target ≤ {esc(fmt_eur(target_eur))} incl. shipping</i>"
    )
    parts = [header]
    if events:
        parts.append("<b>Changes</b>")
        parts.extend(format_event(e, target_eur) for e in events)  # one part each, so splitting stays safe
    parts.append("<b>Sources</b>\n" + "\n".join(_report_line(r) for r in results))
    deals = [r for r in results if r.verification == Verification.VERIFIED and r.in_stock and r.total is not None]
    if deals:
        best = min(deals, key=lambda r: r.total)
        parts.append(f"💶 Cheapest verified in stock: <b>{esc(best.source_name)}</b> {esc(fmt_eur(best.total))}")
    else:
        parts.append("💶 Cheapest verified in stock: none")
    messages, current = [], ""
    for part in parts:
        candidate = f"{current}\n\n{part}" if current else part
        if len(candidate) > TELEGRAM_LIMIT and current:
            messages.append(current)
            current = part
        else:
            current = candidate
    if current:
        messages.append(current)
    return messages


def html_to_text(message: str) -> str:
    text = re.sub(r'<a href="([^"]+)">([^<]*)</a>', lambda m: m.group(1) if m.group(2) == "Open product page" else f"{m.group(2)} ({m.group(1)})", message)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


class ConsoleNotifier:
    channel = "console"

    def send(self, messages: list[str]) -> None:
        for m in messages:
            print("\n----- notification (dry run, not sent) -----")
            print(html_to_text(m))
        if messages:
            print("--------------------------------------------")


class TelegramNotifier:
    channel = "telegram"

    def __init__(self, token: str, chat_id: str, timeout: int = 20):
        if not token or not chat_id:
            raise NotificationError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
        self.timeout = timeout

    def send(self, messages: list[str]) -> None:
        for m in messages:
            self._send_one(m)

    def _send_one(self, text: str, attempt: int = 0) -> None:
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            resp = requests.post(self.url, data=payload, timeout=self.timeout)
        except requests.RequestException as exc:
            if attempt < 2:
                time.sleep(3)
                return self._send_one(text, attempt + 1)
            # never include the URL: it contains the bot token
            raise NotificationError(f"Telegram request failed: {type(exc).__name__}") from None
        if resp.status_code == 429 and attempt < 2:
            retry = 5
            try:
                retry = int(resp.json().get("parameters", {}).get("retry_after", 5))
            except ValueError:
                pass
            time.sleep(min(retry, 60))
            return self._send_one(text, attempt + 1)
        if resp.status_code != 200:
            try:
                desc = resp.json().get("description", "")
            except ValueError:
                desc = resp.text[:200]
            raise NotificationError(f"Telegram API error {resp.status_code}: {desc}")


def summary_markdown(results: list[CheckResult], header: str) -> str:
    icon = {
        Verification.VERIFIED: "✅ verified",
        Verification.UNVERIFIED: "⚠️ unverified",
        Verification.COMPARISON: "🔎 comparison",
        Verification.REJECTED: "🚫 wrong product",
        Verification.ERROR: "❌ error",
        Verification.SKIPPED: "⏭ skipped",
    }
    lines = [
        f"### {header}",
        "",
        "| Source | Status | Price | Total | Stock | Notes |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        notes = "; ".join(r.reasons).replace("|", "/")[:220]
        stock = r.availability.value if r.offer else "-"
        lines.append(
            f"| {r.source_name} | {icon[r.verification]} | {fmt_eur(r.price)} | "
            f"{fmt_eur(r.total)} | {stock} | {notes} |"
        )
    return "\n".join(lines) + "\n"
