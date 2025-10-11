"""
Tests for Item model
"""
from models import Item


class TestItem:
    """Test Item model functionality"""
    
    def test_item_creation(self):
        """Test creating an Item"""
        item = Item(
            url="https://example.com/item1",
            title="Test Item",
            price="100 BYN",
            img_url="https://example.com/img.jpg"
        )
        
        assert item.url == "https://example.com/item1"
        assert item.title == "Test Item"
        assert item.price == "100 BYN"
        assert item.img_url == "https://example.com/img.jpg"
    
    def test_item_equality(self):
        """Test items with same URL are equal"""
        item1 = Item(url="https://example.com/item1", title="Item 1", price="100", img_url="img1.jpg")
        item2 = Item(url="https://example.com/item1", title="Different Title", price="200", img_url="img2.jpg")
        
        assert item1 == item2
    
    def test_item_inequality(self):
        """Test items with different URLs are not equal"""
        item1 = Item(url="https://example.com/item1", title="Item", price="100", img_url="img.jpg")
        item2 = Item(url="https://example.com/item2", title="Item", price="100", img_url="img.jpg")
        
        assert item1 != item2
    
    def test_item_hashable(self):
        """Test items can be used in sets"""
        item1 = Item(url="https://example.com/item1", title="Item 1", price="100", img_url="img1.jpg")
        item2 = Item(url="https://example.com/item1", title="Item 1", price="100", img_url="img1.jpg")
        item3 = Item(url="https://example.com/item2", title="Item 2", price="200", img_url="img2.jpg")
        
        items_set = {item1, item2, item3}
        
        # item1 and item2 have same URL, so set should have only 2 items
        assert len(items_set) == 2
