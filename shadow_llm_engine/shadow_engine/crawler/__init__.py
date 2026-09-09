"""
Shadow-Webcrawler -- Datensammelsystem für das Training.

Pipeline:
    Crawler -> Downloader -> Parser -> Filter -> Qualitätsprüfung
            -> Dataset Manager -> Training

Sicherheitsmerkmale:
    - robots.txt (RobotsChecker)
    - Rate-Limits und Domain-Limits (Downloader)
    - Inhaltsfilter + Admin-Allow-/Block-Listen (ContentFilter / CrawlerAdmin)
    - Review-Queue für gesammelte Daten

Die Crawler-Ausgabe ist über CrawlerSource direkt in die bestehende
Datenpipeline (shadow_engine.dataset) einspeisbar.
"""

from shadow_engine.crawler.crawler import WebCrawler, CrawlStats
from shadow_engine.crawler.downloader import Downloader, ContentFilter, DownloadResult
from shadow_engine.crawler.parser import parse_html, ParsedPage
from shadow_engine.crawler.robots import RobotsChecker
from shadow_engine.crawler.admin import CrawlerAdmin, CrawlSchedule, ReviewEntry

__all__ = [
    "WebCrawler", "CrawlStats",
    "Downloader", "ContentFilter", "DownloadResult",
    "parse_html", "ParsedPage",
    "RobotsChecker",
    "CrawlerAdmin", "CrawlSchedule", "ReviewEntry",
]
