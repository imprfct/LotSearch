"""Pytest configuration and fixtures."""
from __future__ import annotations

import pytest

from config import settings


@pytest.fixture(autouse=True)
def mock_env_vars(monkeypatch) -> None:
    """Set up test environment variables"""
    monkeypatch.setenv('BOT_TOKEN', 'test_token_123456')
    monkeypatch.setenv('ADMIN_CHAT_IDS', '123456789,987654321')
    monkeypatch.setenv('CHECK_INTERVAL_MINUTES', '60')
    monkeypatch.setenv('MONITOR_URLS', 'https://example.com/page1,https://example.com/page2')
    settings.reload()


@pytest.fixture
def sample_html() -> str:
    """Sample HTML with product cards for testing parser"""
    return """
    <html>
        <body>
            <div class="item-type-card__card">
                <a class="item-type-card__link" href="https://ay.by/lot/item1">Test Item 1</a>
                <img src="https://example.com/img1.jpg" />
                <span>100,00</span>
                <span>бел. руб.</span>
            </div>
            <div class="item-type-card__card">
                <a class="item-type-card__link" href="https://ay.by/lot/item2">Test Item 2</a>
                <img src="https://example.com/img2.jpg" />
                <span>200,50</span>
                <span>бел. руб.</span>
            </div>
        </body>
    </html>
    """


@pytest.fixture
def invalid_html() -> str:
    """HTML without product cards"""
    return """
    <html>
        <body>
            <div>No products here</div>
        </body>
    </html>
    """
