from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ps5watcher.config import ProductSpec, Settings, SourceConfig  # noqa: E402
from ps5watcher.extract import normalize_gtin  # noqa: E402
from ps5watcher.fetch import classify  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


SPEC = ProductSpec(
    expected_gtins=frozenset({normalize_gtin("0711719020837")}),
    reject_gtins=frozenset({normalize_gtin("0711719022633"), normalize_gtin("0711719021926")}),
)


def evaluate_html(html, src, spec=SPEC, settings=None, status=200, final_url=None, now="2026-11-27T13:00:00+00:00"):
    """The exact runtime pipeline minus the network: classify -> extract -> page checks -> verify."""
    from ps5watcher.sources.base import extract_offer
    from ps5watcher.verify import evaluate_offer
    from ps5watcher.models import FetchStatus

    settings = settings or Settings(delay_between_sources_s=0)
    fetch = classify(src.url, status, html, final_url or src.url, "test")
    offer = extract_offer(src, html, spec, fetch.final_url) if fetch.status == FetchStatus.OK else None
    return evaluate_offer(src, fetch, offer, spec, settings, now)


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    """No test may ever touch the real data/ or evidence/ folders."""
    monkeypatch.setenv("PS5W_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PS5W_EVIDENCE_DIR", str(tmp_path / "evidence"))
    for var in ("TELEGRAM_ENABLED", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def settings() -> Settings:
    return Settings(delay_between_sources_s=0)


@pytest.fixture
def spec() -> ProductSpec:
    return SPEC


def make_src(**kw) -> SourceConfig:
    defaults = dict(
        id="shop",
        name="Test Shop",
        url="https://shop.example/ps5",
        integration_tested=True,
        shipping_eur=None,
        first_party_shop=True,
    )
    defaults.update(kw)
    return SourceConfig(**defaults)


class FakeFetcher:
    """Serves fixture HTML by URL; no network."""

    name = "fake"

    def __init__(self, pages: dict[str, tuple[int, str]]):
        self.pages = pages
        self.calls: list[str] = []

    def fetch(self, url: str):
        self.calls.append(url)
        status, html = self.pages[url]
        return classify(url, status, html, url, self.name)

    def close(self):
        pass


class FakePool:
    def __init__(self, pages):
        self.fetcher = FakeFetcher(pages)

    def get(self, name):
        return self.fetcher

    def close(self):
        pass


D = Decimal
