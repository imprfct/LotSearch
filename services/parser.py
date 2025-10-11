"""Parser service for extracting items from web pages."""
from __future__ import annotations

import logging
import re
from typing import List, Optional

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

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

    def __init__(self) -> None:
        self.headers = settings.HEADERS

    def get_page_content(self, url: str) -> Optional[str]:
        """Fetch HTML content from an URL."""
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            logger.exception("Error fetching page %s", url)
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
                img_url = img_tag.get('src', '').strip()
                if img_url and not img_url.startswith('http'):
                    img_url = urljoin(BASE_URL, img_url)
                if not img_url:
                    continue

                price = self._extract_price(list(card.stripped_strings))

                item = Item(
                    url=link,
                    title=title,
                    price=price,
                    img_url=img_url
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
