"""
Data models for the application
"""
from dataclasses import dataclass


@dataclass
class Item:
    """Represents a lot/item from the website"""
    url: str
    title: str
    price: str
    img_url: str
    
    def __hash__(self):
        """Make Item hashable by URL"""
        return hash(self.url)
    
    def __eq__(self, other):
        """Items are equal if they have the same URL"""
        if not isinstance(other, Item):
            return False
        return self.url == other.url
