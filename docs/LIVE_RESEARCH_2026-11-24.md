# Live research log, 24 Nov 2026 (~15:00 Europe/Berlin)

**Method.** Each page was opened in a desktop Chrome browser (Claude in
Chrome, the user's own browser, German residential connection), read-only.
I read the structured data (JSON-LD, embedded app state) and the visible
text with JavaScript. No captcha or bot wall appeared, and none was bypassed.
No account actions were taken. Personal data the page displayed (e.g.
Amazon's delivery address) was not recorded.

**What this proves.** The URLs are correct, the product identity is
confirmed, and the page structures that the parsers now read are known
(regression fixtures: `tests/fixtures/observed_*_2026-11-24.html`).

**What it does NOT prove.** It does not show that the bot's HTTP client
(Python `requests`, or headless Chromium on a GitHub-hosted runner) gets
the same HTML. Datacenter IPs are often served captchas, and some pages
are rendered with JavaScript. So **no source is marked
`integration_tested`**. That needs `probe --record` from the bot's real
environment (see README §6).

| Source | Configured URL | Identity evidence | Price | Stock | Seller | Shipping | Data structure |
|---|---|---|---|---|---|---|---|
| Sony | `playstation.com/de-de/ps5/digital-edition-825-gb/` (the old `direct.playstation.com/de-de/buy-consoles/playstation5-digital-edition-console-825-gb` **redirects here**) | JSON-LD `mpn` **CFI-2116B01Y**, h1 "PlayStation®5 Digital Edition Konsole - 825 GB" | **599,99 €** | JSON-LD says `InStock`, but the page says **"Derzeit nicht vorrätig"** and **"Nicht zum Kauf erhältlich"** | Sony (no marketplace) | banner: "Kostenlose Lieferung ab £40 Bestellwert" (sic) | JSON-LD Product (no GTIN, no seller) |
| Amazon.de | `amazon.de/dp/B0FN7ZG39D` | Tech details: model **CFI-2116**, release 15 Sep 2025 | none | **no buy box**: "See all buying options" (third-party sellers only) | n/a | n/a | no JSON-LD; `#productTitle` |
| MediaMarkt | `mediamarkt.de/…-3012188.html` → **redirects** to marketplace product `…-165421836.html` | Embedded state: article 3012188 **EAN 0711719020837** | own article **599,99 €**; marketplace 1.099,99 € | own: `NOT_IN_ASSORTMENT`, not buyable; marketplace: buyable | own: MediaMarkt; marketplace: **Collectronics** | 0 € (both) | No Product JSON-LD. `window.__PRELOADED_STATE__` → `apolloState` (`CofrPriceFeature`, `CofrOnlineStatusFeature`, `GraphqlProduct`) |
| Saturn | `saturn.de/…-3012188.html` → same marketplace redirect | Same EAN | same as MediaMarkt | same | same | same | same platform |
| OTTO | `otto.de/p/…-S0GFY0YO/` | Title says Digital 825 GB, but JSON-LD `gtin` is **4262451074603 (not Sony's EAN)** | 1.299,99 € | JSON-LD InStock | **Marketplace: "Verkäufer: Hakla-Shop"** (visible text only) | 0,00 € | JSON-LD Product without seller |
| Alternate | `alternate.de/…/html/product/100155464` | **EAN 0711719020837** (in JSON-LD field `gtin8`, and in the datasheet), CFI-2100 | 899,00 € | `OutOfStock`; "Artikel kann derzeit nicht gekauft werden" | ALTERNATE GmbH | **7,99 €** (JSON-LD `shippingRate`) | JSON-LD Product + Offer |
| expert | `expert.de/shop/…/11364210744-playstation-5-digital-edition-modellgruppe-slim.html` | A site search for **EAN 0711719020837** resolved to this page; page shows "825 GB" | none shown | "Das von Ihnen ausgewählte Produkt ist ausverkauft." | unknown | unknown | **no structured data** |
| Müller | – | **Not listed.** Searching "playstation 5 digital" (34 hits) found only the PS5 1 TB (disc), PS5 Pro 2 TB and the disc drive | – | – | – | – | – |
| idealo | `idealo.de/preisvergleich/OffersOfProduct/207748718_-…-825gb-sony.html` (**the candidate you supplied, validated**) | Variant "Standard Edition 825GB"; details "Modell PS5 Digital, 825 GB, 2025" | **from 799,90 € incl. shipping**, 5 offers up to 968,90 € | – | cheapest: maxgaming.gg (Sweden); others are marketplaces (eBay/leipzigsells, Hakla-Shop, FabKoh24Deals) | shown per offer | JSON-LD AggregateOffer (name **lacks** "825") + offer list `li.productOffers-listItem` |

Other observations:

* Variants on the MediaMarkt/Saturn page: 3020826 (EAN 0711719022633, the
  2-controller bundle, 649,99 €, available), 3020823 (EAN 0711719022404,
  699,99 €, available), 3018916 (529,99 €, not in assortment), 3018022
  (899,99 €, temporarily unavailable). Only 3012188 is the single console.
  The others are why the parser pins to the configured article.
* idealo international prices for the same variant: idealo.fr from 599 €,
  idealo.it from 599,99 €.

**Market conclusion on that day.** No German source offered the console
new for ≤ 500 €. Sony's own list price was 599,99 €.
