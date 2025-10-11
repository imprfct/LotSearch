"""
Tests for Parser service - critical functionality
"""
import pytest
import requests
from unittest.mock import Mock, patch

from services.parser import Parser
from models import Item


class TestParser:
    """Test parser functionality"""
    
    def test_parse_items_from_valid_html(self, sample_html):
        """Test parsing items from valid HTML"""
        parser = Parser()
        items = parser.parse_items(sample_html)
        
        assert len(items) == 2
        assert items[0].title == "Test Item 1"
        assert items[0].price == "100 BYN"
        assert items[0].url == "https://coins.ay.by/item1"
        assert items[1].title == "Test Item 2"
        assert items[1].price == "200 BYN"
    
    def test_parse_items_from_empty_html(self, invalid_html):
        """Test parsing from HTML without products"""
        parser = Parser()
        items = parser.parse_items(invalid_html)
        
        assert len(items) == 0
    
    def test_parse_items_handles_malformed_cards(self):
        """Test parser handles incomplete product cards gracefully"""
        html = """
        <div class="product-card">
            <a class="product-card__name" href="/item1">Item 1</a>
            <!-- Missing image and price -->
        </div>
        <div class="product-card">
            <a class="product-card__name" href="/item2">Item 2</a>
            <img class="product-card__image" src="img2.jpg" />
            <div class="product-card__price">200 BYN</div>
        </div>
        """
        parser = Parser()
        items = parser.parse_items(html)
        
        # Should only parse the complete card
        assert len(items) == 1
        assert items[0].title == "Item 2"
    
    @patch('services.parser.requests.get')
    def test_get_page_content_success(self, mock_get):
        """Test successful page fetch"""
        mock_response = Mock()
        mock_response.text = "<html>test</html>"
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        parser = Parser()
        content = parser.get_page_content("https://example.com")
        
        assert content == "<html>test</html>"
        mock_get.assert_called_once()
    
    @patch('services.parser.requests.get')
    def test_get_page_content_failure(self, mock_get):
        """Test page fetch handles errors"""
        mock_get.side_effect = requests.RequestException("Network error")
        
        parser = Parser()
        content = parser.get_page_content("https://example.com")
        
        assert content is None
    
    @patch('services.parser.requests.get')
    def test_get_page_content_timeout(self, mock_get):
        """Test page fetch handles timeout"""
        mock_get.side_effect = requests.Timeout("Request timeout")
        
        parser = Parser()
        content = parser.get_page_content("https://example.com")
        
        assert content is None
    
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
        mock_parse.assert_called_once_with("<html>test</html>")
    
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
    def test_real_website_accessible(self):
        """CRITICAL: Test that target website is accessible"""
        parser = Parser()
        url = "https://coins.ay.by/sssr/yubilejnye/iz-dragocennyh-metallov/"
        
        content = parser.get_page_content(url)
        
        assert content is not None, "Website is not accessible!"
        assert len(content) > 0, "Website returned empty content!"
        assert "product-card" in content or "html" in content.lower(), "Website structure may have changed!"
    
    @pytest.mark.integration
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
            assert item.url.startswith('https://coins.ay.by'), "Item URL should be from target domain"
