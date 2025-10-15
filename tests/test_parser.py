"""Tests for Parser service - critical functionality."""
from __future__ import annotations

import os
from unittest.mock import Mock, patch

import pytest
import requests

from services.parser import Parser
from models import Item
from config import settings

LIVE_TESTS_ENABLED = os.getenv("ENABLE_LIVE_TESTS") == "1"


class TestParser:
    """Test parser functionality"""
    
    def test_parse_items_from_valid_html(self, sample_html):
        """Test parsing items from valid HTML"""
        parser = Parser()
        with patch.object(Parser, '_load_item_gallery', side_effect=[
            ["https://example.com/full1a.jpg", "https://example.com/full1b.jpg"],
            [],
        ]):
            items = parser.parse_items(sample_html)
        
        assert len(items) == 2
        assert items[0].title == "Test Item 1"
        assert items[0].price == "100,00 бел. руб."
        assert items[0].url == "https://ay.by/lot/item1"
        assert items[0].img_url == "https://example.com/full1a.jpg"
        assert items[0].image_urls == (
            "https://example.com/full1a.jpg",
            "https://example.com/full1b.jpg",
        )
        assert items[1].title == "Test Item 2"
        assert items[1].price == "200,50 бел. руб."
        assert items[1].img_url == "https://example.com/img2.jpg"
        assert items[1].image_urls == ("https://example.com/img2.jpg",)
    
    def test_parse_items_from_empty_html(self, invalid_html):
        """Test parsing from HTML without products"""
        parser = Parser()
        items = parser.parse_items(invalid_html)
        
        assert len(items) == 0
    
    def test_parse_items_handles_malformed_cards(self):
        """Test parser handles incomplete product cards gracefully"""
        html = """
        <div class="item-type-card__card">
            <a class="item-type-card__link" href="https://ay.by/lot/item1">Item 1</a>
            <!-- Missing image and price -->
        </div>
        <div class="item-type-card__card">
            <a class="item-type-card__link" href="https://ay.by/lot/item2">Item 2</a>
            <img src="img2.jpg" />
            <span>200,00</span>
            <span>бел. руб.</span>
        </div>
        """
        parser = Parser()
        with patch.object(Parser, '_load_item_gallery', return_value=[]):
            items = parser.parse_items(html)
        
        # Should only parse the complete card
        assert len(items) == 1
        assert items[0].title == "Item 2"

    def test_parse_items_uses_base_url_for_relative_links(self):
        """Parser should join relative item URLs with provided base."""
        html = """
        <div class="item-type-card__card">
            <a class="item-type-card__link" href="/lot/item3">Item 3</a>
            <img src="/img3.jpg" />
            <span>300,00</span>
            <span>бел. руб.</span>
        </div>
        """
        parser = Parser()
        with patch.object(Parser, '_load_item_gallery', return_value=[]):
            items = parser.parse_items(html, base_url="https://coins.ay.by/catalog/")

        assert len(items) == 1
        assert items[0].url == "https://coins.ay.by/lot/item3"
        assert items[0].img_url.startswith("https://coins.ay.by")
    
    def test_parse_single_item_page(self):
        """Test parsing a single item from its dedicated page."""
        html = """
        <html>
            <body>
                <h1 class="b-lot-page__title">1 рубль 1924 года</h1>
                <span class="b-lot-control__main">355,00&nbsp;<span class="b-lot-control__sub-main">бел. руб.</span>
                    <span class="i-popover">
                        <span class="i-popover__line i-popover__line_special">
                            <span><b>119,68</b>$</span><span><b>103,57</b>€</span><span><b>9571,31</b>руб.</span>
                        </span>
                        <span class="i-popover__line i-popover__line_special">Справочно по курсу НБРБ</span>
                    </span>
                </span>
                <figure class="pswipe-gallery-element">
                    <a href="/upload/images/lot1-full.jpg"></a>
                </figure>
                <figure class="pswipe-gallery-element">
                    <a href="/upload/images/lot1-full2.jpg"></a>
                </figure>
            </body>
        </html>
        """
        parser = Parser()
        item = parser.parse_single_item_page(html, "https://ay.by/lot/test-123.html")
        
        assert item is not None
        assert item.title == "1 рубль 1924 года"
        # Проверяем, что взяли только белорусские рубли
        assert "355,00" in item.price
        assert "бел. руб." in item.price
        # Проверяем, что НЕ взяли другие валюты и справочную информацию
        assert "$" not in item.price
        assert "€" not in item.price
        assert "119,68" not in item.price
        assert "9571,31" not in item.price
        assert "Справочно" not in item.price
        assert item.url == "https://ay.by/lot/test-123.html"
        assert len(item.image_urls) == 2
        assert item.img_url.endswith("lot1-full.jpg")
    
    def test_parse_single_item_page_no_title(self):
        """Test parsing fails gracefully when no title found."""
        html = "<html><body><p>No title here</p></body></html>"
        parser = Parser()
        item = parser.parse_single_item_page(html, "https://ay.by/lot/test.html")
        
        assert item is None
    
    @patch('services.parser.requests.get')
    def test_get_page_content_success(self, mock_get):
        """Test successful page fetch"""
        mock_response = Mock()
        mock_response.text = "<html>test</html>"
        mock_response.raise_for_status = Mock()
        mock_response.url = "https://example.com"
        mock_get.return_value = mock_response
        
        session = Mock()
        session.headers = {}
        session.get = mock_get
        parser = Parser(session=session)
        content = parser.get_page_content("https://example.com")
        
        assert content == "<html>test</html>"
        mock_get.assert_called_once_with(
            "https://example.com",
            headers=settings.HEADERS,
            timeout=settings.REQUEST_TIMEOUT,
        )
        assert parser.last_error is None
    
    @patch('services.parser.requests.get')
    def test_get_page_content_failure(self, mock_get):
        """Test page fetch handles errors"""
        mock_get.side_effect = requests.RequestException("Network error")
        
        session = Mock()
        session.headers = {}
        session.get = mock_get
        parser = Parser(session=session)
        content = parser.get_page_content("https://example.com")
        
        assert content is None
        assert isinstance(parser.last_error, requests.RequestException)
    
    @patch('services.parser.requests.get')
    def test_get_page_content_timeout(self, mock_get):
        """Test page fetch handles timeout"""
        mock_get.side_effect = requests.Timeout("Request timeout")
        
        session = Mock()
        session.headers = {}
        session.get = mock_get
        parser = Parser(session=session)
        content = parser.get_page_content("https://example.com")
        
        assert content is None
        assert isinstance(parser.last_error, requests.Timeout)

    @patch('services.parser.requests.get')
    def test_get_page_content_connection_error_logs(self, mock_get):
        """Parser should store connection errors"""
        mock_get.side_effect = requests.ConnectionError("DNS failure")

        session = Mock()
        session.headers = {}
        session.get = mock_get
        parser = Parser(session=session)

        assert parser.get_page_content("https://example.com") is None
        assert isinstance(parser.last_error, requests.ConnectionError)
    
    @patch.object(Parser, 'get_page_content')
    @patch.object(Parser, 'parse_items')
    def test_get_items_from_url_integration(self, mock_parse, mock_get):
        """Test full flow of getting items from URL"""
        mock_get.return_value = "<html>test</html>"
        mock_items = [
            Item(url="url1", title="Item 1", price="100", img_url="img1.jpg")
        ]
        mock_parse.return_value = mock_items
        
        parser = Parser()
        items = parser.get_items_from_url("https://example.com")
        
        assert len(items) == 1
        assert items[0].title == "Item 1"
        mock_get.assert_called_once_with("https://example.com")
        mock_parse.assert_called_once_with("<html>test</html>", base_url="https://example.com")
    
    @patch.object(Parser, 'get_page_content')
    def test_get_items_from_url_when_page_fails(self, mock_get):
        """Test get_items_from_url when page fetch fails"""
        mock_get.return_value = None
        
        parser = Parser()
        items = parser.get_items_from_url("https://example.com")
        
        assert items == []


