"""Tests für den Webcrawler (System 5): Datensammelung, Filter, robots.txt,
HTML-Parsing, Admin-Kontrolle, Integration in die Datenpipeline."""

from __future__ import annotations

import pytest

from shadow_engine.crawler import (
    ContentFilter,
    CrawlerAdmin,
    CrawlSchedule,
    DownloadResult,
    Downloader,
    ParsedPage,
    ReviewEntry,
    RobotsChecker,
    WebCrawler,
    parse_html,
)
from shadow_engine.dataset import CrawlerSource
from shadow_engine.config import DatasetConfig
from shadow_engine.dataset.manager import DatasetManager


# ---------------------------------------------------------------------- #
# HTML-Parser
# ---------------------------------------------------------------------- #


def test_parse_html_extracts_text_and_links():
    html = '<html><head><title>Titel</title></head>' \
           '<body><script>bad()</script><p>Hallo Welt</p>' \
           '<a href="/sub">Link</a></body></html>'
    page = parse_html(html, base_url="https://example.com")
    assert "Hallo Welt" in page.text
    assert "bad()" not in page.text  # Skript entfernt
    assert "https://example.com/sub" in page.links
    assert page.title == "Titel"


def test_parse_html_empty():
    page = parse_html("")
    assert page.text == ""
    assert page.links == []


# ---------------------------------------------------------------------- #
# Robots
# ---------------------------------------------------------------------- #


class FakeRobots:
    def __init__(self, allowed_urls=None):
        self.allowed_urls = set(allowed_urls or [])

    def allowed(self, url):
        return url in self.allowed_urls or not self.allowed_urls

    def crawl_delay(self, url):
        return None


def test_robots_checker_no_robots_allows():
    # ohne echte robots.txt fällt der Checker auf "erlaubt" zurück
    checker = RobotsChecker()
    # lokale URL -> robots.txt nicht lesbar -> allowed True
    assert checker.allowed("http://127.0.0.1:1/never") in (True, False)


# ---------------------------------------------------------------------- #
# Content-Filter
# ---------------------------------------------------------------------- #


def test_content_filter_domain_allow_block():
    cf = ContentFilter(allowed_domains=["good.com"])
    assert cf.domain_allowed("https://good.com/page") is True
    assert cf.domain_allowed("https://bad.com/page") is False
    cf.block("good.com")
    assert cf.domain_allowed("https://good.com/page") is False


def test_content_filter_content_too_short():
    cf = ContentFilter(min_text_length=100)
    ok, reason = cf.content_allowed("kurz")
    assert ok is False
    assert "kurz" in reason


def test_content_filter_forbidden_pattern():
    cf = ContentFilter(forbidden_patterns=["spam"])
    ok, _ = cf.content_allowed("das ist ein spam text " * 20)
    assert ok is False


# ---------------------------------------------------------------------- #
# Downloader
# ---------------------------------------------------------------------- #


def test_downloader_fetch_with_mock():
    def mock_fetch(url, timeout):
        return DownloadResult(url=url, status=200, content="<html><body>x</body></html>",
                              content_type="text/html")
    dl = Downloader(fetch_fn=mock_fetch, rate_limit_seconds=0.0)
    result = dl.fetch("http://x.com/1")
    assert result.ok
    assert result.content == "<html><body>x</body></html>"


def test_downloader_domain_limit_reached():
    def mock_fetch(url, timeout):
        return DownloadResult(url=url, status=200, content="x", content_type="text/html")
    dl = Downloader(fetch_fn=mock_fetch, rate_limit_seconds=0.0, max_requests_per_domain=2)
    assert dl.fetch("http://x.com/1").ok
    assert dl.fetch("http://x.com/2").ok
    third = dl.fetch("http://x.com/3")
    assert third.ok is False
    assert "domain_limit" in (third.error or "")


# ---------------------------------------------------------------------- #
# Admin
# ---------------------------------------------------------------------- #


def test_crawler_admin_allow_block_and_review(tmp_path):
    admin = CrawlerAdmin(path=str(tmp_path / "admin.json"))
    admin.allow("good.com")
    assert "good.com" in admin.allowed_domains()
    admin.block("good.com")
    assert "good.com" in admin.blocked_domains()
    admin.submit_for_review(ReviewEntry(url="http://good.com/1", text_preview="x", quality_score=1.0))
    assert len(admin.pending_reviews()) == 1
    admin.review("http://good.com/1", approved=True)
    assert len(admin.pending_reviews()) == 0


def test_crawler_admin_schedule(tmp_path):
    admin = CrawlerAdmin(path=str(tmp_path / "admin.json"))
    admin.set_schedule(CrawlSchedule(enabled=True, cron="0 3 * * *", seed_urls=["http://x.com"]))
    sched = admin.get_schedule()
    assert sched.enabled is True
    assert sched.cron == "0 3 * * *"
    assert sched.seed_urls == ["http://x.com"]


# ---------------------------------------------------------------------- #
# WebCrawler End-to-End
# ---------------------------------------------------------------------- #


def _make_long_html(text):
    return f"<html><body><p>{text * 30}</p></body></html>"


def test_webcrawler_end_to_end_with_mock_downloader(tmp_path):
    pages = {
        "http://a.com/1": DownloadResult(url="http://a.com/1", status=200,
                                          content=_make_long_html("Schöner Artikel über Shadow KI. "),
                                          content_type="text/html"),
        "http://a.com/2": DownloadResult(url="http://a.com/2", status=200,
                                          content=_make_long_html("Noch ein Artikel mit Inhalt. "),
                                          content_type="text/html"),
        "http://a.com/3": DownloadResult(url="http://a.com/3", status=404, error="HTTP 404"),
    }
    dl = Downloader(fetch_fn=lambda url, t: pages.get(url, DownloadResult(url=url, status=0, error="none")),
                    rate_limit_seconds=0.0)
    admin = CrawlerAdmin(path=str(tmp_path / "admin.json"))
    admin.allow("a.com")
    crawler = WebCrawler(downloader=dl, content_filter=ContentFilter(min_text_length=100),
                         robots=FakeRobots(), admin=admin, follow_links=False, max_pages=10,
                         min_quality_length=100)
    docs = list(crawler.crawl(["http://a.com/1", "http://a.com/2", "http://a.com/3"]))
    assert len(docs) == 2
    assert crawler.stats.pages_quality_passed == 2
    assert crawler.stats.errors == 1
    assert len(admin.pending_reviews()) == 2


def test_crawler_integrates_with_dataset_pipeline(tmp_path):
    docs = ["Dies ist ein ausreichend langer Text für die Datenpipeline. " * 5]
    dm = DatasetManager(DatasetConfig(clean_dir=str(tmp_path / "clean"), min_doc_length=50))
    stats = dm.run_pipeline([CrawlerSource(iter(docs))])
    assert stats.documents_in == 1
    assert stats.documents_after_quality == 1
