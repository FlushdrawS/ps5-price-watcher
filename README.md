# PS5 Price Watcher (Germany): v0.2

A free Telegram bot for the **PlayStation 5 Digital Edition 825 GB**
(model group CFI-2100, EU model CFI-2116, "E-Chassis", EAN 0711719020837).
It runs on GitHub Actions, with no paid APIs, servers or subscriptions.

> **Status: not production-ready, and deliberately not deployed.**
> * 228 offline tests pass. 8 live website tests exist but are run only on purpose.
> * All 9 sources were researched live on 2026-11-24. 8 have a validated URL; Müller doesn't list the product.
> * **No source is marked `integration_tested`.** Live evidence so far comes from a desktop browser, not from the bot's HTTP client on GitHub's servers. See [Readiness](#4-source-readiness-and-blockers).
> * The scheduled workflow and Telegram are **off by default**.
> * Market reality on 2026-11-24: nothing new was offered at ≤ 500 €. Sony's list price is 599,99 € ([research log](docs/LIVE_RESEARCH_2026-11-24.md)).

---

## 1. What changed in v0.2 (audit fixes)

| Audit item | Change |
|---|---|
| Source coverage | URLs for Sony (moved to playstation.com), Amazon (B0FN7ZG39D), MediaMarkt/Saturn (article 3012188), OTTO, Alternate, expert and idealo (your candidate, validated). Müller: not listed, so it can't be configured. |
| Live testing | Live research documented in `docs/LIVE_RESEARCH_2026-11-24.md`. Regression fixtures rebuilt from the observed structures. `probe --record` writes evidence files. A separate live test suite (`pytest -m live`). Nothing is marked tested without evidence. |
| New parsers | MediaMarkt/Saturn embedded app state (`ceconomy`). idealo offer list (`idealo`). Amazon "no buy box" detection. |
| Telegram | A **full status report every 3 h (Berlin time), Fridays included**. On Fridays, extra checks every 15 min send **immediate alerts only on meaningful changes**. Duplicates are suppressed. |
| Safety | An EAN can't override a contradicting title (1 TB, bundle, used, accessory). Non-Sony EANs are flagged. The visible page text overrides structured "in stock". The price must be printed on the page. Seller policy per shop; marketplace offers are never verified. |
| idealo | Comparison only, always labelled "confirm on the merchant's site". Bundles in its offer list are filtered out. Preiswecker fallback documented (§8). |
| Price history | `history/YYYY-MM.jsonl`, persisted with `state.json` on the `watcher-state` branch. `history` CLI with CSV export. |
| Workflow | Hourly cron plus Friday quarter-hours for reliability. A dependency-free gate runs before `pip install`. A read-only check job and a separate write-only persist job. No shell interpolation of inputs. Dependabot. Disabled by default. |
| Testing | 228 offline tests (synthetic plus observed-structure fixtures, workflow/security assertions, state-branch round trip). Live tests separated and deselected by default. |

## 2. Architecture

```
GitHub cron (UTC, late/skipped runs possible)
   │  hourly :11  +  Fridays :02/:17/:32/:47
   ▼
gate.py (stdlib only, before pip install) ── slot already done? → exit in seconds
   │  Berlin slots: checks every 3 h, Fridays every 15 min; report slot every 3 h
   ▼
for each source: fetch.py (http | playwright) → BLOCKED / OK / …
   → extractor: generic JSON-LD · ceconomy state · amazon · idealo
   → pagecheck.py: visible stock sentence, visible price, visible seller
   → matching.py: EAN + title rules (825 GB Digital only)
   → verify.py: VERIFIED only if every check passes, else the reasons
   ▼
history.py (every observation) → alerts.py (events, de-dup) → notify.py
   report slot new?  yes → full status report (+ changes)   no → immediate alerts only
   ▼
persist job (only job with write access): data dir → 'watcher-state' branch
```

```
ps5-price-watcher/
├── README.md
├── docs/LIVE_RESEARCH_2026-11-24.md   live evidence for every URL
├── config/sources.toml                 target, schedule, EANs, 9 sources
├── requirements.txt / requirements-dev.txt / pyproject.toml / .env.example
├── src/ps5watcher/
│   ├── __main__.py   CLI: run | probe | status | history | gate | test-telegram
│   ├── gate.py       dependency-free slot gate for the workflow
│   ├── paths.py      data dir (state.json, history/), evidence dir
│   ├── config.py · ids.py · models.py · prices.py
│   ├── fetch.py      HTTP + Playwright, bot-wall detection
│   ├── extract.py    schema.org JSON-LD / microdata / meta
│   ├── pagecheck.py  visible-text cross-checks (stock, price, seller)
│   ├── matching.py   identity rules     ├── verify.py   verified vs. unverified
│   ├── alerts.py     events + de-dup    ├── notify.py   report / alerts / Telegram
│   ├── schedule.py   Berlin slots       ├── state.py    state.json
│   ├── history.py    price history      ├── evidence.py live-test evidence files
│   ├── runner.py     one run
│   └── sources/ base.py · ceconomy.py (MediaMarkt/Saturn) · amazon.py · idealo.py
├── scripts/state_branch.sh             load/save data dir on 'watcher-state'
├── tests/            offline tests + fixtures/ (synthetic + observed_*)
│   └── live/         LIVE website tests (pytest -m live)
├── evidence/         committed probe evidence (empty until you probe)
└── .github/  workflows/ tests.yml · watch.yml · probe.yml   dependabot.yml
```

## 3. Verified prices and purchase alerts

A retailer result is **VERIFIED** only if *all* of these hold:
1. The page was fetched normally (no captcha, bot wall, queue or 404).
2. The integration is live-tested (`integration_tested = true`, backed by an evidence file).
3. The price comes from structured data or a dedicated site parser, **and is printed on the page**.
4. Currency is EUR and the price is plausible (250–1500 €).
5. Identity is confirmed: EAN 0711719020837, or a title saying Digital + 825 GB / CFI-21xx, or a URL you confirmed by EAN/model (`url_identity_verified`). Exclusions always win: 1 TB/2 TB, Pro, disc, bundles, used/refurbished, accessories, other platforms. A foreign EAN on the page (OTTO case) blocks the URL upgrade.
6. Shipping is known (page data or config).
7. The seller passes the policy: the shop itself (`first_party_shop`) or the `required_seller`. **Marketplace offers are never verified.**

A **purchase alert** (🚨) additionally needs **in stock** (structured stock not contradicted by the page text) and a **total including shipping ≤ 500 €**. Anything else ≤ 500 € is sent as a clearly labelled ⚠️ *unverified listing* or 🔎 *price comparison*, with the reasons.

## Telegram behaviour

| When (Berlin time) | What is sent |
|---|---|
| Every 3 h: 00, 03, 06, 09, 12, 15, 18, 21, **every day including Friday** | One **status report**: all 9 sources (price, total, stock, verified/unverified with the main reason), any changes since the last check, and the cheapest verified in-stock offer |
| Fridays, the 15-minute checks in between | **Only** immediate alerts, and only if something meaningful changed: purchase alert, unverified listing ≤ target, significant price drop (≥ 10 € or ≥ 3 %), deal ended, back in stock / out of stock, source failing / recovered |

No duplicates: each report slot is reported once, each event fires once
(again only for a lower price, or after a 24 h reminder). A captcha in
between doesn't re-trigger anything. If Telegram fails, state isn't saved,
so the messages come again on the next run. The 3-hourly report doubles as
a heartbeat: if it stops arriving, the watcher has stopped.

## 4. Source readiness and blockers

Legend: ✔ done · ✘ missing · ? unknown until probed from the bot's network.

| Source | URL | Identity | Parser vs. observed structure | Seller check | Shipping | Bot's HTTP fetch | Integration tested | Blockers |
|---|---|---|---|---|---|---|---|---|
| Sony | ✔ | ✔ CFI-2116B01Y | ✔ JSON-LD + page-text stock override | ✔ first party | ✔ free ≥ 40 (banner) | ? | ✘ | Probe from the bot's network; confirm shipping at checkout; Sony page currently "not purchasable" |
| Amazon.de | ✔ B0FN7ZG39D | ✔ CFI-2116 | ◐ "no buy box" ✔; **buy-box selectors untested** (no offer existed) | ✔ must be Amazon | ◐ only "free delivery" text | ? (captchas likely) | ✘ | Needs a day when Amazon itself sells it, to confirm selectors; GitHub IPs likely blocked |
| MediaMarkt | ✔ 3012188 | ✔ EAN | ✔ embedded state; own article pinned | ✔ must be MediaMarkt | ✔ from state (0 €) | ? (bot protection likely) | ✘ | Probe from the bot's network; confirm visible price when back in assortment |
| Saturn | ✔ 3012188 | ✔ EAN | ✔ same as MediaMarkt | ✔ must be Saturn | ✔ 0 € | ? | ✘ | Same as MediaMarkt |
| OTTO | ✔ | ✘ **foreign EAN** (marketplace listing) | ✔ JSON-LD + visible seller | ✔ must be OTTO | ✔ 0 € in JSON-LD | ? | ✘ | No OTTO-sold listing exists, so it will always be unverified; replace the URL if OTTO lists its own article |
| Alternate | ✔ | ✔ EAN | ✔ JSON-LD (EAN in `gtin8`) | ✔ ALTERNATE GmbH | ✔ 7,99 € | ? | ✘ | Probe from the bot's network |
| expert | ✔ | ✔ via EAN search | ◐ sold-out ✔; **no price parser** (no structured data) | ✘ unknown | ✘ unknown | ? | ✘ | Needs an in-stock page to write a price parser; seller/shipping unknown |
| Müller | ✘ not listed | – | – | – | – | – | ✘ | Product not sold online on 2026-11-24 |
| idealo | ✔ validated | ✔ variant 825GB | ✔ offer list + JSON-LD fallback | n/a (comparison) | ✔ totals shown | ? (often blocks bots) | n/a | Probe from the bot's network; never a purchase source by design |

**Cross-cutting blockers before production**
1. **Probe from the bot's real network** (the GitHub "Probe sources" workflow, or `probe --record` locally). Only a passing probe plus a browser comparison justifies `integration_tested = true`.
2. Sources that GitHub's IPs can't reach will show as failing. Options: try `fetcher = "playwright"`, accept it, or disable it. Captchas are not bypassed.
3. Telegram is not activated yet (next step, with your confirmation).
4. Public vs. private repository choice (cost, see §9).

## 5. Testing: offline vs. live

| Suite | Command | Network | In CI |
|---|---|---|---|
| **Offline** (228 tests): parsers on synthetic and observed fixtures, verification, safety rules, schedule/DST, reports, de-dup, history, gate without dependencies, workflow security assertions, state-branch git round trip | `python -m pytest` | none | yes (`tests.yml`) |
| **Live** (8 tests, one per configured source): real fetch from *your* network; asserts fetch OK, identity MATCH, price or explicit unavailability, EUR, plausible, seller known; writes evidence | `pytest -m live tests/live -s` | real retailers | no (run on purpose) |
| **Probe** (diagnostics, any network) | `python -m ps5watcher probe --record --save-html debug` | real retailers | manual workflow `probe.yml` |

### Local setup

```bash
cd ps5-price-watcher
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m pytest                   # offline suite
export PYTHONPATH=src              # PowerShell: $env:PYTHONPATH="src"
python -m ps5watcher status
python -m ps5watcher probe --record --save-html debug --where "home"
python -m ps5watcher run --force --dry-run --report     # prints the Telegram report, sends nothing
python -m ps5watcher history --days 7
```

## 6. Making a source verified

1. Open the URL in a browser and confirm: 825 GB Digital Edition, single console, new, sold by the retailer.
2. `python -m ps5watcher probe --source <id> --record --where "<network>"` and compare price, stock, seller and shipping with the browser. Ideally do this also from GitHub (Probe workflow): that's the network the bot will use.
3. Commit the evidence file `evidence/probe/<id>/…json`.
4. Set `integration_tested = true` in `config/sources.toml`.
5. Run `python -m pytest` again. The suite checks the config rules.

## 7. Price history

Every check appends one line per source to `data/history/YYYY-MM.jsonl`
(UTC timestamp, status, price, shipping, total, stock, seller, marketplace
flag, method, top reasons). On GitHub the data directory is restored before
and saved after each run on the `watcher-state` branch: a single commit,
force-pushed, containing only `state.json` and `history/*.jsonl`. Files
older than 400 days are pruned. View or export with
`python -m ps5watcher history --days 30 --csv prices.csv`.

## 8. idealo, and the Preiswecker fallback

idealo is configured as `kind = "comparison"`. It reads the lowest **total
including shipping** from the offer list, filters out bundle and accessory
offers by title, and names the shop and any marketplace seller. Its results
are **never verified**: every idealo message says "confirm on the merchant's
own site". On 2026-11-24 its cheapest offers came from a Swedish shop and
from marketplace sellers.

**Fallback if idealo blocks the bot:** use idealo's own free
**Preiswecker** (price alarm). On the product page, click "Preiswecker
stellen", enter 500 € as the desired price and choose how to be notified
(account/e-mail or the idealo app, per idealo's current options). It
complements the bot. Still verify the merchant, total and shipping before
buying.

## 9. Workflow review (schedule, DST, delays, security, persistence)

* **Europe/Berlin and DST.** All decisions are made in Python with `zoneinfo`. Tests cover the DST change days and Friday starting/ending at Berlin midnight in both CET and CEST.
* **Delays and skipped runs.** Cron fires hourly (:11) plus every 15 min on Fridays (:02/:17/:32/:47, avoiding the busy top of the hour), and on Thursday 22–24 UTC for Berlin's Friday start. Each 3-hour slot therefore gets 3 chances, and late runs still land in the right slot. The gate exits in seconds when a slot is done.
* **Disabled by default.** Scheduled runs need the repository variable `WATCHER_ENABLED=true`. Telegram needs `TELEGRAM_ENABLED=true` plus the two secrets. Manual runs default to a dry run.
* **Least privilege.** Workflow default `permissions: {}`. The `check` job has a read-only token and is the only job that sees the Telegram secrets, in one step only. The `persist` job has `contents: write`, but never parses retailer HTML or sees secrets.
* **Injection.** No `${{ … }}` expressions inside `run:` scripts (enforced by a test). The probe workflow validates its inputs.
* **Secrets.** Never in code or config. The bot token is never logged: urllib3 debug logging is silenced, and errors don't include the URL.
* **Supply chain.** Only GitHub-owned actions (`actions/*`). Dependabot proposes monthly updates. For extra hardening you can pin actions to commit SHAs.
* **Cost.** On a **public repo**, standard GitHub-hosted runners are free. On a private repo, a simulated month (Nov 2026) has about 1,140 workflow runs: about 590 full checks (each 2 jobs, check + persist) and about 550 that stop at the gate. Each job is billed as at least one minute, so expect roughly **1,700+ minutes a month**. That is close to typical free allowances, so check your billing page before choosing private.
* **60-day rule.** GitHub disables scheduled workflows in public repos after 60 days without repository activity, and emails a warning first. One click re-enables it. If the 3-hour reports stop, check this first.

## 10. Configuration reference

`config/sources.toml`, commented in place. Per source: `url`, `kind`,
`fetcher`, `extractor` (`generic`/`amazon`/`ceconomy`/`idealo`),
`article_id`, `integration_tested`, `first_party_shop`, `required_seller`,
`url_identity_verified` + `url_identity_evidence`, `shipping_eur`,
`free_shipping_from_eur`, `require_visible_price`, `enabled`, `notes`.
Environment: `TELEGRAM_ENABLED`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
`PS5W_CONFIG`, `PS5W_DATA_DIR`, `PS5W_EVIDENCE_DIR` (locally via `.env`).

## Fair use

At most one page per source per slot, which is lighter than a person
refreshing a page. Captchas and bot protection are never circumvented. Some
retailers' terms restrict automated access. Review them and disable any
source you're not comfortable with.
