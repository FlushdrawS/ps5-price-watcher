"""Command line interface.

    python -m ps5watcher run                 # scheduled entry point (gated by Berlin time slots)
    python -m ps5watcher run --force --dry-run --report
    python -m ps5watcher probe               # live diagnostic of every source, no state, no alerts
    python -m ps5watcher probe --source alternate --save-html debug --record
    python -m ps5watcher probe --source alternate --file debug/alternate.html   # offline re-parse
    python -m ps5watcher status              # readiness checklist per source
    python -m ps5watcher history --days 7 [--source sony] [--csv out.csv]
    python -m ps5watcher gate                # same as `python -m ps5watcher.gate`
    python -m ps5watcher test-telegram       # send one test message (only after activation)
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import PROJECT_ROOT, ConfigError, load_config
from .paths import data_dir, evidence_dir, history_dir, state_file


def load_dotenv(path: Path = PROJECT_ROOT / ".env") -> None:
    """Minimal .env support for local testing (KEY=VALUE lines). Real env vars win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    # urllib3 debug logs would print request URLs - the Telegram URL contains the bot token.
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def cmd_gate(args, cfg) -> int:
    from .gate import main as gate_main

    return gate_main(["--force"] if args.force else [])


def cmd_run(args, cfg) -> int:
    from .notify import NotificationError
    from .runner import make_notifier, run

    only = set(args.only.split(",")) if args.only else None
    try:
        notifier = make_notifier(args.dry_run)
    except NotificationError as exc:
        logging.error("%s", exc)
        return 2
    return run(cfg, notifier=notifier, force=args.force, only=only, force_report=args.report)


def _print_candidates(html: str) -> None:
    from .extract import extract_candidates

    cands = extract_candidates(html)
    print(f"  structured offers on page: {len(cands)}")
    for c in cands[:6]:
        print(
            f"    - [{c.method}] {c.title!r} price={c.price} {c.currency} "
            f"avail={c.availability.value} gtin={c.gtin} cond={c.condition} "
            f"ship={c.shipping} seller={c.seller!r} offers={c.offer_count}"
        )


def cmd_probe(args, cfg) -> int:
    from .evidence import record
    from .fetch import FetcherPool
    from .models import FetchResult, FetchStatus
    from .sources import check_source
    from .sources.base import extract_offer
    from .verify import evaluate_offer

    sources = [cfg.source(args.source)] if args.source else list(cfg.sources)
    if args.fetcher:
        sources = [dataclasses.replace(s, fetcher=args.fetcher) for s in sources]
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    save_dir = Path(args.save_html) if args.save_html else None
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)
    pool = FetcherPool(timeout=cfg.settings.request_timeout_s)
    try:
        for src in sources:
            print(f"\n== {src.id} ({src.name}) ==")
            if args.file:
                html = Path(args.file).read_text(encoding="utf-8", errors="replace")
                fetch = FetchResult(src.url or args.file, FetchStatus.OK, 200, html, None, None, "file")
                offer = extract_offer(src, html, cfg.product, None)
                result = evaluate_offer(src, fetch, offer, cfg.product, cfg.settings, now)
            else:
                if not src.url:
                    print("  SKIPPED: no URL configured.")
                    if src.notes:
                        print(f"  note: {src.notes}")
                    continue
                result, fetch = check_source(src, pool, cfg.product, cfg.settings, now)
            print(f"  url:        {src.url}")
            if fetch:
                print(f"  fetcher:    {fetch.fetcher}   HTTP {fetch.http_status}   fetch={fetch.status.value}")
                if fetch.final_url and fetch.final_url != src.url:
                    print(f"  final url:  {fetch.final_url}")
                if fetch.error:
                    print(f"  error:      {fetch.error}")
                if fetch.html:
                    print(f"  html size:  {len(fetch.html):,} chars")
                    _print_candidates(fetch.html)
                    if save_dir and not args.file:
                        out = save_dir / f"{src.id}.html"
                        out.write_text(fetch.html, encoding="utf-8")
                        print(f"  saved html: {out}")
            o = result.offer
            if o:
                print(f"  chosen:     [{o.method}] {o.title!r}")
                print(f"              price={o.price} {o.currency}  shipping={o.shipping}  total={result.total}")
                print(f"              availability={o.availability.value}  gtin={o.gtin}  seller={o.seller!r}"
                      f"  marketplace={o.is_marketplace}  price_on_page={o.price_visible}")
                if o.availability_note:
                    print(f"              note: {o.availability_note}")
                for n in o.notes:
                    print(f"              note: {n}")
            print(f"  match:      {result.match.value}")
            print(f"  RESULT:     {result.verification.value.upper()}")
            for reason in result.reasons:
                print(f"    - {reason}")
            if args.record and not args.file:
                path = record(result, fetch, evidence_dir(), where=args.where or "")
                print(f"  evidence:   {path}")
    finally:
        pool.close()
    return 0


