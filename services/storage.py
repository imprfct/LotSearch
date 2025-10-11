from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from config import settings
from models import Item


class ItemRepository:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or settings.DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    price TEXT NOT NULL,
                    img_url TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_items_source_url ON items(source_url)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=5, check_same_thread=False)

    def get_known_urls(self, source_url: str | None = None) -> set[str]:
        query = "SELECT url FROM items"
        parameters: tuple[str, ...] = ()
        if source_url:
            query += " WHERE source_url = ?"
            parameters = (source_url,)
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return {row[0] for row in rows}

    def save_items(self, items: Iterable[Item], source_url: str) -> None:
        timestamp = datetime.now(UTC).isoformat()
        records = [
            (
                item.url,
                item.title,
                item.price,
                item.img_url,
                source_url,
                timestamp,
            )
            for item in items
        ]
        if not records:
            return
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO items (url, title, price, img_url, source_url, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    title=excluded.title,
                    price=excluded.price,
                    img_url=excluded.img_url,
                    source_url=excluded.source_url
                """,
                records,
            )
            connection.commit()

    def clear(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM items")
            connection.commit()
