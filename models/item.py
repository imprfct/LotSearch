"""
Data models for the application
"""
from dataclasses import dataclass
from typing import Tuple


@dataclass(slots=True)
class Item:
    """Represents a lot/item from the website"""
    url: str
    title: str
    price: str
    img_url: str
    image_urls: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.image_urls, tuple):
            object.__setattr__(self, "image_urls", tuple(self.image_urls))
        if self.image_urls and not self.img_url:
            object.__setattr__(self, "img_url", self.image_urls[0])
        elif self.img_url and not self.image_urls:
            object.__setattr__(self, "image_urls", (self.img_url,))
    
    def __hash__(self):
        """Make Item hashable by URL"""
        return hash(self.url)
    
    def __eq__(self, other):
        """Items are equal if they have the same URL"""
        if not isinstance(other, Item):
            return False
        return self.url == other.url
