"""
Configuration module for loading environment variables
"""
import os
from typing import List
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Settings:
    """Application settings loaded from environment variables"""
    
    # Bot configuration
    BOT_TOKEN: str = os.getenv('BOT_TOKEN', '')
    ADMIN_CHAT_IDS: List[int] = [
        int(chat_id.strip()) 
        for chat_id in os.getenv('ADMIN_CHAT_IDS', '').split(',') 
        if chat_id.strip()
    ]
    
    # Monitoring configuration
    CHECK_INTERVAL_MINUTES: int = int(os.getenv('CHECK_INTERVAL_MINUTES', '60'))
    
    # URLs to monitor
    MONITOR_URLS: List[str] = os.getenv(
        'MONITOR_URLS',
        'https://coins.ay.by/sssr/yubilejnye/iz-dragocennyh-metallov/,https://coins.ay.by/rossiya/?f=1&ti1=6/'
    ).split(',')
    
    # HTTP headers for requests
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    def validate(self) -> None:
        """Validate required settings"""
        if not self.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is required in .env file")
        if not self.ADMIN_CHAT_IDS:
            raise ValueError("ADMIN_CHAT_IDS is required in .env file")


# Create global settings instance
settings = Settings()
