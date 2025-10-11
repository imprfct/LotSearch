"""Configuration helpers for environment-driven settings."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Tuple

from dotenv import load_dotenv

if os.getenv("PYTEST_CURRENT_TEST") is None:
    load_dotenv()


def _split_csv(value: str) -> Tuple[str, ...]:
    return tuple(entry.strip() for entry in value.split(",") if entry.strip())


@dataclass(slots=True)
class Settings:
    """Runtime application settings sourced from environment variables."""

    BOT_TOKEN: str = field(init=False)
    ADMIN_CHAT_IDS: Tuple[int, ...] = field(init=False)
    CHECK_INTERVAL_MINUTES: int = field(init=False)
    MONITOR_URLS: Tuple[str, ...] = field(init=False)
    HEADERS: dict[str, str] = field(init=False)
    DB_PATH: Path = field(init=False)

    def __post_init__(self) -> None:
        self.reload()

    def reload(self) -> None:
        self.BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
        self.ADMIN_CHAT_IDS = tuple(
            int(chat_id)
            for chat_id in _split_csv(os.getenv("ADMIN_CHAT_IDS", ""))
        )

        try:
            interval = int(os.getenv("CHECK_INTERVAL_MINUTES", "60"))
        except ValueError as exc:
            raise ValueError("CHECK_INTERVAL_MINUTES must be an integer") from exc

        if interval <= 0:
            raise ValueError("CHECK_INTERVAL_MINUTES must be positive")
        self.CHECK_INTERVAL_MINUTES = interval

        urls = _split_csv(
            os.getenv(
                "MONITOR_URLS",
                "https://coins.ay.by/sssr/yubilejnye/iz-dragocennyh-metallov/,https://coins.ay.by/rossiya/?f=1&ti1=6/",
            )
        )
        if not urls:
            raise ValueError("MONITOR_URLS must contain at least one URL")
        self.MONITOR_URLS = urls

        self.HEADERS = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/91.0.4472.124 Safari/537.36"
            )
        }

        db_path_value = os.getenv("DB_PATH", "data/items.db").strip()
        db_path = Path(db_path_value)
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path
        self.DB_PATH = db_path

    def validate(self) -> None:
        if not self.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is required in .env file")
        if not self.ADMIN_CHAT_IDS:
            raise ValueError("ADMIN_CHAT_IDS is required in .env file")

settings = Settings()
