# Test fixtures — SYNTHETIC

Every HTML file in this folder was written by hand for the unit tests.
They follow public schema.org conventions (JSON-LD, microdata, OpenGraph)
and imitate the *shape* of common shop pages. They are **not** copies of
real retailer pages and passing tests here proves nothing about whether a
live retailer integration works. Live behaviour is checked with
`python -m ps5watcher probe`.

To add a real-world regression test later: save a page with
`probe --save-html debug/`, strip personal/cookie data, and add it here
with a name like `real_alternate_2026-11.html`.

## observed_*_2026-11-24.html — observed structure

These files are **minimal reconstructions** of structures seen live on
2026-11-24 in a desktop Chrome browser (via Claude in Chrome): the same
element ids/classes, JSON-LD keys, embedded-state entities and the values
shown that day. They contain only what the parser reads, not page copies.
They are regression tests for real-world quirks, e.g.:

* Sony: JSON-LD `InStock` while the page says "Derzeit nicht vorrätig".
* MediaMarkt/Saturn: no JSON-LD, data in `window.__PRELOADED_STATE__`,
  own article NOT_IN_ASSORTMENT, page redirected to a marketplace offer,
  a bundle variant with another EAN on the same page.
* OTTO: marketplace seller only in visible text, non-Sony EAN.
* Alternate: the 13-digit EAN sits in a field called `gtin8`.
* Amazon: no buy box at all.
* expert: no structured data, sold-out sentence only.
* idealo: AggregateOffer name without "825", offer list with marketplaces.

A browser is not the bot's HTTP client: these files prove the parser handles
the structures, not that GitHub-hosted runners receive the same HTML.
