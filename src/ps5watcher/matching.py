"""Product identity: is this offer really the new PS5 Digital Edition 825 GB?

Rules, strongest first:
  * Used / refurbished / damaged condition            -> REJECT
  * EAN in reject list (known bundles)                -> REJECT
  * EAN in expected list                              -> MATCH
  * Title contains an exclusion (1 TB, Pro, Disc,
    bundle, used, accessory, other platform ...)      -> REJECT
  * Title lacks "PS5/PlayStation 5" or "Digital"      -> REJECT
  * EAN present but not in expected list              -> PROBABLE
  * Title has 825 GB / CFI-21xx / E-Chassis           -> MATCH
  * Otherwise                                         -> PROBABLE
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import ProductSpec
from .models import ExtractedOffer, MatchResult

# (label, regex) - applied to the normalised title.
EXCLUSIONS: list[tuple[str, str]] = [
    # wrong storage / model
    ("1 TB / 2 TB model", r"\b[12]\s?tb\b|\b[12]000\s?gb\b"),
    ("PS5 Pro", r"\bpro\b"),
    ("disc edition", r"\bdis[ck] edition\b|\bmit dis[ck]\b|\bblu ?ray laufwerk\b"),
    ("disc drive (accessory or disc model)", r"(?<!ohne )(?<!ohne dis[ck] )\blaufwerk\b"),
    ("old 2020 launch model", r"\bcfi ?1[0-2]\d\d[a-z]?\b"),
    # bundles
    ("bundle", r"\bbundle\b|\bpaket\b|\bset\b|\bvoucher\b|\bgutschein\b|\bcombo\b"),
    ("bundle (+ extra item)", r"\+"),
    ("bundle (2 controllers)", r"\b(2|zwei)\s?x?\s?(dualsense|controller)|\b2x\b"),
    ("bundle (game)", r"\b(fc ?2\d|fifa|fortnite|call of duty|cod|gran turismo|ghost of|astro bot|wolverine|spider ?man|god of war|ea sports)\b"),
    ("limited / special edition", r"\blimited\b|\banniversary\b|\bsonderedition\b"),
    # condition
    ("used / refurbished", r"\bgebraucht\b|\brefurbished\b|\bgeneral(ü|ue)berholt\b|\bb ?ware\b|\bwie neu\b|\brenewed\b|\bused\b|\bretoure\b|\bzertifiziert\b|\bvorf(ü|ue)hr"),
    # accessories and other products
    ("accessory", r"\bh(ü|ue)lle\b|\bcover\b|\bskin\b|\bfolie\b|\bst(ä|ae)nder\b|\bstandfu(ß|ss)\b|\bvertical stand\b|\bladestation\b|\bfaceplate\b|\babdeckung\b|\bk(ü|ue)hler\b|\bl(ü|ue)fter\b|\btasche\b|\bcase\b|\bfernbedienung\b|\bheadset\b"),
    ("accessory (for PS5)", r"\bf(ü|ue)r (die )?(ps5|playstation)|\bfor (the )?(ps5|playstation)|\bkompatibel\b"),
    ("other product", r"\bportal\b|\bvr ?2\b|\bps4\b|\bxbox\b|\bnintendo\b|\bswitch\b|\bdualsense edge\b"),
]

_PLATFORM_RE = re.compile(r"\bps ?5\b|\bplaystation ?5\b|\bplaystationr5\b")
_DIGITAL_RE = re.compile(r"\bdigital\b|\bdigitale\b")
_STRONG_RE = re.compile(r"\b825\s?gb\b|\b825\b|\bcfi ?21\d\d[a-z]?\b|\be ?chassis\b")


def normalize_title(title: str) -> str:
    t = title.lower()
    t = t.replace("®", " ").replace("™", " ").replace(" ", " ")
    t = re.sub(r"[\-_/|–—:,()\[\]\"']", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


@dataclass
class MatchOutcome:
    result: MatchResult
    reasons: list[str]
    gtin_mismatch: bool = False  # page carries an EAN that is not ours (e.g. reseller EAN)


def title_exclusion(title: str, spec: ProductSpec) -> str | None:
    t = normalize_title(title)
    for label, pattern in EXCLUSIONS:
        if re.search(pattern, t):
            return label
    for term in spec.extra_exclude_terms:
        if term and term in t:
            return f"custom term {term!r}"
    return None


def title_acceptable(title: str, spec: ProductSpec) -> bool:
    """Quick filter for offer lists (idealo): no exclusion, mentions PS5 + Digital."""
    t = normalize_title(title)
    return title_exclusion(title, spec) is None and bool(_PLATFORM_RE.search(t)) and bool(_DIGITAL_RE.search(t))


def match_offer(offer: ExtractedOffer, spec: ProductSpec) -> MatchOutcome:
    if offer.condition in {"used", "refurbished", "damaged"}:
        return MatchOutcome(MatchResult.REJECT, [f"condition is {offer.condition}, not new"])

    if offer.gtin and offer.gtin in spec.reject_gtins:
        return MatchOutcome(MatchResult.REJECT, [f"EAN {offer.gtin} is on the reject list (bundle/other model)"])

    # Title exclusions apply EVEN when the EAN matches: shops sometimes attach the
    # console EAN to bundles or accessories. Conflicting data is rejected.
    excluded = title_exclusion(offer.title, spec) if offer.title else None
    if excluded:
        prefix = f"EAN {offer.gtin} matches but " if offer.gtin in spec.expected_gtins else ""
        return MatchOutcome(MatchResult.REJECT, [f"{prefix}title excluded: {excluded} ({offer.title!r})"])

    if offer.gtin and offer.gtin in spec.expected_gtins:
        return MatchOutcome(MatchResult.MATCH, [f"EAN {offer.gtin} matches"])

    if not offer.title:
        return MatchOutcome(MatchResult.UNKNOWN, ["no product title found"])

    t = normalize_title(offer.title)
    if not _PLATFORM_RE.search(t):
        return MatchOutcome(MatchResult.REJECT, [f"title does not mention PS5 ({offer.title!r})"])
    if not _DIGITAL_RE.search(t):
        return MatchOutcome(MatchResult.REJECT, [f"title does not say Digital ({offer.title!r})"])

    if offer.gtin and spec.expected_gtins:
        return MatchOutcome(
            MatchResult.PROBABLE,
            [f"EAN {offer.gtin} on page is not Sony's EAN for this console (reseller/wrong data?)"],
            gtin_mismatch=True,
        )
    if _STRONG_RE.search(t):
        return MatchOutcome(MatchResult.MATCH, ["title confirms Digital + 825 GB / CFI-21xx"])
    return MatchOutcome(
        MatchResult.PROBABLE,
        ["title lacks 825 GB / CFI-21xx - could be the older 1 TB Slim"],
    )
