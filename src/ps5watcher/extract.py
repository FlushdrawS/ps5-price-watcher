"""Generic, retailer-independent extraction of product offers from HTML.

Order of trust:
  1. schema.org JSON-LD (<script type="application/ld+json">)
  2. schema.org microdata (itemprop="price" ...)
  3. OpenGraph / product meta tags (weakest; never enough for "verified")

Nothing here is retailer-specific. Retailer quirks live in sources/.
"""

from __future__ import annotations

import json
import logging
import re
from decimal import Decimal
from typing import Any, Iterable

from bs4 import BeautifulSoup

from .ids import normalize_gtin
from .models import Availability, ExtractedOffer
from .prices import parse_price

log = logging.getLogger(__name__)

TRUSTED_METHODS = {"jsonld", "microdata"}

_AVAILABILITY_MAP = {
    "instock": Availability.IN_STOCK,
    "limitedavailability": Availability.IN_STOCK,
    "onlineonly": Availability.IN_STOCK,
    "instoreonly": Availability.OUT_OF_STOCK,  # not orderable online
    "outofstock": Availability.OUT_OF_STOCK,
    "soldout": Availability.OUT_OF_STOCK,
    "discontinued": Availability.OUT_OF_STOCK,
    "preorder": Availability.PREORDER,
    "presale": Availability.PREORDER,
    "backorder": Availability.PREORDER,
}

_CONDITION_MAP = {
    "newcondition": "new",
    "usedcondition": "used",
    "refurbishedcondition": "refurbished",
    "damagedcondition": "damaged",
}


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "html.parser")


# --------------------------------------------------------------------------- #
# Normalisers
# --------------------------------------------------------------------------- #
def _last_segment(value: Any) -> str:
    """'https://schema.org/InStock' -> 'instock'."""
    if not value:
        return ""
    if isinstance(value, dict):
        value = value.get("@id") or value.get("name") or ""
    s = str(value).strip().rstrip("/")
    s = s.rsplit("/", 1)[-1]
    return re.sub(r"[^a-z]", "", s.lower())


def map_availability(value: Any) -> Availability:
    return _AVAILABILITY_MAP.get(_last_segment(value), Availability.UNKNOWN)


def map_condition(value: Any) -> str | None:
    return _CONDITION_MAP.get(_last_segment(value))


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _types(node: dict) -> set[str]:
    return {str(t).lower() for t in _as_list(node.get("@type"))}


# --------------------------------------------------------------------------- #
# JSON-LD
# --------------------------------------------------------------------------- #
def _iter_jsonld_nodes(soup: BeautifulSoup) -> Iterable[dict]:
    for tag in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = tag.string or tag.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Some sites put several objects or trailing commas; try a lenient fix.
            try:
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", raw))
            except json.JSONDecodeError:
                log.debug("Unparseable JSON-LD block skipped")
                continue
        yield from _walk(data)


def _walk(data: Any) -> Iterable[dict]:
    if isinstance(data, list):
        for item in data:
            yield from _walk(item)
    elif isinstance(data, dict):
        yield data
        for key in ("@graph", "mainEntity", "itemListElement", "item", "hasVariant"):
            if key in data:
                yield from _walk(data[key])


def _shipping_from(offer: dict) -> Any:
    for details in _as_list(offer.get("shippingDetails")):
        if not isinstance(details, dict):
            continue
        rate = details.get("shippingRate")
        for r in _as_list(rate):
            if isinstance(r, dict):
                val = r.get("value", r.get("price"))
                if val is not None:
                    cur = str(r.get("currency", "EUR")).upper()
                    if cur == "EUR":
                        # parse_price rejects 0 (free shipping) - handle explicitly
                        if str(val).strip() in {"0", "0.0", "0.00", "0,00"}:
                            return "0"
                        return val
    return None


