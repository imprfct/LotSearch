"""Parser service for extracting items from web pages."""
from __future__ import annotations

import logging
import re
import time
from typing import List, Optional

import requests
from requests import Session
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
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
        self.session = session or self._create_session()
        if session is not None:
            headers = getattr(self.session, "headers", None)
            if headers is not None and hasattr(headers, "update"):
                headers.update(self.headers)
        self.last_error: Optional[Exception] = None
        self.last_page_url: Optional[str] = None
        self.last_page_load_failed: bool = False
        self.gallery_load_errors: list[tuple[str, Exception]] = []
        self._last_request_time: dict[str, float] = {}

    def _apply_rate_limit(self, url: str) -> None:
        """Apply rate limiting based on domain."""
        parsed = urlparse(url)
        domain = parsed.netloc
        delay = settings.REQUEST_DELAY_SECONDS
        
        if domain in self._last_request_time:
            elapsed = time.time() - self._last_request_time[domain]
            if elapsed < delay:
                sleep_time = delay - elapsed
                logger.debug("Rate limiting: sleeping %.2fs for %s", sleep_time, domain)
                time.sleep(sleep_time)
        
        self._last_request_time[domain] = time.time()

    def get_page_content(self, url: str) -> Optional[str]:
        """Fetch HTML content from an URL."""
        self._apply_rate_limit(url)
        self.last_error = None
        self.last_page_url = None
        self.last_page_load_failed = False
        timeout = settings.REQUEST_TIMEOUT
        try:
            response = self.session.get(url, headers=self.headers, timeout=timeout)
            response.raise_for_status()
            self.last_page_url = getattr(response, "url", url)
            return response.text
        except requests.Timeout as exc:
            self.last_error = exc
            self.last_page_load_failed = True
            logger.warning("Timeout fetching page %s: %s", url, exc)
            return None
        except requests.ConnectionError as exc:
            self.last_error = exc
            self.last_page_load_failed = True
            logger.warning("Connection error fetching page %s: %s", url, exc)
            logger.debug("Connection error details", exc_info=True)
            return None
        except requests.HTTPError as exc:
            self.last_error = exc
            self.last_page_load_failed = True
            status_code = getattr(exc.response, "status_code", "unknown")
            logger.error("HTTP error fetching page %s (status %s)", url, status_code)
            logger.debug("HTTP error details", exc_info=True)
            return None
        except requests.RequestException as e:
            self.last_error = e
            self.last_page_load_failed = True
            logger.error("Error fetching page %s: %s", url, e)
            logger.debug("Unhandled request exception", exc_info=True)
            return None

    def parse_items(self, html: str, base_url: Optional[str] = None) -> List[Item]:
        """Parse items from HTML content."""
        soup = BeautifulSoup(html, 'html.parser')
        items = []
        base = base_url or BASE_URL
        self.gallery_load_errors.clear()

        for card in soup.find_all('div', class_='item-type-card__card'):
            try:
                link_tag = card.find('a', href=lambda x: x and '/lot/' in x)
                if not link_tag:
                    continue

                raw_link = link_tag.get('href', '')
                link = raw_link if raw_link.startswith('http') else urljoin(base, raw_link)
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

    def parse_single_item_page(self, html: str, item_url: str) -> Optional[Item]:
        """Parse a single item from its dedicated page."""
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(html, 'html.parser')
        
        try:
            # Find title - try multiple selectors
            title_tag = (
                soup.select_one('h1.b-lot-page__title') or
                soup.select_one('h1') or
                soup.select_one('.lot-title')
            )
            if not title_tag:
                logger.warning("No title found on %s", item_url)
                return None
            
            title = title_tag.get_text(strip=True)
            
            # Find price - look for price containers
            price = "Цена не указана"
            
            # Извлекаем только белорусские рубли
            # Структура: <span class="b-lot-control__main">355,00&nbsp;<span class="b-lot-control__sub-main">бел. руб.</span>...</span>
            price_main = soup.select_one('.b-lot-control__main')
            if price_main:
                # Валюта находится внутри price_main как вложенный span
                currency_span = price_main.select_one('.b-lot-control__sub-main')
                if currency_span:
                    currency = currency_span.get_text(strip=True)
                    # Проверяем, что это белорусские рубли
                    if 'бел' in currency.lower():
                        # Получаем только прямой текст (без вложенных тегов)
                        # Используем .strings для получения только текстовых узлов
                        price_parts = []
                        for string in price_main.stripped_strings:
                            # Пропускаем текст из вложенных элементов (валюты и справочной информации)
                            if string != currency and 'справочно' not in string.lower() and '$' not in string and '€' not in string:
                                price_parts.append(string)
                        if price_parts:
                            price_value = price_parts[0]  # Берём первую часть (сама цена)
                            price = f"{price_value} {currency}"
            
            # Если не нашли, попробуем другие селекторы
            if price == "Цена не указана":
                price_selectors = [
                    'span.b-lot-control__main',
                    '.b-lot-control__main',
                    '.b-lot-page__price-value',
                    '.lot-price',
                    '.price-value',
                    '[class*="price"]'
                ]
                for selector in price_selectors:
                    price_tag = soup.select_one(selector)
                    if price_tag:
                        price_text = price_tag.get_text(strip=True)
                        # Ищем валюту как следующий элемент (sibling)
                        parent = price_tag.parent
                        if parent:
                            sub_main = parent.select_one('.b-lot-control__sub-main')
                            if sub_main:
                                currency = sub_main.get_text(strip=True)
                                # Берём только белорусские рубли
                                if 'бел' in currency.lower() or 'руб' in currency.lower():
                                    price_text = f"{price_text} {currency}"
                                    if price_text and price_text.lower() != "цена не указана":
                                        price = price_text
                                        break
                        elif price_text and price_text.lower() != "цена не указана":
                            price = price_text
                            break
            
            # Get gallery images
            gallery_urls = self._parse_gallery_images(html, item_url)
            
            # If no gallery, try to find main image
            if not gallery_urls:
                img_selectors = [
                    '.b-lot-media__photo img',
                    '.lot-photo img',
                    '.b-lot-page img[src*="/lot/"]',
                    'img[data-src]',
                ]
                for selector in img_selectors:
                    img_tag = soup.select_one(selector)
                    if img_tag:
                        img_src = img_tag.get('data-src') or img_tag.get('src') or ''
                        img_url = self._normalize_media_url(img_src, item_url)
                        if img_url:
                            gallery_urls = [img_url]
                            break
            
            if not gallery_urls:
                logger.warning("No images found on %s", item_url)
                return None
            
            item = Item(
                url=item_url,
                title=title,
                price=price,
                img_url=gallery_urls[0],
                image_urls=tuple(gallery_urls),
            )
            
            return item
            
        except Exception:
            logger.exception("Error parsing single item page %s", item_url)
            return None

    def get_items_from_url(self, url: str) -> List[Item]:
        """Get all items from a specific URL."""
        html = self.get_page_content(url)
        if not html:
            return []
        base_url = self.last_page_url or url
        return self.parse_items(html, base_url=base_url)

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
            return urljoin(base_url or BASE_URL, candidate)
        return urljoin(base_url or BASE_URL, candidate)

    def _load_item_gallery(self, item_url: str) -> List[str]:
        timeout = settings.REQUEST_TIMEOUT
        try:
            response = self.session.get(item_url, headers=self.headers, timeout=timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.debug("Failed to fetch item gallery for %s: %s", item_url, exc)
            self.gallery_load_errors.append((item_url, exc))
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
                # Не raise сразу при редиректе
                raise_on_redirect=False,
                # Убираем спам в логах от urllib3
                respect_retry_after_header=True,
            )
            adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=20)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
        session.headers.update(self.headers)
        return session