def cmd_status(args, cfg) -> int:
    from .state import StateStore

    s = cfg.settings
    print(f"Target: {s.target_total_eur} EUR incl. shipping | {s.timezone} | checks every "
          f"{s.normal_interval_hours} h, Fridays every {s.friday_interval_minutes} min | "
          f"report every {s.report_interval_hours} h")
    print(f"Expected EANs: {sorted(cfg.product.expected_gtins) or 'none'}")
    print()
    print(f"{'id':<11} {'kind':<10} {'url':<4} {'identity':<9} {'tested':<7} {'shipping':<13} {'seller policy':<22} on")
    for src in cfg.sources:
        if src.shipping_eur is not None:
            ship = f"{src.shipping_eur} EUR"
        elif src.free_shipping_from_eur is not None:
            ship = f"free>={src.free_shipping_from_eur}"
        else:
            ship = "from page/?"
        if src.is_comparison:
            policy = "n/a (comparison)"
        elif src.required_seller:
            policy = "must be " + "/".join(src.required_seller)
        elif src.first_party_shop:
            policy = "shop is seller"
        else:
            policy = "UNVERIFIED"
        print(
            f"{src.id:<11} {src.kind:<10} {'yes' if src.url else 'NO':<4} "
            f"{'url-ok' if src.url_identity_verified else '-':<9} "
            f"{'yes' if src.integration_tested else 'NO':<7} {ship:<13} {policy:<22} {src.enabled}"
        )
    print("\nA retailer can only produce VERIFIED purchase alerts when url=yes and tested=yes, shipping is known,")
    print("the seller policy passes and the page itself shows the price and stock.")
    state = StateStore(state_file()).load()
    print(f"\nData dir: {data_dir()}  last slot: {state.get('last_slot')}  "
          f"last report: {state.get('last_report_slot')}  channel: {state.get('alert_channel')}")
    return 0


def cmd_history(args, cfg) -> int:
    from .history import HistoryStore

    store = HistoryStore(history_dir())
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    rows = store.read(since=since, source=args.source)
    if args.csv:
        store.export_csv(rows, args.csv)
        print(f"Wrote {len(rows)} rows to {args.csv}")
        return 0
    for r in rows[-args.limit:]:
        print(f"{r['t']}  {r['source']:<11} {r['status']:<11} price={r['price']} total={r['total']} "
              f"stock={r['stock']} seller={r.get('seller')}")
    print(f"({len(rows)} observation(s) in the last {args.days} day(s); showing up to {args.limit})")
    return 0


def cmd_test_telegram(args, cfg) -> int:
    from .notify import NotificationError, TelegramNotifier, html_to_text

    try:
        n = TelegramNotifier(os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", ""))
        msg = "✅ <b>PS5 Price Watcher</b>: test message. Telegram delivery works."
        n.send([msg])
    except NotificationError as exc:
        print(f"FAILED: {exc}")
        return 1
    print("Sent:", html_to_text(msg))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ps5watcher", description="PS5 Digital 825 GB price watcher")
    parser.add_argument("--config", help="path to sources.toml")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("gate", help="is a check due now?")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("run", help="check all sources and notify")
    p.add_argument("--force", action="store_true", help="ignore the time-slot gate")
    p.add_argument("--dry-run", action="store_true", help="print notifications instead of sending")
    p.add_argument("--report", action="store_true", help="send the full status report even if already sent this slot")
    p.add_argument("--only", help="comma-separated source ids (implies --force, no report, does not advance the slot)")

    p = sub.add_parser("probe", help="live diagnostics, no state and no notifications")
    p.add_argument("--source", help="source id")
    p.add_argument("--save-html", metavar="DIR", help="save fetched HTML for inspection")
    p.add_argument("--file", help="parse a saved HTML file instead of fetching (requires --source)")
    p.add_argument("--fetcher", choices=["http", "playwright"], help="override the configured fetcher")
    p.add_argument("--record", action="store_true", help="write an evidence JSON file per source")
    p.add_argument("--where", help="label for the evidence file, e.g. 'home DSL' or 'github-actions'")

    sub.add_parser("status", help="readiness checklist")

    p = sub.add_parser("history", help="show or export stored observations")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--source")
    p.add_argument("--limit", type=int, default=60)
    p.add_argument("--csv", help="export to CSV file")

    sub.add_parser("test-telegram", help="send a test message")

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    load_dotenv()
    if args.config:
        os.environ["PS5W_CONFIG"] = args.config
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    if args.command == "probe" and args.file and not args.source:
        parser.error("--file requires --source")

    handlers = {
        "gate": cmd_gate,
        "run": cmd_run,
        "probe": cmd_probe,
        "status": cmd_status,
        "history": cmd_history,
        "test-telegram": cmd_test_telegram,
    }
    return handlers[args.command](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
