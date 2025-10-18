from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Sequence
import json
from urllib.parse import parse_qs, quote_plus, urlparse, urlunparse
from urllib.parse import unquote

from config import settings
from models import Item, TrackedPage


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
                    gallery TEXT NOT NULL DEFAULT '[]',
                    description_table TEXT,
                    description_text TEXT,
                    source_url TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_items_source_url ON items(source_url)"
            )
            self._ensure_gallery_column(connection)
            self._ensure_description_columns(connection)

    @staticmethod
    def _ensure_gallery_column(connection: sqlite3.Connection) -> None:
        columns = connection.execute("PRAGMA table_info(items)").fetchall()
        has_gallery = any(col[1] == "gallery" for col in columns)
        if not has_gallery:
            connection.execute("ALTER TABLE items ADD COLUMN gallery TEXT NOT NULL DEFAULT '[]'")
            connection.execute("UPDATE items SET gallery = '[]' WHERE gallery IS NULL")
            connection.commit()

    @staticmethod
    def _ensure_description_columns(connection: sqlite3.Connection) -> None:
        columns = connection.execute("PRAGMA table_info(items)").fetchall()
        column_names = {col[1] for col in columns}
        
        if "description_table" not in column_names:
            connection.execute("ALTER TABLE items ADD COLUMN description_table TEXT")
            connection.commit()
        
        if "description_text" not in column_names:
            connection.execute("ALTER TABLE items ADD COLUMN description_text TEXT")
            connection.commit()

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

    def get_recent_items(
        self, source_url: str, limit: int | None = None
    ) -> list[tuple[Item, datetime | None]]:
        if limit is not None and limit <= 0:
            return []

        query = (
            """
            SELECT id, url, title, price, img_url, gallery, description_table, description_text, created_at
            FROM items
            WHERE source_url = ?
            ORDER BY id DESC
            """
        )
        parameters: list[object] = [source_url]

        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)

        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()

        recent: list[tuple[Item, datetime | None]] = []
        for row in rows:
            gallery_raw = row[5]
            description_table_raw = row[6]
            description_text = row[7]
            created_at = row[8]
            saved_at: datetime | None
            try:
                saved_at = datetime.fromisoformat(created_at) if created_at else None
            except ValueError:
                saved_at = None
            try:
                gallery_list = json.loads(gallery_raw) if gallery_raw else []
            except json.JSONDecodeError:
                gallery_list = []
            if not gallery_list:
                gallery_list = [row[4]] if row[4] else []
            
            try:
                description_table = json.loads(description_table_raw) if description_table_raw else None
            except json.JSONDecodeError:
                description_table = None
            
            recent.append(
                (
                    Item(
                        url=row[1],
                        title=row[2],
                        price=row[3],
                        img_url=row[4],
                        image_urls=tuple(gallery_list),
                        description_table=description_table,
                        description_text=description_text,
                    ),
                    saved_at,
                )
            )
        return recent

    def save_items(self, items: Iterable[Item], source_url: str) -> None:
        timestamp = datetime.now(UTC).isoformat()
        records = [
            (
                item.url,
                item.title,
                item.price,
                item.img_url,
                json.dumps(list(item.image_urls) or ([item.img_url] if item.img_url else [])),
                json.dumps(item.description_table) if item.description_table else None,
                item.description_text,
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
                INSERT INTO items (url, title, price, img_url, gallery, description_table, description_text, source_url, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    title=excluded.title,
                    price=excluded.price,
                    img_url=excluded.img_url,
                    gallery=excluded.gallery,
                    description_table=excluded.description_table,
                    description_text=excluded.description_text,
                    source_url=excluded.source_url
                """,
                records,
            )
            connection.commit()

    def clear(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM items")
            connection.commit()


ORDER_LABEL_HINTS = {
    "create": "Новые",
    "stop": "Скоро завершатся",
    "cost_asc": "Дешёвые",
    "cost_desc": "Дорогие",
    "rating": "Высокий рейтинг",
}


def _build_label(url: str, existing_labels: set[str]) -> str:
    parsed = urlparse(url)
    path_segment = unquote(parsed.path.rstrip("/").split("/")[-1])
    if not path_segment:
        path_segment = parsed.netloc

    path_segment = path_segment.replace("-", " ").replace("_", " ").strip().title() or "Страница"
    order = parse_qs(parsed.query).get("order", [""])[0]

    if order:
        order_label = ORDER_LABEL_HINTS.get(order, order.replace("_", " ").replace("-", " ").strip().title() or order)
        base_label = f"{path_segment} · {order_label}"
    else:
        base_label = path_segment

    candidate = base_label
    suffix = 2
    while candidate in existing_labels:
        candidate = f"{base_label} ({suffix})"
        suffix += 1
    return candidate


def _apply_order_to_url(url: str, order: str | None) -> str:
    parsed = urlparse(url)
    raw_query = parsed.query

    if not raw_query:
        if not order:
            return url
        assert order is not None
        encoded = quote_plus(order)
        return urlunparse(parsed._replace(query=f"order={encoded}"))

    segments = raw_query.split("&")
    preserved: list[str] = []

    for segment in segments:
        if not segment:
            preserved.append(segment)
            continue

        key, _, _ = segment.partition("=")
        if key == "order":
            continue
        preserved.append(segment)

    if order:
        assert order is not None
        encoded = quote_plus(order)
        preserved.append(f"order={encoded}")

    new_query = "&".join(preserved)
    return urlunparse(parsed._replace(query=new_query))


class TrackedPageRepository:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or settings.DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self._ensure_seed(settings.MONITOR_URLS)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=5, check_same_thread=False)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tracked_pages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tracked_pages_enabled ON tracked_pages(enabled)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS app_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

    def _ensure_seed(self, defaults: Sequence[str]) -> None:
        normalized_defaults = [url.strip() for url in defaults or () if url.strip()]

        with self._connect() as connection:
            seeded_row = connection.execute(
                "SELECT value FROM app_meta WHERE key = ?",
                ("tracked_pages_seeded",),
            ).fetchone()

            if seeded_row:
                return

            existing_count = connection.execute(
                "SELECT COUNT(1) FROM tracked_pages"
            ).fetchone()[0]

            if normalized_defaults and existing_count == 0:
                existing_labels: set[str] = set()
                inserts = []
                for url in normalized_defaults:
                    label = _build_label(url, existing_labels)
                    existing_labels.add(label)
                    timestamp = datetime.now(UTC).isoformat()
                    inserts.append((label, url, 1, timestamp))

                if inserts:
                    connection.executemany(
                        """
                        INSERT INTO tracked_pages (label, url, enabled, created_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        inserts,
                    )

            connection.execute(
                "INSERT OR REPLACE INTO app_meta (key, value) VALUES (?, ?)",
                ("tracked_pages_seeded", datetime.now(UTC).isoformat()),
            )
            connection.commit()

    def list_pages(self) -> list[TrackedPage]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, label, url, enabled FROM tracked_pages ORDER BY created_at ASC, id ASC"
            ).fetchall()

        return [
            TrackedPage(id=row[0], label=row[1], url=row[2], enabled=bool(row[3]))
            for row in rows
        ]

    def get_page(self, page_id: int) -> TrackedPage:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, label, url, enabled FROM tracked_pages WHERE id = ?",
                (page_id,),
            ).fetchone()
        if row is None:
            raise ValueError("Страница с указанным ID не найдена")
        return TrackedPage(id=row[0], label=row[1], url=row[2], enabled=bool(row[3]))

    def get_enabled_urls(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT url FROM tracked_pages WHERE enabled = 1 ORDER BY created_at ASC, id ASC"
            ).fetchall()

        return [row[0] for row in rows]

    def get_enabled_pages(self) -> list[TrackedPage]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, label, url, enabled FROM tracked_pages WHERE enabled = 1 ORDER BY created_at ASC, id ASC"
            ).fetchall()

        return [
            TrackedPage(id=row[0], label=row[1], url=row[2], enabled=bool(row[3]))
            for row in rows
        ]

    def add_page(self, url: str, label: str | None = None) -> TrackedPage:
        normalized_url = url.strip()
        if not normalized_url or not normalized_url.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")

        with self._connect() as connection:
            existing_labels = {
                row[0]
                for row in connection.execute("SELECT label FROM tracked_pages").fetchall()
            }
            final_label = label.strip() if label and label.strip() else _build_label(normalized_url, existing_labels)
            timestamp = datetime.now(UTC).isoformat()
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO tracked_pages (label, url, enabled, created_at)
                    VALUES (?, ?, 1, ?)
                    """,
                    (final_label, normalized_url, timestamp),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError("URL уже добавлен в отслеживание") from exc

        return TrackedPage(id=cursor.lastrowid, label=final_label, url=normalized_url, enabled=True)

    def toggle_page(self, page_id: int) -> TrackedPage:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT label, url, enabled FROM tracked_pages WHERE id = ?",
                (page_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Страница с указанным ID не найдена")

            new_state = 0 if row[2] else 1
            connection.execute(
                "UPDATE tracked_pages SET enabled = ? WHERE id = ?",
                (new_state, page_id),
            )
            connection.commit()

        return TrackedPage(id=page_id, label=row[0], url=row[1], enabled=bool(new_state))

    def remove_page(self, page_id: int) -> TrackedPage:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT label, url, enabled FROM tracked_pages WHERE id = ?",
                (page_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Страница с указанным ID не найдена")

            connection.execute(
                "DELETE FROM tracked_pages WHERE id = ?",
                (page_id,),
            )
            connection.commit()

        return TrackedPage(id=page_id, label=row[0], url=row[1], enabled=bool(row[2]))

    def update_label(self, page_id: int, label: str) -> TrackedPage:
        new_label = label.strip()
        if not new_label:
            raise ValueError("Название не может быть пустым")

        with self._connect() as connection:
            row = connection.execute(
                "SELECT url, enabled FROM tracked_pages WHERE id = ?",
                (page_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Страница с указанным ID не найдена")

            connection.execute(
                "UPDATE tracked_pages SET label = ? WHERE id = ?",
                (new_label, page_id),
            )
            connection.commit()

        return TrackedPage(id=page_id, label=new_label, url=row[0], enabled=bool(row[1]))

    def update_sort(self, page_id: int, order: str | None) -> TrackedPage:
        valid_orders = {"stop", "create", "cost_asc", "cost_desc", "rating"}
        if order == "":
            order = None
        if order is not None and order not in valid_orders:
            raise ValueError("Неизвестный тип сортировки")

        with self._connect() as connection:
            row = connection.execute(
                "SELECT label, url, enabled FROM tracked_pages WHERE id = ?",
                (page_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Страница с указанным ID не найдена")

            new_url = _apply_order_to_url(row[1], order)

            if new_url != row[1]:
                connection.execute(
                    "UPDATE tracked_pages SET url = ? WHERE id = ?",
                    (new_url, page_id),
                )
                connection.commit()
            else:
                new_url = row[1]

        return TrackedPage(id=page_id, label=row[0], url=new_url, enabled=bool(row[2]))


class AppSettingsRepository:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or settings.DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._default_interval = settings.CHECK_INTERVAL_MINUTES
        self._base_admin_ids = tuple(settings.ADMIN_CHAT_IDS)
        self._default_timeout = 60.0
        self._default_retries = 5
        self._default_backoff = 2.0
        self._default_delay = 3.0
        self._initialize()
        self.sync_settings()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=5, check_same_thread=False)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS app_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def _get_meta(self, key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM app_meta WHERE key = ?",
                (key,),
            ).fetchone()
        return row[0] if row else None

    def _set_meta(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO app_meta (key, value) VALUES (?, ?)",
                (key, value),
            )
            connection.commit()

    def _load_extra_admins(self) -> list[int]:
        raw = self._get_meta("admin_chat_ids")
        if not raw:
            return []
        extras: list[int] = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                extras.append(int(part))
            except ValueError:
                continue
        return extras

    def _save_extra_admins(self, admins: list[int]) -> None:
        value = ",".join(str(chat_id) for chat_id in admins)
        self._set_meta("admin_chat_ids", value)

    def get_check_interval(self) -> int:
        raw = self._get_meta("check_interval_minutes")
        if not raw:
            return self._default_interval
        try:
            minutes = int(raw)
        except ValueError:
            return self._default_interval
        return minutes if minutes > 0 else self._default_interval

    def set_check_interval(self, minutes: int) -> int:
        if minutes <= 0:
            raise ValueError("Интервал должен быть положительным")
        if minutes < 3:
            raise ValueError("Минимальный интервал — 3 минуты (чтобы не перегружать сервер)")
        self._set_meta("check_interval_minutes", str(minutes))
        settings.CHECK_INTERVAL_MINUTES = minutes
        return minutes

    def get_admin_ids(self) -> tuple[int, ...]:
        extras = self._load_extra_admins()
        merged: list[int] = []
        for chat_id in [*self._base_admin_ids, *extras]:
            if chat_id not in merged:
                merged.append(chat_id)
        return tuple(merged)

    def add_admin(self, chat_id: int | str) -> tuple[int, ...]:
        try:
            new_id = int(chat_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("ID администратора должен быть целым числом") from exc

        if new_id <= 0:
            raise ValueError("ID администратора должен быть положительным")

        current = set(self.get_admin_ids())
        if new_id in current:
            raise ValueError("Администратор уже добавлен")

        extras = self._load_extra_admins()
        extras.append(new_id)
        self._save_extra_admins(extras)
        updated = self.get_admin_ids()
        settings.ADMIN_CHAT_IDS = updated
        return updated

    def remove_admin(self, chat_id: int | str) -> tuple[int, ...]:
        """Remove administrator from extra admins list."""
        try:
            target_id = int(chat_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("ID администратора должен быть целым числом") from exc

        if target_id <= 0:
            raise ValueError("ID администратора должен быть положительным")

        # Don't allow removing admins from .env
        if target_id in self._base_admin_ids:
            raise ValueError("Нельзя удалить администратора из .env")

        extras = self._load_extra_admins()
        if target_id not in extras:
            raise ValueError("Администратор не найден в дополнительных админах")

        extras.remove(target_id)
        self._save_extra_admins(extras)
        updated = self.get_admin_ids()
        settings.ADMIN_CHAT_IDS = updated
        return updated

    def get_request_timeout(self) -> float:
        """Get HTTP request timeout in seconds."""
        raw = self._get_meta("request_timeout")
        if not raw:
            return self._default_timeout
        try:
            timeout = float(raw)
        except ValueError:
            return self._default_timeout
        return timeout if timeout > 0 else self._default_timeout

    def set_request_timeout(self, timeout: float) -> float:
        """Set HTTP request timeout in seconds."""
        if timeout <= 0:
            raise ValueError("Таймаут должен быть положительным")
        if timeout > 300:
            raise ValueError("Таймаут не должен превышать 300 секунд")
        self._set_meta("request_timeout", str(timeout))
        settings.REQUEST_TIMEOUT = timeout
        return timeout

    def get_request_max_retries(self) -> int:
        """Get max HTTP retry attempts."""
        raw = self._get_meta("request_max_retries")
        if not raw:
            return self._default_retries
        try:
            retries = int(raw)
        except ValueError:
            return self._default_retries
        return retries if retries >= 0 else self._default_retries

    def set_request_max_retries(self, retries: int) -> int:
        """Set max HTTP retry attempts."""
        if retries < 0:
            raise ValueError("Количество попыток не может быть отрицательным")
        if retries > 20:
            raise ValueError("Количество попыток не должно превышать 20")
        self._set_meta("request_max_retries", str(retries))
        settings.REQUEST_MAX_RETRIES = retries
        return retries

    def get_request_backoff_factor(self) -> float:
        """Get HTTP retry backoff factor."""
        raw = self._get_meta("request_backoff_factor")
        if not raw:
            return self._default_backoff
        try:
            backoff = float(raw)
        except ValueError:
            return self._default_backoff
        return backoff if backoff >= 0 else self._default_backoff

    def set_request_backoff_factor(self, backoff: float) -> float:
        """Set HTTP retry backoff factor."""
        if backoff < 0:
            raise ValueError("Backoff фактор не может быть отрицательным")
        if backoff > 10:
            raise ValueError("Backoff фактор не должен превышать 10")
        self._set_meta("request_backoff_factor", str(backoff))
        settings.REQUEST_BACKOFF_FACTOR = backoff
        return backoff

    def get_request_delay_seconds(self) -> float:
        """Get delay between requests to same domain."""
        raw = self._get_meta("request_delay_seconds")
        if not raw:
            return self._default_delay
        try:
            delay = float(raw)
        except ValueError:
            return self._default_delay
        return delay if delay >= 0 else self._default_delay

    def set_request_delay_seconds(self, delay: float) -> float:
        """Set delay between requests to same domain."""
        if delay < 0:
            raise ValueError("Задержка не может быть отрицательной")
        if delay > 60:
            raise ValueError("Задержка не должна превышать 60 секунд")
        self._set_meta("request_delay_seconds", str(delay))
        settings.REQUEST_DELAY_SECONDS = delay
        return delay

    def sync_settings(self) -> None:
        interval = self.get_check_interval()
        settings.CHECK_INTERVAL_MINUTES = interval
        settings.ADMIN_CHAT_IDS = self.get_admin_ids()
        settings.REQUEST_TIMEOUT = self.get_request_timeout()
        settings.REQUEST_MAX_RETRIES = self.get_request_max_retries()
        settings.REQUEST_BACKOFF_FACTOR = self.get_request_backoff_factor()
        settings.REQUEST_DELAY_SECONDS = self.get_request_delay_seconds()