def _offer_from_product(node: dict) -> ExtractedOffer:
    title = node.get("name")
    gtin = None
    for key in ("gtin13", "gtin", "gtin14", "gtin12", "gtin8", "ean"):
        if node.get(key):
            gtin = normalize_gtin(node.get(key))
            if gtin:
                break
    offer = ExtractedOffer(
        title=str(title).strip() if title else None,
        gtin=gtin,
        mpn=str(node["mpn"]) if node.get("mpn") else None,
        method="jsonld",
    )

    offers = [o for o in _as_list(node.get("offers")) if isinstance(o, dict)]
    # Flatten AggregateOffer.offers if present, but keep aggregate values too.
    chosen: dict | None = None
    for o in offers:
        if "aggregateoffer" in _types(o):
            offer.price = parse_price(o.get("lowPrice") or o.get("price"))
            offer.currency = (o.get("priceCurrency") or "").upper() or None
            try:
                offer.offer_count = int(o.get("offerCount")) if o.get("offerCount") else None
            except (TypeError, ValueError):
                offer.offer_count = None
            offer.availability = map_availability(o.get("availability"))
            return offer

    # Several offers on one product: prefer an in-stock new one with the lowest price.
    def sort_key(o: dict):
        av = map_availability(o.get("availability"))
        cond = map_condition(o.get("itemCondition")) or "new"
        price = parse_price(o.get("price") or _price_spec(o))
        return (
            0 if cond == "new" else 1,
            0 if av == Availability.IN_STOCK else 1,
            price if price is not None else Decimal("1e9"),
        )

    if offers:
        chosen = sorted(offers, key=sort_key)[0]
    if chosen:
        offer.price = parse_price(chosen.get("price") or _price_spec(chosen))
        offer.currency = (chosen.get("priceCurrency") or _price_spec_currency(chosen) or "").upper() or None
        offer.availability = map_availability(chosen.get("availability"))
        offer.condition = map_condition(chosen.get("itemCondition") or node.get("itemCondition"))
        ship = _shipping_from(chosen)
        if ship == "0":
            offer.shipping = Decimal("0.00")
        elif ship is not None:
            offer.shipping = parse_price(ship)
        seller = chosen.get("seller")
        if isinstance(seller, dict):
            offer.seller = seller.get("name")
        elif isinstance(seller, str):
            offer.seller = seller
        if not offer.gtin:
            for key in ("gtin13", "gtin", "gtin14", "gtin12"):
                if chosen.get(key):
                    offer.gtin = normalize_gtin(chosen.get(key))
                    break
    elif node.get("itemCondition"):
        offer.condition = map_condition(node.get("itemCondition"))
    return offer


def _price_spec(o: dict) -> Any:
    spec = o.get("priceSpecification")
    for s in _as_list(spec):
        if isinstance(s, dict) and s.get("price") is not None:
            return s.get("price")
    return None


def _price_spec_currency(o: dict) -> Any:
    for s in _as_list(o.get("priceSpecification")):
        if isinstance(s, dict) and s.get("priceCurrency"):
            return s.get("priceCurrency")
    return None


def extract_jsonld(soup: BeautifulSoup) -> list[ExtractedOffer]:
    results = []
    for node in _iter_jsonld_nodes(soup):
        t = _types(node)
        if "product" in t or "productgroup" in t or "individualproduct" in t:
            results.append(_offer_from_product(node))
    return results


# --------------------------------------------------------------------------- #
# Microdata
# --------------------------------------------------------------------------- #
def _itemprop_value(tag) -> str | None:
    for attr in ("content", "href", "value", "datetime"):
        if tag.has_attr(attr):
            return str(tag[attr]).strip()
    text = tag.get_text(" ", strip=True)
    return text or None


def extract_microdata(soup: BeautifulSoup) -> list[ExtractedOffer]:
    results = []
    for scope in soup.find_all(attrs={"itemtype": re.compile(r"schema\.org/Product", re.I)}):
        def first(prop: str):
            tag = scope.find(attrs={"itemprop": prop})
            return _itemprop_value(tag) if tag else None

        price = parse_price(first("price") or first("lowPrice"))
        if price is None:
            continue
        results.append(
            ExtractedOffer(
                title=first("name"),
                price=price,
                currency=(first("priceCurrency") or "").upper() or None,
                availability=map_availability(first("availability")),
                gtin=normalize_gtin(first("gtin13") or first("gtin")),
                condition=map_condition(first("itemCondition")),
                method="microdata",
            )
        )
    return results


# --------------------------------------------------------------------------- #
# Meta tags (weak)
# --------------------------------------------------------------------------- #
def _meta(soup: BeautifulSoup, *names: str) -> str | None:
    for n in names:
        tag = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
        if tag and tag.get("content"):
            return str(tag["content"]).strip()
    return None


def extract_meta(soup: BeautifulSoup) -> list[ExtractedOffer]:
    price = parse_price(_meta(soup, "product:price:amount", "og:price:amount"))
    if price is None:
        return []
    return [
        ExtractedOffer(
            title=_meta(soup, "og:title"),
            price=price,
            currency=(_meta(soup, "product:price:currency", "og:price:currency") or "").upper() or None,
            availability=map_availability(_meta(soup, "product:availability", "og:availability")),
            method="meta",
        )
    ]


def page_title(soup: BeautifulSoup) -> str | None:
    t = _meta(soup, "og:title")
    if t:
        return t
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    return h1.get_text(" ", strip=True) if h1 else None


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def extract_candidates(html: str) -> list[ExtractedOffer]:
    """All offers found on the page, best extraction method first."""
    soup = soup_of(html)
    candidates = extract_jsonld(soup) + extract_microdata(soup) + extract_meta(soup)
    fallback_title = page_title(soup)
    for c in candidates:
        if not c.title:
            c.title = fallback_title
    return candidates
