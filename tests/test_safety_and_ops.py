"""Safety rules, scheduling of reports, history, gate, workflows and state persistence (offline)."""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import yaml
from conftest import ROOT, SPEC

from ps5watcher.alerts import EventType, evaluate
from ps5watcher.config import ConfigError, load_config
from ps5watcher.evidence import build
from ps5watcher.history import HistoryStore
from ps5watcher.matching import match_offer
from ps5watcher.models import (
    Availability,
    CheckResult,
    ExtractedOffer,
    FetchStatus,
    MatchResult,
    Verification,
)
from ps5watcher.notify import build_report, html_to_text
from ps5watcher.schedule import decide
from ps5watcher.state import empty_state


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def res(price, verification=Verification.VERIFIED, stock=Availability.IN_STOCK, sid="shop", total="auto"):
    offer = ExtractedOffer(title="PS5 Digital 825 GB", price=Decimal(str(price)) if price else None,
                           currency="EUR", availability=stock, method="jsonld")
    tot = (Decimal(str(price)) if price else None) if total == "auto" else total
    return CheckResult(source_id=sid, source_name=sid.title(), kind="retailer", url=f"https://{sid}.example/p",
                       fetch_status=FetchStatus.OK, verification=verification, match=MatchResult.MATCH,
                       offer=offer, total=tot)


# ------------------------------------------------------------------ identity safety
@pytest.mark.parametrize(
    "title",
    [
        "PlayStation 5 Slim Digital Edition 1TB",            # wrong storage despite our EAN
        "PS5 Digital Edition 825 GB + 2 DualSense",          # bundle despite our EAN
        "PlayStation 5 Digital Edition 825 GB gebraucht",    # used despite our EAN
        "Cover für PS5 Digital Edition",                     # accessory despite our EAN
    ],
)
def test_expected_ean_cannot_override_contradicting_title(title):
    o = ExtractedOffer(title=title, gtin="0711719020837")
    out = match_offer(o, SPEC)
    assert out.result == MatchResult.REJECT
    assert "EAN 0711719020837 matches but" in out.reasons[0]


@pytest.mark.parametrize(
    "title",
    [
        "PlayStation®5 Konsole – 1TB",
        "PlayStation®5 Pro-Konsole - 2 TB",
        "Disc-Laufwerk für PS5® Pro-Konsolen und PS5 Digital Edition-Konsolen",
        "Sony PS5 Slim Digital Edition Disc Laufwerk",
        "Sony PlayStation Portal White",
        "Sony PlayStation 5 Slim (PS5 Slim) Digital Edition 825GB Marvel's Wolverine Limited Edition",
        "Sony PlayStation 5 Slim (PS5 Slim) + Call of Duty: Black Ops 6",
        "PlayStation 5 Digital-Edition 825 GB – EA SPORTS FC™ 26 Bundle",
        "Playstation 5 Digital-Edition 825 GB – Fortnite Erblühendes-Chaos-Bundle",
        "Joso front panel for PS5 Digital Edition, replacement cover",
        "NEWDERY Fan for PS5 Slim Console",
    ],
)
def test_titles_seen_live_are_rejected(title):
    assert match_offer(ExtractedOffer(title=title), SPEC).result == MatchResult.REJECT


def test_foreign_ean_flagged_and_not_upgradeable():
    out = match_offer(ExtractedOffer(title="PS5 Slim DIGITAL Edition ohne Laufwerk 825 GB", gtin="4262451074603"), SPEC)
    assert out.result == MatchResult.PROBABLE and out.gtin_mismatch


def test_purchase_alert_requires_stock_and_total():
    s = load_config().settings
    now = utc(2026, 11, 27, 12)
    assert evaluate([res(489, stock=Availability.UNKNOWN)], empty_state(), s, now) == []
    assert evaluate([res(489, total=None)], empty_state(), s, now) == []  # shipping unknown
    assert evaluate([res(489, stock=Availability.OUT_OF_STOCK)], empty_state(), s, now) == []
    ev = evaluate([res(489, verification=Verification.UNVERIFIED)], empty_state(), s, now)
    assert [e.type for e in ev] == [EventType.CANDIDATE]  # labelled, not a purchase alert


