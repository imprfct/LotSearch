"""Bot package initialization"""
from .handlers import router
from .filters import IsAdmin

__all__ = ['router', 'IsAdmin']
