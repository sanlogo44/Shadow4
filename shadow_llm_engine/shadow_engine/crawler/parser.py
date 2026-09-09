"""
HTML-Parser für den Shadow-Webcrawler.

Extrahiert sichtbaren Text aus HTML ohne externe Abhängigkeiten (nur
html.parser der Standardbibliothek). Entfernt Skripte, Styles und
HTML-Tags; liefert bereinigten Fließtext + Metadaten (Titel, Links).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urljoin, urlparse


@dataclass
class ParsedPage:
    url: str
    title: str = ""
    text: str = ""
    links: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


class _TextExtractor(HTMLParser):
    """Sammelt sichtbaren Text und Links; ignoriert Skripte/Styles."""

    _SKIP_TAGS = {"script", "style", "noscript", "iframe"}

    def __init__(self):
        super().__init__()
        self._chunks: list[str] = []
        self._links: list[str] = []
        self._title_parts: list[str] = []
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._links.append(href)
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in ("p", "div", "br", "h1", "h2", "h3", "li"):
            self._chunks.append("\n")

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        if self._in_title:
            self._title_parts.append(data)
        text = data.strip()
        if text:
            self._chunks.append(text + " ")

    @property
    def text(self) -> str:
        return " ".join(self._chunks).strip()

    @property
    def title(self) -> str:
        return "".join(self._title_parts).strip()

    @property
    def links(self) -> list[str]:
        return self._links


def parse_html(html: str, base_url: str = "") -> ParsedPage:
    """Parst HTML und liefert bereinigten Text + Links (absolut gemacht)."""
    extractor = _TextExtractor()
    try:
        extractor.feed(html)
    except Exception:
        pass
    # Links absolut machen, falls Base-URL gegeben
    links = extractor.links
    if base_url:
        links = []
        for href in extractor.links:
            try:
                links.append(urljoin(base_url, href))
            except Exception:
                links.append(href)
    return ParsedPage(
        url=base_url,
        title=extractor.title or _guess_title_from_text(extractor.text),
        text=_normalize_whitespace(extractor.text),
        links=links,
    )


def _guess_title_from_text(text: str) -> str:
    if not text:
        return ""
    return text[:80].strip()


def _normalize_whitespace(text: str) -> str:
    import re
    text = re.sub(r"\s+", " ", text).strip()
    return text
