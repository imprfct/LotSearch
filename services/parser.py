"""
Parser service for extracting items from web pages
"""
import logging
from typing import List, Optional
from bs4 import BeautifulSoup
import requests

from config import settings
from models import Item

logger = logging.getLogger(__name__)


class Parser:
    """Web page parser for extracting product information"""
    
    def __init__(self):
        self.headers = settings.HEADERS
    
    def get_page_content(self, url: str) -> Optional[str]:
        """
        Fetch HTML content from URL
        
        Args:
            url: URL to fetch
            
        Returns:
            HTML content as string or None if error occurred
        """
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            logger.error(f"Error fetching page {url}: {e}")
            return None
    
    def parse_items(self, html: str) -> List[Item]:
        """
        Parse items from HTML content
        
        Args:
            html: HTML content to parse
            
        Returns:
            List of parsed Item objects
        """
        soup = BeautifulSoup(html, 'html.parser')
        items = []
        
        for card in soup.find_all('div', class_='product-card'):
            try:
                link_tag = card.find('a', class_='product-card__name')
                img_tag = card.find('img', class_='product-card__image')
                price_tag = card.find('div', class_='product-card__price')
                
                if link_tag and img_tag and price_tag:
                    link = 'https://coins.ay.by' + link_tag.get('href')
                    title = link_tag.get_text(strip=True)
                    price = price_tag.get_text(strip=True)
                    img_url = img_tag.get('src')
                    
                    item = Item(
                        url=link,
                        title=title,
                        price=price,
                        img_url=img_url
                    )
                    items.append(item)
            except Exception as e:
                logger.warning(f"Error parsing item: {e}")
                continue
        
        logger.info(f"Parsed {len(items)} items")
        return items
    
    def get_items_from_url(self, url: str) -> List[Item]:
        """
        Get all items from a specific URL
        
        Args:
            url: URL to parse
            
        Returns:
            List of Item objects
        """
        html = self.get_page_content(url)
        if not html:
            return []
        
        return self.parse_items(html)