def test_deal_ended_event():
    s = load_config().settings
    st = empty_state()
    t = utc(2026, 11, 27, 12)
    assert [e.type for e in evaluate([res(489)], st, s, t)] == [EventType.TARGET_HIT]
    ev = evaluate([res(489, stock=Availability.OUT_OF_STOCK)], st, s, t + timedelta(minutes=15))
    assert [e.type for e in ev] == [EventType.DEAL_ENDED]  # no extra OUT_OF_STOCK duplicate
    assert evaluate([res(489, stock=Availability.OUT_OF_STOCK)], st, s, t + timedelta(minutes=30)) == []


# ------------------------------------------------------------------ report schedule
@pytest.mark.parametrize(
    "when,expected",
    [
        (utc(2026, 11, 24, 12, 11), "rep:2026-11-24T12"),   # Tue 13:11 CET
        (utc(2026, 11, 27, 13, 47), "rep:2026-11-27T12"),   # Fri 14:47 CET (Friday too)
        (utc(2026, 11, 27, 14, 2), "rep:2026-11-27T15"),    # Fri 15:02 CET
        (utc(2026, 7, 3, 21, 59), "rep:2026-07-03T21"),     # Fri 23:59 CEST
        (utc(2026, 3, 29, 1, 30), "rep:2026-03-29T03"),     # DST start: 01:30 UTC = 03:30 CEST
        (utc(2026, 10, 25, 1, 30), "rep:2026-10-25T00"),    # DST end:   01:30 UTC = 02:30 CET
    ],
)
def test_report_slots(when, expected):
    assert decide(None, now_utc=when).report_slot == expected


def test_friday_has_eight_report_slots_and_96_check_slots():
    start = utc(2026, 11, 26, 23, 0)  # Fri 00:00 CET
    checks, reports = set(), set()
    for m in range(0, 24 * 60, 5):
        d = decide(None, now_utc=start + timedelta(minutes=m))
        checks.add(d.slot)
        reports.add(d.report_slot)
    assert len(checks) == 96 and len(reports) == 8


def test_normal_day_has_eight_check_and_report_slots():
    start = utc(2026, 11, 23, 23, 0)  # Tue 00:00 CET
    slots = {decide(None, now_utc=start + timedelta(minutes=m)).slot for m in range(0, 24 * 60, 5)}
    assert len(slots) == 8


# ------------------------------------------------------------------ report format
def test_report_lists_every_source_with_status():
    rs = [res(899, stock=Availability.OUT_OF_STOCK, sid="alternate"),
          res(None, verification=Verification.UNVERIFIED, stock=Availability.OUT_OF_STOCK, sid="amazon"),
          CheckResult(source_id="mueller", source_name="Müller", kind="retailer", url="",
                      fetch_status=FetchStatus.NOT_CONFIGURED, verification=Verification.SKIPPED,
                      match=MatchResult.UNKNOWN)]
    msgs = build_report(rs, [], Decimal("500"), "Tue 2026-11-24 15:00 CET")
    text = html_to_text(msgs[0])
    assert "status report" in text and "Alternate" in text and "899,00 €" in text
    assert "Amazon (https://amazon.example/p): not offered" in text and "Müller: not configured" in text
    assert "Cheapest verified in stock: none" in text


# ------------------------------------------------------------------ history
def test_history_roundtrip_prune_and_csv(tmp_path):
    h = HistoryStore(tmp_path / "history")
    old = utc(2025, 9, 1)
    h.append([res(599)], old)
    h.append([res(589)], utc(2026, 11, 24))
    assert len(h.read()) == 2
    assert len(h.read(since=utc(2026, 1, 1))) == 1
    removed = h.prune(400, utc(2026, 11, 24))
    assert removed == ["2025-09.jsonl"]
    h.export_csv(h.read(), tmp_path / "x.csv")
    assert ",589," in (tmp_path / "x.csv").read_text()


# ------------------------------------------------------------------ evidence
def test_evidence_has_no_html_and_a_checklist():
    data = build(res(599), None)
    assert "html" not in json.dumps(data).lower().replace("html_size", "")
    assert data["checklist_for_integration_tested"]["identity_match"] is True


# ------------------------------------------------------------------ config safety
def test_shipped_config_rules():
    cfg = load_config()
    assert not any(s.integration_tested for s in cfg.sources)
    for s in cfg.sources:
        if s.url_identity_verified:
            assert s.url_identity_evidence
        if s.kind == "retailer" and s.url and s.id != "expert":  # expert: seller policy unknown -> stays unverified
            assert s.first_party_shop or s.required_seller, f"{s.id}: no seller policy"
    assert cfg.source("mueller").url == ""
    assert cfg.source("idealo").kind == "comparison"


