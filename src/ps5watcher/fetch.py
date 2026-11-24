"""Page fetchers: plain HTTP (requests) and headless Chromium (Playwright).

Both return a FetchResult and never raise for network problems. Bot walls
(captcha, Cloudflare/Akamai/DataDome/PerimeterX challenge pages) are reported
as BLOCKED so they can never be mistaken for a real "out of stock" or a price.
"""

from __future__ import annotations

import logging
import random
import re
import time

import requests

from .models import FetchResult, FetchStatus

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.6",
    "Cache-Control": "no-cache",
}

# Strong, specific markers only - generic words like "captcha" also appear in
# normal pages (e.g. newsletter forms with reCAPTCHA).
BLOCK_MARKERS = [
    ("amazon captcha", re.compile(r"validateCaptcha|api-services-support@amazon\.com", re.I)),
    ("amazon robot check", re.compile(r"<title>\s*Robot Check\s*</title>", re.I)),
    ("cloudflare challenge", re.compile(r"_cf_chl_opt|cf-chl-widget|<title>\s*Just a moment\.\.\.\s*</title>|Attention Required! \| Cloudflare", re.I)),
    ("akamai access denied", re.compile(r"<title>\s*Access Denied\s*</title>", re.I)),
    ("datadome captcha", re.compile(r"captcha-delivery\.com", re.I)),
    ("perimeterx captcha", re.compile(r"px-captcha|_pxCaptcha", re.I)),
    ("incapsula", re.compile(r"_Incapsula_Resource|Request unsuccessful\. Incapsula", re.I)),
]
# Waiting rooms are detected by the URL we end up on, because normal pages
# often embed the queue script without actually queueing you.
WAITING_ROOM_URL = re.compile(r"queue-it\.net|//queue\.", re.I)


def detect_block(http_status: int | None, html: str, final_url: str | None = None) -> str | None:
    if final_url and WAITING_ROOM_URL.search(final_url):
        return "waiting room / queue"
    if http_status in (401, 403, 429):
        return f"HTTP {http_status}"
    sample = html[:200_000]
    for label, rx in BLOCK_MARKERS:
        if rx.search(sample):
            return label
    if http_status == 503:
        return "HTTP 503 (often a bot wall)"
    return None


def classify(url: str, http_status: int | None, html: str, final_url: str | None, fetcher: str) -> FetchResult:
    block = detect_block(http_status, html, final_url)
    if block:
        return FetchResult(url, FetchStatus.BLOCKED, http_status, html, final_url, f"blocked: {block}", fetcher)
    if http_status in (404, 410):
        return FetchResult(url, FetchStatus.NOT_FOUND, http_status, html, final_url, f"HTTP {http_status}", fetcher)
    if http_status is None or not (200 <= http_status < 300):
        return FetchResult(url, FetchStatus.HTTP_ERROR, http_status, html, final_url, f"HTTP {http_status}", fetcher)
    return FetchResult(url, FetchStatus.OK, http_status, html, final_url, None, fetcher)


class HttpFetcher:
    name = "http"

    def __init__(self, timeout: int = 25, retries: int = 2):
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def fetch(self, url: str) -> FetchResult:
        last_error = "unknown error"
        for attempt in range(self.retries + 1):
            try:
                resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
                result = classify(url, resp.status_code, resp.text, resp.url, self.name)
                # Retry only transient server errors, never bot walls.
                if result.status == FetchStatus.HTTP_ERROR and resp.status_code >= 500 and attempt < self.retries:
                    time.sleep(2 + attempt * 3)
                    continue
                return result
            except requests.RequestException as exc:
                # Short, readable message for reports; the exception type says what happened.
                last_error = f"network error ({type(exc).__name__})"
                if attempt < self.retries:
                    time.sleep(2 + attempt * 3 + random.random())
        return FetchResult(url, FetchStatus.NETWORK_ERROR, error=last_error, fetcher=self.name)

    def close(self) -> None:
        self.session.close()


class PlaywrightFetcher:
    """Headless Chromium for JavaScript-rendered pages. Started lazily, shared per run."""

    name = "playwright"

    def __init__(self, timeout: int = 45):
        self.timeout_ms = timeout * 1000
        self._pw = None
        self._browser = None
        self._context = None

    def _ensure(self):
        if self._context is not None:
            return
        from playwright.sync_api import sync_playwright  # imported lazily: optional dependency

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._context = self._browser.new_context(
            user_agent=USER_AGENT,
            locale="de-DE",
            timezone_id="Europe/Berlin",
            viewport={"width": 1366, "height": 900},
        )

    def fetch(self, url: str) -> FetchResult:
        try:
            self._ensure()
        except Exception as exc:  # noqa: BLE001
            return FetchResult(url, FetchStatus.NETWORK_ERROR, error=f"playwright unavailable: {exc}"[:300], fetcher=self.name)
        page = self._context.new_page()
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            try:
                page.wait_for_selector('script[type="application/ld+json"]', state="attached", timeout=8000)
            except Exception:  # noqa: BLE001 - structured data may legitimately be missing
                pass
            page.wait_for_timeout(1500)
            html = page.content()
            status = resp.status if resp else None
            return classify(url, status, html, page.url, self.name)
        except Exception as exc:  # noqa: BLE001
            return FetchResult(url, FetchStatus.NETWORK_ERROR, error=f"{type(exc).__name__}: {exc}"[:300], fetcher=self.name)
        finally:
            page.close()

    def close(self) -> None:
        for obj in (self._context, self._browser):
            try:
                if obj:
                    obj.close()
            except Exception:  # noqa: BLE001
                pass
        if self._pw:
            try:
                self._pw.stop()
            except Exception:  # noqa: BLE001
                pass


class FetcherPool:
    """Creates fetchers on demand so Playwright only starts if a source needs it."""

    def __init__(self, timeout: int = 25):
        self.timeout = timeout
        self._fetchers: dict[str, object] = {}

    def get(self, name: str):
        if name not in self._fetchers:
            self._fetchers[name] = HttpFetcher(self.timeout) if name == "http" else PlaywrightFetcher(max(self.timeout, 45))
        return self._fetchers[name]

    def close(self) -> None:
        for f in self._fetchers.values():
            f.close()
