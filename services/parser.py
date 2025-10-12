"""Parser service for extracting items from web pages."""
from __future__ import annotations

import logging
import re
from typing import List, Optional

import requests
from requests import Session
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from urllib3.util.retry import Retry

from config import settings
from models import Item

logger = logging.getLogger(__name__)
BASE_URL = "https://ay.by"
PRICE_PATTERN = re.compile(
    r"(\d[\d\s]*[\.,]\d{2}|\d[\d\s]*)(?:\s*(?:бел\.\s*)?руб\.?)",
    re.IGNORECASE,
)


class Parser:
    """Web page parser for extracting product information."""

    def __init__(self, session: Optional[Session] = None) -> None:
        self.headers = settings.HEADERS
        self.timeout = settings.REQUEST_TIMEOUT
        self.session = session or self._create_session()
        if session is not None:
            headers = getattr(self.session, "headers", None)
            if headers is not None and hasattr(headers, "update"):
                headers.update(self.headers)
        self.last_error: Optional[Exception] = None

    def get_page_content(self, url: str) -> Optional[str]:
        """Fetch HTML content from an URL."""
        self.last_error = None
        try:
            response = self.session.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.text
        except requests.Timeout as exc:
            self.last_error = exc
            logger.warning("Timeout fetching page %s: %s", url, exc)
            return None
        except requests.ConnectionError as exc:
            self.last_error = exc
            logger.warning("Connection error fetching page %s: %s", url, exc)
            logger.debug("Connection error details", exc_info=True)
            return None
        except requests.HTTPError as exc:
            self.last_error = exc
            status_code = getattr(exc.response, "status_code", "unknown")
            logger.error("HTTP error fetching page %s (status %s)", url, status_code)
            logger.debug("HTTP error details", exc_info=True)
            return None
        except requests.RequestException as e:
            self.last_error = e
            logger.error("Error fetching page %s: %s", url, e)
            logger.debug("Unhandled request exception", exc_info=True)
            return None

    def parse_items(self, html: str) -> List[Item]:
        """Parse items from HTML content."""
        soup = BeautifulSoup(html, 'html.parser')
        items = []

        for card in soup.find_all('div', class_='item-type-card__card'):
            try:
                link_tag = card.find('a', href=lambda x: x and '/lot/' in x)
                if not link_tag:
                    continue

                raw_link = link_tag.get('href', '')
                link = raw_link if raw_link.startswith('http') else urljoin(BASE_URL, raw_link)
                title = link_tag.get_text(strip=True)

                img_tag = card.find('img')
                if not img_tag:
                    continue
                img_url = self._normalize_media_url(img_tag.get('data-src') or img_tag.get('src', ''), link)
                if not img_url:
                    continue

                price = self._extract_price(list(card.stripped_strings))

                gallery_urls = self._load_item_gallery(link)
                if gallery_urls:
                    image_urls = gallery_urls
                else:
                    image_urls = [img_url]

                item = Item(
                    url=link,
                    title=title,
                    price=price,
                    img_url=image_urls[0],
                    image_urls=tuple(image_urls),
                )
                items.append(item)
            except Exception:
                logger.warning("Error parsing item", exc_info=True)
                continue

        logger.info("Parsed %s items", len(items))
        return items

    def get_items_from_url(self, url: str) -> List[Item]:
        """Get all items from a specific URL."""
        html = self.get_page_content(url)
        if not html:
            return []
        return self.parse_items(html)

    @staticmethod
    def _extract_price(text_nodes: List[str]) -> str:
        content = " ".join(text_nodes[1:]) if len(text_nodes) > 1 else ""
        match = PRICE_PATTERN.search(content)
        if not match:
            return "Цена не указана"
        return " ".join(match.group(0).split())

    @staticmethod
    def _normalize_media_url(url: str, base_url: str | None = None) -> str:
        candidate = (url or "").strip()
        if not candidate:
            return ""
        if candidate.startswith("//"):
            return f"https:{candidate}"
        if candidate.startswith("http"):
            return candidate
        if candidate.startswith("/"):
            return urljoin(BASE_URL, candidate)
        return urljoin(base_url or BASE_URL, candidate)

    def _load_item_gallery(self, item_url: str) -> List[str]:
        try:
            response = self.session.get(item_url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.debug("Failed to fetch item gallery for %s: %s", item_url, exc)
            return []

        return self._parse_gallery_images(response.text, item_url)

    def _parse_gallery_images(self, html: str, base_url: str) -> List[str]:
        soup = BeautifulSoup(html, 'html.parser')
        urls: List[str] = []

        for anchor in soup.select('figure.pswipe-gallery-element a[href]'):
            href = anchor.get('href', '').strip()
            normalized = self._normalize_media_url(href, base_url)
            if normalized:
                urls.append(normalized)

        if not urls:
            for img in soup.select('.b-lot-media__photo img, .lot-photo__item img, .b-lot-media__gallery img'):
                candidate = img.get('data-origin') or img.get('data-src') or img.get('src')
                normalized = self._normalize_media_url(candidate, base_url)
                if normalized:
                    urls.append(normalized)

        unique: List[str] = []
        seen = set()
        for media_url in urls:
            if media_url in seen:
                continue
            seen.add(media_url)
            unique.append(media_url)

        return unique

    def _create_session(self) -> Session:
        session = requests.Session()
        retries = settings.REQUEST_MAX_RETRIES
        if retries > 0:
            retry = Retry(
                total=retries,
                connect=retries,
                read=retries,
                backoff_factor=settings.REQUEST_BACKOFF_FACTOR,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET"}),
                raise_on_status=False,
            )
            adapter = HTTPAdapter(max_retries=retry)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
        session.headers.update(self.headers)
        return session
