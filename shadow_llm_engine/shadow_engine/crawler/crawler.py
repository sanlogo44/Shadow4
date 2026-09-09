"""
Shadow-Webcrawler -- Datensammelsystem für das Training.

Architektur:

    Crawler -> Downloader -> Parser -> Filter -> Qualitätsprüfung
            -> Dataset Manager -> Training

Der Crawler ist sicherheitsbewusst:
    - robots.txt wird beachtet (RobotsChecker)
    - Rate-Limits und Domain-Limits (Downloader)
    - Inhaltsfilter (ContentFilter) + Admin-Allow-/Block-Listen (CrawlerAdmin)
    - gesammelte Daten können vom Admin geprüft werden (Review-Queue)

Die Schnittstelle `iter_documents()` ist kompatibel mit `CrawlerSource`
aus shadow_engine.dataset, sodass gecrawlte Dokumente direkt in die
bestehende Datenpipeline (Reinigung/Dedup/Qualität/Tokenisierung) eingespeist
werden können -- ohne Änderungen an der Pipeline.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterator, Optional
from urllib.parse import urlparse

from shadow_engine.crawler.admin import CrawlerAdmin, ReviewEntry
from shadow_engine.crawler.downloader import ContentFilter, Downloader, DownloadResult
from shadow_engine.crawler.parser import parse_html
from shadow_engine.crawler.robots import RobotsChecker


@dataclass
class CrawlStats:
    urls_visited: int = 0
    pages_extracted: int = 0
    pages_filtered: int = 0
    pages_quality_passed: int = 0
    errors: int = 0
    robots_blocked: int = 0

    def to_dict(self) -> dict:
        return self.__dict__


class WebCrawler:
    """Orchestriert die vollständige Crawl-Pipeline."""

    def __init__(
        self,
        downloader: Optional[Downloader] = None,
        content_filter: Optional[ContentFilter] = None,
        robots: Optional[RobotsChecker] = None,
        admin: Optional[CrawlerAdmin] = None,
        follow_links: bool = True,
        max_pages: int = 1000,
        min_quality_length: int = 200,
    ):
        self.downloader = downloader or Downloader()
        self.filter = content_filter or ContentFilter(min_text_length=min_quality_length)
        self.robots = robots or RobotsChecker()
        self.admin = admin
        self.follow_links = follow_links
        self.max_pages = max_pages
        self.min_quality_length = min_quality_length
        self.stats = CrawlStats()
        self._visited: set[str] = set()

    def crawl(self, seed_urls: list[str]) -> Iterator[str]:
        """Crawlt ab seed_urls und liefert bereinigte Texte (streaming).

        Die Ausgabe ist ein Iterator von Strings -- kompatibel mit
        `CrawlerSource(iter_documents=...)` aus shadow_engine.dataset.
        """
        queue = list(seed_urls)
        while queue and self.stats.pages_extracted < self.max_pages:
            url = queue.pop(0)
            if url in self._visited:
                continue
            self._visited.add(url)

            # 1. Admin-/Domain-Filter
            if not self.filter.domain_allowed(url):
                self.stats.pages_filtered += 1
                continue
            # Admin-Block-Liste
            if self.admin:
                domain = urlparse(url).netloc
                if domain in self.admin.blocked_domains():
                    self.stats.pages_filtered += 1
                    continue

            # 2. robots.txt
            if not self.robots.allowed(url):
                self.stats.robots_blocked += 1
                continue

            # 3. Download
            self.stats.urls_visited += 1
            result = self.downloader.fetch(url)
            if not result.ok:
                self.stats.errors += 1
                continue

            # 4. Parse
            page = parse_html(result.content, base_url=url)
            if not page.text:
                self.stats.errors += 1
                continue
            self.stats.pages_extracted += 1

            # 5. Inhaltsfilter
            allowed, reason = self.filter.content_allowed(page.text)
            if not allowed:
                self.stats.pages_filtered += 1
                continue

            # 6. Qualitätsprüfung (hier: Mindestlänge)
            if len(page.text) < self.min_quality_length:
                self.stats.pages_filtered += 1
                continue
            self.stats.pages_quality_passed += 1

            # 7. Admin-Review (optional)
            if self.admin:
                self.admin.submit_for_review(ReviewEntry(
                    url=url, text_preview=page.text[:200], quality_score=1.0,
                ))

            yield page.text

            # 8. Links folgen (gleiche Domain)
            if self.follow_links:
                base_domain = urlparse(url).netloc
                for link in page.links:
                    if urlparse(link).netloc == base_domain and link not in self._visited:
                        queue.append(link)

    def iter_documents(self) -> Iterator[str]:
        """Kompatibilitäts-Schnittstelle für CrawlerSource."""
        # Wird typischerweise nach crawl(seed_urls) verwendet;
        # hier als No-Op-Fallback, falls direkt aufgerufen.
        return iter([])

    def crawl_to_documents(self, seed_urls: list[str]) -> Iterator[str]:
        """Alias für crawl()."""
        yield from self.crawl(seed_urls)