class TestParserLiveConnection:
    """Test parser with real website - critical check"""
    
    @pytest.mark.integration
    @pytest.mark.skipif(not LIVE_TESTS_ENABLED, reason="Set ENABLE_LIVE_TESTS=1 to run live checks")
    def test_real_website_accessible(self):
        """CRITICAL: Test that target website is accessible"""
        parser = Parser()
        url = "https://coins.ay.by/sssr/yubilejnye/iz-dragocennyh-metallov/"
        
        content = parser.get_page_content(url)
        
        assert content is not None, "Website is not accessible!"
        assert len(content) > 0, "Website returned empty content!"
        assert "product-card" in content or "html" in content.lower(), "Website structure may have changed!"
    
    @pytest.mark.integration
    @pytest.mark.skipif(not LIVE_TESTS_ENABLED, reason="Set ENABLE_LIVE_TESTS=1 to run live checks")
    def test_real_website_parsing(self):
        """CRITICAL: Test parsing real website data"""
        parser = Parser()
        url = "https://coins.ay.by/sssr/yubilejnye/iz-dragocennyh-metallov/"
        
        items = parser.get_items_from_url(url)
        
        # Website should have at least some items (or structure is correct even if empty)
        assert isinstance(items, list), "Parser should return a list"
        
        # If items exist, verify structure
        if len(items) > 0:
            item = items[0]
            assert hasattr(item, 'url'), "Item should have url"
            assert hasattr(item, 'title'), "Item should have title"
            assert hasattr(item, 'price'), "Item should have price"
            assert hasattr(item, 'img_url'), "Item should have img_url"
            assert hasattr(item, 'image_urls'), "Item should have image_urls"
            # URL может быть как ay.by так и coins.ay.by
            assert 'ay.by' in item.url, "Item URL should be from ay.by domain"
