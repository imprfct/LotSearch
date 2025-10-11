"""
Pytest configuration and fixtures
"""
import pytest
import os
from typing import Generator


@pytest.fixture
def mock_env_vars(monkeypatch) -> None:
    """Set up test environment variables"""
    monkeypatch.setenv('BOT_TOKEN', 'test_token_123456')
    monkeypatch.setenv('ADMIN_CHAT_IDS', '123456789,987654321')
    monkeypatch.setenv('CHECK_INTERVAL_MINUTES', '60')
    monkeypatch.setenv('MONITOR_URLS', 'https://example.com/page1,https://example.com/page2')


@pytest.fixture
def sample_html() -> str:
    """Sample HTML with product cards for testing parser"""
    return """
    <html>
        <body>
            <div class="product-card">
                <a class="product-card__name" href="/item1">Test Item 1</a>
                <img class="product-card__image" src="https://example.com/img1.jpg" />
                <div class="product-card__price">100 BYN</div>
            </div>
            <div class="product-card">
                <a class="product-card__name" href="/item2">Test Item 2</a>
                <img class="product-card__image" src="https://example.com/img2.jpg" />
                <div class="product-card__price">200 BYN</div>
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
