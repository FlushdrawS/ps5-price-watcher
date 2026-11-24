import pytest

from ps5watcher.config import DEFAULT_CONFIG, ConfigError, load_config

EXPECTED_IDS = ["sony", "amazon", "mediamarkt", "saturn", "otto", "alternate", "expert", "mueller", "idealo"]


def test_shipped_config_loads_all_nine_sources():
    cfg = load_config(DEFAULT_CONFIG)
    assert [s.id for s in cfg.sources] == EXPECTED_IDS
    assert cfg.source("idealo").kind == "comparison"
    assert cfg.settings.target_total_eur == 500
    assert cfg.settings.timezone == "Europe/Berlin"
    assert "0711719020837" in cfg.product.expected_gtins


def test_shipped_config_claims_nothing_is_tested():
    cfg = load_config(DEFAULT_CONFIG)
    assert not any(s.integration_tested for s in cfg.sources)


def write(tmp_path, body):
    p = tmp_path / "c.toml"
    p.write_text(body, encoding="utf-8")
    return p


def test_duplicate_ids_rejected(tmp_path):
    p = write(tmp_path, '[[sources]]\nid="a"\n[[sources]]\nid="a"\n')
    with pytest.raises(ConfigError):
        load_config(p)


def test_bad_fetcher_rejected(tmp_path):
    p = write(tmp_path, '[[sources]]\nid="a"\nfetcher="curl"\n')
    with pytest.raises(ConfigError):
        load_config(p)


def test_http_url_rejected(tmp_path):
    p = write(tmp_path, '[[sources]]\nid="a"\nurl="http://x.example"\n')
    with pytest.raises(ConfigError):
        load_config(p)


def test_bad_interval_rejected(tmp_path):
    p = write(tmp_path, "[settings]\nnormal_interval_hours = 5\n")
    with pytest.raises(ConfigError):
        load_config(p)
