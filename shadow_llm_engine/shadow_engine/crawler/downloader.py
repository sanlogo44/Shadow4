"""
Downloader und Inhaltsfilter für den Shadow-Webcrawler.

Downloader:
    - lädt eine URL über urllib (Standardbibliothek)
    - respektiert Rate-Limits pro Domain
    - respektiert Domain-Limits (max. Anfragen pro Domain)
    - injizierbar für Tests (fetch_fn)

ContentFilter:
    - Allow-/Block-Listen für Domains
    - Inhaltsfilter (Mindestlänge, verbotene Muster)
    - Admin-Kontrolle: Quellen erlauben/blockieren
"""

from __future__ import annotations

import time
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import urlparse


@dataclass
class DownloadResult:
    url: str
    status: int
    content: str = ""
    content_type: str = ""
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status < 300


class Downloader:
    """Lädt URLs herunter mit Rate-Limiting und Domain-Limits pro Domain."""

    def __init__(
        self,
        rate_limit_seconds: float = 1.0,
        max_requests_per_domain: int = 100,
        timeout: float = 10.0,
        fetch_fn: Optional[Callable[[str, float], DownloadResult]] = None,
    ):
        self.rate_limit = rate_limit_seconds
        self.max_per_domain = max_requests_per_domain
        self.timeout = timeout
        self._fetch_fn = fetch_fn or self._default_fetch
        self._last_request: dict[str, float] = {}
        self._count: dict[str, int] = {}

    def _domain(self, url: str) -> str:
        return urlparse(url).netloc

    def _default_fetch(self, url: str, timeout: float) -> DownloadResult:
        req = urllib.request.Request(url, headers={"User-Agent": "shadow-crawler"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content_type = resp.headers.get("Content-Type", "")
                if "text/html" not in content_type and "text/plain" not in content_type:
                    return DownloadResult(url=url, status=resp.status, content_type=content_type,
                                           error="unsupported_content_type")
                body = resp.read().decode("utf-8", errors="ignore")
                return DownloadResult(url=url, status=resp.status, content=body, content_type=content_type)
        except urllib.error.HTTPError as e:
            return DownloadResult(url=url, status=e.code, error=f"HTTP {e.code}")
        except Exception as e:
            return DownloadResult(url=url, status=0, error=str(e))

    def fetch(self, url: str) -> DownloadResult:
        domain = self._domain(url)
        # Domain-Limit
        if self._count.get(domain, 0) >= self.max_per_domain:
            return DownloadResult(url=url, status=0, error="domain_limit_reached")
        # Rate-Limit
        last = self._last_request.get(domain, 0.0)
        wait = self.rate_limit - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        self._last_request[domain] = time.time()
        self._count[domain] = self._count.get(domain, 0) + 1
        return self._fetch_fn(url, self.timeout)


class ContentFilter:
    """Allow-/Block-Listen für Quellen und Inhaltsfilter."""

    def __init__(
        self,
        allowed_domains: Optional[list[str]] = None,
        blocked_domains: Optional[list[str]] = None,
        min_text_length: int = 200,
        forbidden_patterns: Optional[list[str]] = None,
    ):
        self.allowed_domains = set(allowed_domains or [])
        self.blocked_domains = set(blocked_domains or [])
        self.min_text_length = min_text_length
        self.forbidden_patterns = forbidden_patterns or []

    def domain_allowed(self, url: str) -> bool:
        domain = urlparse(url).netloc
        if domain in self.blocked_domains:
            return False
        if self.allowed_domains and domain not in self.allowed_domains:
            return False
        return True

    def content_allowed(self, text: str) -> tuple[bool, str]:
        if len(text) < self.min_text_length:
            return False, "zu kurz"
        for pattern in self.forbidden_patterns:
            if pattern.lower() in text.lower():
                return False, f"verbotenes Muster: {pattern}"
        return True, ""

    def allow(self, domain: str) -> None:
        self.allowed_domains.add(domain)
        self.blocked_domains.discard(domain)

    def block(self, domain: str) -> None:
        self.blocked_domains.add(domain)
        self.allowed_domains.discard(domain)
