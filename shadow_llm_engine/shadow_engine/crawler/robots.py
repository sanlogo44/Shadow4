"""
robots.txt-Prüfung für den Shadow-Webcrawler.

Nutzt die Standardbibliothek (urllib.robotparser) zur Auswertung von
robots.txt-Dateien. Jeder Domain wird einmalig ein RobotFileParser
zugeordnet und gecacht.
"""

from __future__ import annotations

import urllib.robotparser
from typing import Optional
from urllib.parse import urlparse


class RobotsChecker:
    """Prüft, ob eine URL gemäß robots.txt der Domain gecrawlt werden darf."""

    def __init__(self, user_agent: str = "shadow-crawler", fetch_timeout: float = 5.0):
        self.user_agent = user_agent
        self.fetch_timeout = fetch_timeout
        self._cache: dict[str, urllib.robotparser.RobotFileParser] = {}

    def _robots_url(self, url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    def _get_parser(self, url: str) -> Optional[urllib.robotparser.RobotFileParser]:
        robots_url = self._robots_url(url)
        if robots_url in self._cache:
            return self._cache[robots_url]
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        try:
            rp.read()
        except Exception:
            # Wenn robots.txt nicht lesbar ist, erlauben wir das Crawling
            # nicht blind -- wir behandeln die Domain als "keine robots.txt"
            # und erlauben nur, wenn der Admin die Domain freigegeben hat
            # (siehe ContentFilter / CrawlerAdmin). Hier cachen wir "keine
            # robots.txt" als None.
            self._cache[robots_url] = None  # type: ignore
            return None
        self._cache[robots_url] = rp
        return rp

    def allowed(self, url: str) -> bool:
        """True, wenn die URL laut robots.txt gecrawlt werden darf."""
        parser = self._get_parser(url)
        if parser is None:
            return True  # keine robots.txt -> erlaubt (Admin-Filter greift zusätzlich)
        try:
            return parser.can_fetch(self.user_agent, url)
        except Exception:
            return False

    def crawl_delay(self, url: str) -> Optional[float]:
        parser = self._get_parser(url)
        if parser is None:
            return None
        try:
            delay = parser.crawl_delay(self.user_agent)
            return float(delay) if delay is not None else None
        except Exception:
            return None
