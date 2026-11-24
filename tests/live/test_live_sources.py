"""LIVE website tests - real network requests to the configured retailers.

NOT part of the default test run (deselected by the `live` marker, see
pyproject.toml) and NOT run in CI. Run them on purpose, from your own machine
or the "Probe sources" workflow:

    pytest -m live tests/live -s                 # all sources
    pytest -m live tests/live -s -k alternate    # one source

Every test writes an evidence file to evidence/probe/<source>/ (no HTML).
A FAILED test means "this integration does not work from this network right
now" - it is information, not a bug in the offline code. Commit the evidence
of a PASSED run before setting integration_tested = true for that source.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from ps5watcher.config import DEFAULT_CONFIG, PROJECT_ROOT, load_config
from ps5watcher.evidence import record
from ps5watcher.fetch import FetcherPool
from ps5watcher.models import Availability, FetchStatus, MatchResult, Verification
from ps5watcher.sources import check_source

pytestmark = pytest.mark.live

CFG = load_config(DEFAULT_CONFIG)
LIVE_SOURCES = [s for s in CFG.sources if s.enabled and s.url]


@pytest.fixture(scope="module")
def pool():
    p = FetcherPool(timeout=CFG.settings.request_timeout_s)
    yield p
    p.close()


@pytest.mark.parametrize("src", LIVE_SOURCES, ids=[s.id for s in LIVE_SOURCES])
def test_live_source(src, pool):
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    result, fetch = check_source(src, pool, CFG.product, CFG.settings, now)
    evidence_root = os.environ.get("PS5W_LIVE_EVIDENCE_DIR") or str(PROJECT_ROOT / "evidence")
    path = record(result, fetch, evidence_root, where=os.environ.get("PS5W_WHERE", "live pytest"))
    print(f"\n[{src.id}] {result.verification.value} price={result.price} total={result.total} "
          f"stock={result.availability.value} seller={result.offer.seller if result.offer else None}\n"
          f"  reasons: {result.reasons}\n  evidence: {path}")

    assert result.fetch_status == FetchStatus.OK, f"fetch failed: {result.reasons}"
    assert result.verification not in (Verification.ERROR, Verification.REJECTED), result.reasons
    assert result.match == MatchResult.MATCH, f"identity not confirmed: {result.reasons}"
    o = result.offer
    assert o is not None
    assert o.price is not None or o.availability == Availability.OUT_OF_STOCK, "neither price nor clear unavailability"
    if o.price is not None:
        assert o.currency == "EUR"
        assert CFG.settings.min_plausible_eur <= o.price <= CFG.settings.max_plausible_eur
    if src.kind == "retailer" and o.price is not None:
        assert o.seller, "seller could not be determined"