def test_config_rejects_unbacked_identity_claim(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[[sources]]\nid="a"\nurl="https://x.example/p"\nurl_identity_verified=true\n')
    with pytest.raises(ConfigError):
        load_config(p)


def test_config_ceconomy_needs_article(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[[sources]]\nid="a"\nurl="https://x.example/p"\nextractor="ceconomy"\n')
    with pytest.raises(ConfigError):
        load_config(p)


# ------------------------------------------------------------------ gate without dependencies
def test_gate_runs_with_standard_library_only(tmp_path):
    code = (
        "import sys; sys.modules['bs4']=None; sys.modules['requests']=None; sys.modules['playwright']=None;"
        "from ps5watcher.gate import main; sys.exit(main(['--force']))"
    )
    out_file = tmp_path / "gh_out"
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), GITHUB_OUTPUT=str(out_file),
               PS5W_DATA_DIR=str(tmp_path / "data"))
    proc = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = out_file.read_text()
    assert "due=true" in out and "report=true" in out and "needs_browser=" in out


# ------------------------------------------------------------------ workflows
WF = ROOT / ".github" / "workflows"


def _load(name):
    return yaml.safe_load((WF / name).read_text())


def test_watch_workflow_least_privilege_and_disabled_by_default():
    wf = _load("watch.yml")
    assert wf["permissions"] == {}
    check, persist = wf["jobs"]["check"], wf["jobs"]["persist"]
    assert check["permissions"] == {"contents": "read"}
    assert persist["permissions"] == {"contents": "write"}
    assert "vars.WATCHER_ENABLED == 'true'" in check["if"]
    # secrets only in the single step that needs them, never in the write job
    steps_with_secrets = [s for s in check["steps"] if "secrets." in json.dumps(s)]
    assert [s["name"] for s in steps_with_secrets] == ["Check prices and notify"]
    assert "secrets." not in json.dumps(persist)
    assert "vars.TELEGRAM_ENABLED" in json.dumps(steps_with_secrets[0])


def test_watch_workflow_crons_cover_berlin_friday():
    crons = [c["cron"] for c in _load("watch.yml")[True]["schedule"]]
    assert "11 * * * *" in crons
    assert any(c.endswith("* * 5") for c in crons) and any(c.endswith("* * 4") for c in crons)


@pytest.mark.parametrize("name", ["watch.yml", "probe.yml", "tests.yml"])
def test_no_expression_interpolation_inside_run_scripts(name):
    wf = _load(name)
    for job in wf["jobs"].values():
        for step in job["steps"]:
            run = step.get("run", "")
            assert "${{" not in run, f"{name}: expression inside run script: {run[:80]}"


# ------------------------------------------------------------------ state branch script
@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_state_branch_roundtrip(tmp_path):
    script = ROOT / "scripts" / "state_branch.sh"
    env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")

    def git(*a, cwd):
        return subprocess.run(["git", *a], cwd=cwd, env=env, capture_output=True, text=True, check=True)

    remote, work = tmp_path / "remote.git", tmp_path / "work"
    git("init", "-q", "--bare", str(remote), cwd=tmp_path)
    git("init", "-q", str(work), cwd=tmp_path)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "i", cwd=work)
    git("remote", "add", "origin", str(remote), cwd=work)
    data = tmp_path / "data"
    (data / "history").mkdir(parents=True)
    (data / "state.json").write_text('{"version": 1}')
    (data / "history" / "2026-11.jsonl").write_text('{"t": 1}\n')
    (data / "secret.env").write_text("TOKEN=should-not-be-saved")
    e2 = dict(env, PS5W_DATA_DIR=str(data))
    subprocess.run(["bash", str(script), "save"], cwd=work, env=e2, check=True, capture_output=True)
    shutil.rmtree(data)
    subprocess.run(["bash", str(script), "load"], cwd=work, env=e2, check=True, capture_output=True)
    assert (data / "history" / "2026-11.jsonl").read_text() == '{"t": 1}\n'
    assert not (data / "secret.env").exists()
    count = git("--git-dir", str(remote), "rev-list", "--count", "watcher-state", cwd=tmp_path).stdout.strip()
    assert count == "1"
