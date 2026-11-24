from conftest import load

from ps5watcher.fetch import classify, detect_block
from ps5watcher.models import FetchStatus


def test_amazon_captcha_detected():
    assert detect_block(200, load("blocked_amazon_captcha.html")) == "amazon captcha"


def test_cloudflare_detected():
    assert detect_block(200, load("blocked_cloudflare.html")) == "cloudflare challenge"


def test_normal_page_with_recaptcha_widget_not_blocked():
    assert detect_block(200, load("jsonld_in_stock.html")) is None


def test_status_codes():
    assert classify("u", 403, "", "u", "t").status == FetchStatus.BLOCKED
    assert classify("u", 429, "", "u", "t").status == FetchStatus.BLOCKED
    assert classify("u", 404, "", "u", "t").status == FetchStatus.NOT_FOUND
    assert classify("u", 500, "", "u", "t").status == FetchStatus.HTTP_ERROR
    assert classify("u", 200, "<html></html>", "u", "t").status == FetchStatus.OK


def test_waiting_room_by_final_url():
    r = classify("https://direct.playstation.com/x", 200, "<html></html>", "https://sony.queue-it.net/?c=x", "t")
    assert r.status == FetchStatus.BLOCKED
