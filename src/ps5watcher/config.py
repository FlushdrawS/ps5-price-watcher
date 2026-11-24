"""Load and validate config/sources.toml."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .ids import normalize_gtin

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "sources.toml"

VALID_KINDS = {"retailer", "comparison"}
VALID_FETCHERS = {"http", "playwright"}
VALID_EXTRACTORS = {"generic", "amazon", "ceconomy", "idealo"}


class ConfigError(ValueError):
    pass


def _dec(value, name: str) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception as exc:  # noqa: BLE001
        raise ConfigError(f"{name}: not a number: {value!r}") from exc


@dataclass(frozen=True)
class Settings:
    target_total_eur: Decimal = Decimal("500")
    timezone: str = "Europe/Berlin"
    normal_interval_hours: int = 3
    friday_interval_minutes: int = 15
    significant_drop_eur: Decimal = Decimal("10")
    significant_drop_pct: Decimal = Decimal("3")
    target_reminder_hours: int = 24
    notify_unverified_candidates: bool = True
    notify_out_of_stock: bool = True
    failure_alert_after: int = 4
    min_plausible_eur: Decimal = Decimal("250")
    max_plausible_eur: Decimal = Decimal("1500")
    request_timeout_s: int = 25
    delay_between_sources_s: float = 2.0
    report_interval_hours: int = 3
    history_retention_days: int = 400


@dataclass(frozen=True)
class ProductSpec:
    name: str = "PlayStation 5 Digital Edition 825 GB (CFI-2100)"
    expected_gtins: frozenset[str] = frozenset()
    reject_gtins: frozenset[str] = frozenset()
    extra_exclude_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceConfig:
    id: str
    name: str
    kind: str = "retailer"
    url: str = ""
    enabled: bool = True
    fetcher: str = "http"
    extractor: str = "generic"
    integration_tested: bool = False
    shipping_eur: Decimal | None = None
    free_shipping_from_eur: Decimal | None = None
    required_seller: tuple[str, ...] = ()
    first_party_shop: bool = False  # shop has no marketplace: the shop itself is the seller
    article_id: str = ""  # retailer article number (MediaMarkt/Saturn)
    url_identity_verified: bool = False  # a human confirmed this URL is the 825 GB console
    url_identity_evidence: str = ""
    require_visible_price: bool = True  # price must also be printed on the page
    notes: str = ""

    @property
    def is_comparison(self) -> bool:
        return self.kind == "comparison"


@dataclass(frozen=True)
class AppConfig:
    settings: Settings
    product: ProductSpec
    sources: tuple[SourceConfig, ...] = field(default_factory=tuple)

    def source(self, source_id: str) -> SourceConfig:
        for s in self.sources:
            if s.id == source_id:
                return s
        raise KeyError(source_id)


def _norm_gtins(values) -> frozenset[str]:
    out = set()
    for v in values or []:
        g = normalize_gtin(v)
        if not g:
            raise ConfigError(f"invalid EAN/GTIN in config: {v!r}")
        out.add(g)
    return frozenset(out)


def load_config(path: str | os.PathLike | None = None) -> AppConfig:
    path = Path(path or os.environ.get("PS5W_CONFIG") or DEFAULT_CONFIG)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    s = raw.get("settings", {})
    defaults = Settings()
    settings = Settings(
        target_total_eur=_dec(s.get("target_total_eur", defaults.target_total_eur), "target_total_eur"),
        timezone=s.get("timezone", defaults.timezone),
        normal_interval_hours=int(s.get("normal_interval_hours", defaults.normal_interval_hours)),
        friday_interval_minutes=int(s.get("friday_interval_minutes", defaults.friday_interval_minutes)),
        significant_drop_eur=_dec(s.get("significant_drop_eur", defaults.significant_drop_eur), "significant_drop_eur"),
        significant_drop_pct=_dec(s.get("significant_drop_pct", defaults.significant_drop_pct), "significant_drop_pct"),
        target_reminder_hours=int(s.get("target_reminder_hours", defaults.target_reminder_hours)),
        notify_unverified_candidates=bool(s.get("notify_unverified_candidates", defaults.notify_unverified_candidates)),
        notify_out_of_stock=bool(s.get("notify_out_of_stock", defaults.notify_out_of_stock)),
        failure_alert_after=int(s.get("failure_alert_after", defaults.failure_alert_after)),
        min_plausible_eur=_dec(s.get("min_plausible_eur", defaults.min_plausible_eur), "min_plausible_eur"),
        max_plausible_eur=_dec(s.get("max_plausible_eur", defaults.max_plausible_eur), "max_plausible_eur"),
        request_timeout_s=int(s.get("request_timeout_s", defaults.request_timeout_s)),
        delay_between_sources_s=float(s.get("delay_between_sources_s", defaults.delay_between_sources_s)),
        report_interval_hours=int(s.get("report_interval_hours", defaults.report_interval_hours)),
        history_retention_days=int(s.get("history_retention_days", defaults.history_retention_days)),
    )
    if not (1 <= settings.normal_interval_hours <= 24) or 24 % settings.normal_interval_hours:
        raise ConfigError("normal_interval_hours must divide 24 (1, 2, 3, 4, 6, 8, 12, 24)")
    if not (5 <= settings.friday_interval_minutes <= 60) or 60 % settings.friday_interval_minutes:
        raise ConfigError("friday_interval_minutes must divide 60 and be >= 5")
    if not (1 <= settings.report_interval_hours <= 24) or 24 % settings.report_interval_hours:
        raise ConfigError("report_interval_hours must divide 24")

    p = raw.get("product", {})
    product = ProductSpec(
        name=p.get("name", ProductSpec.name),
        expected_gtins=_norm_gtins(p.get("expected_gtins")),
        reject_gtins=_norm_gtins(p.get("reject_gtins")),
        extra_exclude_terms=tuple(str(t).lower() for t in p.get("extra_exclude_terms", [])),
    )

    sources = []
    seen = set()
    for i, src in enumerate(raw.get("sources", [])):
        sid = src.get("id")
        if not sid:
            raise ConfigError(f"sources[{i}] is missing 'id'")
        if sid in seen:
            raise ConfigError(f"duplicate source id: {sid}")
        seen.add(sid)
        sc = SourceConfig(
            id=sid,
            name=src.get("name", sid),
            kind=src.get("kind", "retailer"),
            url=(src.get("url") or "").strip(),
            enabled=bool(src.get("enabled", True)),
            fetcher=src.get("fetcher", "http"),
            extractor=src.get("extractor", "generic"),
            integration_tested=bool(src.get("integration_tested", False)),
            shipping_eur=_dec(src.get("shipping_eur"), f"{sid}.shipping_eur"),
            free_shipping_from_eur=_dec(src.get("free_shipping_from_eur"), f"{sid}.free_shipping_from_eur"),
            required_seller=tuple(str(x).lower() for x in src.get("required_seller", [])),
            first_party_shop=bool(src.get("first_party_shop", False)),
            article_id=str(src.get("article_id", "") or ""),
            url_identity_verified=bool(src.get("url_identity_verified", False)),
            url_identity_evidence=src.get("url_identity_evidence", ""),
            require_visible_price=bool(src.get("require_visible_price", True)),
            notes=src.get("notes", ""),
        )
        if sc.kind not in VALID_KINDS:
            raise ConfigError(f"{sid}: kind must be one of {sorted(VALID_KINDS)}")
        if sc.fetcher not in VALID_FETCHERS:
            raise ConfigError(f"{sid}: fetcher must be one of {sorted(VALID_FETCHERS)}")
        if sc.extractor not in VALID_EXTRACTORS:
            raise ConfigError(f"{sid}: extractor must be one of {sorted(VALID_EXTRACTORS)}")
        if sc.extractor == "ceconomy" and sc.url and not sc.article_id:
            raise ConfigError(f"{sid}: extractor 'ceconomy' needs article_id")
        if sc.url_identity_verified and not sc.url_identity_evidence:
            raise ConfigError(f"{sid}: url_identity_verified needs url_identity_evidence")
        if sc.integration_tested and not sc.url:
            raise ConfigError(f"{sid}: integration_tested without url")
        if sc.url and not sc.url.startswith("https://"):
            raise ConfigError(f"{sid}: url must start with https://")
        sources.append(sc)

    return AppConfig(settings=settings, product=product, sources=tuple(sources))
