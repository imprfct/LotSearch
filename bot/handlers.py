"""Telegram command handlers for the bot."""
from __future__ import annotations

import asyncio
import html
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Dict, Sequence, Tuple
from urllib.parse import parse_qs, urlparse

from aiogram import F, Router
from aiogram.filters import CommandStart, Command
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.filters import IsAdmin
from config import settings
from models import Item, TrackedPage
from services.parser import Parser
from services.runtime import update_monitor_interval
from services.storage import AppSettingsRepository, ItemRepository, TrackedPageRepository

logger = logging.getLogger(__name__)
router = Router()
parser = Parser()
item_repository = ItemRepository()
app_settings = AppSettingsRepository()


@dataclass(slots=True)
class PendingAction:
    action_type: str
    page_id: int | None = None
    prompt_message_id: int | None = None
    prompt_chat_id: int | None = None


_pending_actions: Dict[int, PendingAction] = {}
_user_filters: Dict[int, str] = {}
_menu_message_refs: Dict[int, Tuple[int, int]] = {}
_settings_message_refs: Dict[int, Tuple[int, int]] = {}


@dataclass(slots=True)
class LatestPreview:
    caption: str
    keyboard: InlineKeyboardMarkup
    image_urls: tuple[str, ...]


_latest_gallery_messages: Dict[tuple[int, int], list[int]] = {}
 

@dataclass(slots=True)
class NewsDraft:
    text: str | None = None
    prompt_message_id: int | None = None
    prompt_chat_id: int | None = None
    preview_message_id: int | None = None
    preview_chat_id: int | None = None


_news_drafts: Dict[int, NewsDraft] = {}
MAX_MEDIA_GROUP_SIZE = 10

FILTER_OPTIONS = (
    ("all", "Все"),
    ("active", "Активные"),
    ("paused", "Пауза"),
)

SORT_OPTIONS = (
    ("", "Актуальные"),
    ("create", "Новые"),
    ("stop", "Скоро завершатся"),
    ("cost_asc", "Дешёвые"),
    ("cost_desc", "Дорогие"),
    ("rating", "Высокий рейтинг"),
)

SORT_LABEL_MAP = {key or "": label for key, label in SORT_OPTIONS}


async def _delete_message_safe(bot, chat_id: int | None, message_id: int | None) -> None:
    if chat_id is None or message_id is None:
        return
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass


def _ensure_news_draft(user_id: int) -> NewsDraft:
    draft = _news_drafts.get(user_id)
    if draft is None:
        draft = NewsDraft()
        _news_drafts[user_id] = draft
    return draft


async def _purge_news_draft(bot, user_id: int) -> None:
    draft = _news_drafts.pop(user_id, None)
    if not draft:
        return
    await _delete_message_safe(bot, draft.prompt_chat_id, draft.prompt_message_id)
    await _delete_message_safe(bot, draft.preview_chat_id, draft.preview_message_id)


async def _clear_news_prompt(bot, draft: NewsDraft) -> None:
    await _delete_message_safe(bot, draft.prompt_chat_id, draft.prompt_message_id)
    draft.prompt_chat_id = None
    draft.prompt_message_id = None


async def _clear_news_preview(bot, draft: NewsDraft) -> None:
    await _delete_message_safe(bot, draft.preview_chat_id, draft.preview_message_id)
    draft.preview_chat_id = None
    draft.preview_message_id = None


def _build_news_preview_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✖️ Отмена", callback_data="news:cancel"),
        InlineKeyboardButton(text="✏️ Редактировать", callback_data="news:edit"),
        InlineKeyboardButton(text="✅ Отправить", callback_data="news:send"),
    )
    return builder.as_markup()


def _compose_news_preview_text(content: str) -> str:
    return "📝 <b>Предпросмотр новости</b>\n\n" + content


async def _ask_news_content(bot, user_id: int, chat_id: int, prompt_text: str) -> None:
    draft = _ensure_news_draft(user_id)
    await _clear_news_prompt(bot, draft)
    prompt = await bot.send_message(
        chat_id=chat_id,
        text=prompt_text,
        parse_mode='HTML',
        reply_markup=ForceReply(selective=True),
    )
    draft.prompt_chat_id = prompt.chat.id
    draft.prompt_message_id = prompt.message_id
    _set_pending_action(
        user_id,
        PendingAction(
            action_type="news_collect",
            prompt_message_id=prompt.message_id,
            prompt_chat_id=prompt.chat.id,
        ),
    )


async def _show_news_preview(bot, user_id: int, chat_id: int) -> None:
    draft = _news_drafts.get(user_id)
    if not draft or not draft.text:
        return
    await _clear_news_preview(bot, draft)
    message = await bot.send_message(
        chat_id=chat_id,
        text=_compose_news_preview_text(draft.text),
        parse_mode='HTML',
        reply_markup=_build_news_preview_keyboard(),
        disable_web_page_preview=True,
    )
    draft.preview_chat_id = message.chat.id
    draft.preview_message_id = message.message_id


async def _broadcast_news(bot, chat_ids: Sequence[int], text: str) -> tuple[int, list[int]]:
    delivered = 0
    failed: list[int] = []
    for chat_id in chat_ids:
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode='HTML')
            delivered += 1
        except Exception as exc:
            failed.append(chat_id)
            logger.warning("Failed to send news to %s: %r", chat_id, exc)
    return delivered, failed


def _plural_category(value: int) -> str:
    val = abs(int(value))
    if val % 10 == 1 and val % 100 != 11:
        return "one"
    if 2 <= val % 10 <= 4 and not 12 <= val % 100 <= 14:
        return "few"
    return "many"


def _minute_form(value: int, case: str = "nominative") -> str:
    forms = {
        "nominative": {
            "one": "минута",
            "few": "минуты",
            "many": "минут",
        },
        "accusative": {
            "one": "минуту",
            "few": "минуты",
            "many": "минут",
        },
    }
    case_forms = forms.get(case, forms["nominative"])
    return case_forms[_plural_category(value)]


def _format_minutes(value: int, case: str = "nominative") -> str:
    return f"{value} {_minute_form(value, case)}"


def _format_interval_phrase(value: int) -> str:
    prefix = "каждую" if _plural_category(value) == "one" else "каждые"
    return f"{prefix} {_format_minutes(value, case='accusative')}"


def _format_admin_list(admin_ids: Sequence[int]) -> str:
    if not admin_ids:
        return "— <i>Список пуст</i>"
    base_admins = app_settings._base_admin_ids
    lines = []
    for chat_id in admin_ids:
        is_base = chat_id in base_admins
        suffix = " <i>(из .env)</i>" if is_base else ""
        lines.append(f"• <code>{chat_id}</code>{suffix}")
    return "\n".join(lines)


def _build_settings_overview() -> str:
    interval = settings.CHECK_INTERVAL_MINUTES
    admins = app_settings.get_admin_ids()
    timeout = app_settings.get_request_timeout()
    retries = app_settings.get_request_max_retries()
    backoff = app_settings.get_request_backoff_factor()
    delay = app_settings.get_request_delay_seconds()
    
    return (
        "⚙️ <b>Настройки бота</b>\n\n"
        f"⏱ Интервал проверки: {_format_minutes(interval)} <i>(мин. 3 мин)</i>\n"
        "👥 Администраторы:\n"
        f"{_format_admin_list(admins)}\n\n"
        "<b>🌐 HTTP настройки:</b>\n"
        f"⏳ Таймаут запроса: {timeout:.1f}s <i>(рек. 75s)</i>\n"
        f"🔄 Макс. попыток: {retries} <i>(рек. 6)</i>\n"
        f"📈 Backoff фактор: {backoff:.1f} <i>(рек. 2.5)</i>\n"
        f"⏸ Задержка между запросами: {delay:.1f}s <i>(рек. 4s)</i>\n\n"
        "<b>Доступные команды:</b>\n"
        "/settings interval &lt;минуты&gt; — интервал (мин. 3)\n"
        "/settings timeout &lt;секунды&gt; — таймаут запросов\n"
        "/settings retries &lt;число&gt; — макс. попыток\n"
        "/settings backoff &lt;число&gt; — backoff фактор\n"
        "/settings delay &lt;секунды&gt; — задержка запросов\n"
        "/settings add_admin &lt;chat_id&gt; — добавить админа\n"
        "/settings remove_admin &lt;chat_id&gt; — удалить админа\n\n"
        "💡 <i>Рекомендуемые значения указаны справа</i>"
    )


def _build_settings_keyboard() -> InlineKeyboardMarkup:
    """Build main settings menu with category buttons."""
    builder = InlineKeyboardBuilder()
    
    # Main categories
    builder.row(
        InlineKeyboardButton(text="⏱ Интервал проверки", callback_data="settings:menu:interval"),
    )
    builder.row(
        InlineKeyboardButton(text="🌐 HTTP настройки", callback_data="settings:menu:http"),
    )
    builder.row(
        InlineKeyboardButton(text="👥 Администраторы", callback_data="settings:menu:admins"),
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Обновить", callback_data="settings:refresh"),
        InlineKeyboardButton(text="✖️ Закрыть", callback_data="settings:close"),
    )
    return builder.as_markup()


def _build_interval_keyboard() -> InlineKeyboardMarkup:
    """Build keyboard for interval settings."""
    builder = InlineKeyboardBuilder()
    interval = settings.CHECK_INTERVAL_MINUTES
    
    builder.row(
        InlineKeyboardButton(text="➖ 5 мин", callback_data="settings:interval:-5"),
        InlineKeyboardButton(text="➖ 1 мин", callback_data="settings:interval:-1"),
    )
    builder.row(
        InlineKeyboardButton(text=f"Текущий: {_format_minutes(interval)}", callback_data="settings:noop"),
    )
    builder.row(
        InlineKeyboardButton(text="➕ 1 мин", callback_data="settings:interval:1"),
        InlineKeyboardButton(text="➕ 5 мин", callback_data="settings:interval:5"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="settings:menu:main"),
    )
    return builder.as_markup()


def _build_http_keyboard() -> InlineKeyboardMarkup:
    """Build keyboard for HTTP settings."""
    builder = InlineKeyboardBuilder()
    
    # Submenu for HTTP settings
    builder.row(
        InlineKeyboardButton(text="⏳ Таймаут запроса", callback_data="settings:menu:http:timeout"),
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Макс. попыток", callback_data="settings:menu:http:retries"),
    )
    builder.row(
        InlineKeyboardButton(text="📈 Backoff фактор", callback_data="settings:menu:http:backoff"),
    )
    builder.row(
        InlineKeyboardButton(text="⏸ Задержка запросов", callback_data="settings:menu:http:delay"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="settings:menu:main"),
    )
    return builder.as_markup()


def _build_timeout_keyboard() -> InlineKeyboardMarkup:
    """Build keyboard for timeout setting."""
    builder = InlineKeyboardBuilder()
    timeout = app_settings.get_request_timeout()
    
    builder.row(
        InlineKeyboardButton(text="➖ 10s", callback_data="settings:timeout:-10"),
        InlineKeyboardButton(text="➖ 5s", callback_data="settings:timeout:-5"),
    )
    builder.row(
        InlineKeyboardButton(text=f"Текущий: {timeout:.0f}s", callback_data="settings:noop"),
    )
    builder.row(
        InlineKeyboardButton(text="➕ 5s", callback_data="settings:timeout:5"),
        InlineKeyboardButton(text="➕ 10s", callback_data="settings:timeout:10"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="settings:menu:http"),
    )
    return builder.as_markup()


def _build_retries_keyboard() -> InlineKeyboardMarkup:
    """Build keyboard for retries setting."""
    builder = InlineKeyboardBuilder()
    retries = app_settings.get_request_max_retries()
    
    builder.row(
        InlineKeyboardButton(text="➖ 2", callback_data="settings:retries:-2"),
        InlineKeyboardButton(text="➖ 1", callback_data="settings:retries:-1"),
    )
    builder.row(
        InlineKeyboardButton(text=f"Текущий: {retries}", callback_data="settings:noop"),
    )
    builder.row(
        InlineKeyboardButton(text="➕ 1", callback_data="settings:retries:1"),
        InlineKeyboardButton(text="➕ 2", callback_data="settings:retries:2"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="settings:menu:http"),
    )
    return builder.as_markup()


def _build_backoff_keyboard() -> InlineKeyboardMarkup:
    """Build keyboard for backoff setting."""
    builder = InlineKeyboardBuilder()
    backoff = app_settings.get_request_backoff_factor()
    
    builder.row(
        InlineKeyboardButton(text="➖ 1.0", callback_data="settings:backoff:-1.0"),
        InlineKeyboardButton(text="➖ 0.5", callback_data="settings:backoff:-0.5"),
    )
    builder.row(
        InlineKeyboardButton(text=f"Текущий: {backoff:.1f}", callback_data="settings:noop"),
    )
    builder.row(
        InlineKeyboardButton(text="➕ 0.5", callback_data="settings:backoff:0.5"),
        InlineKeyboardButton(text="➕ 1.0", callback_data="settings:backoff:1.0"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="settings:menu:http"),
    )
    return builder.as_markup()


def _build_delay_keyboard() -> InlineKeyboardMarkup:
    """Build keyboard for delay setting."""
    builder = InlineKeyboardBuilder()
    delay = app_settings.get_request_delay_seconds()
    
    builder.row(
        InlineKeyboardButton(text="➖ 2s", callback_data="settings:delay:-2"),
        InlineKeyboardButton(text="➖ 1s", callback_data="settings:delay:-1"),
    )
    builder.row(
        InlineKeyboardButton(text=f"Текущий: {delay:.0f}s", callback_data="settings:noop"),
    )
    builder.row(
        InlineKeyboardButton(text="➕ 1s", callback_data="settings:delay:1"),
        InlineKeyboardButton(text="➕ 2s", callback_data="settings:delay:2"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="settings:menu:http"),
    )
    return builder.as_markup()


def _build_admins_keyboard() -> InlineKeyboardMarkup:
    """Build keyboard for admin management."""
    builder = InlineKeyboardBuilder()
    admins = app_settings.get_admin_ids()
    base_admins = app_settings._base_admin_ids
    
    # Show admins with remove buttons for extra admins only
    for admin_id in admins:
        is_base = admin_id in base_admins
        if is_base:
            builder.row(
                InlineKeyboardButton(
                    text=f"👤 {admin_id} (из .env)",
                    callback_data="settings:noop"
                )
            )
        else:
            builder.row(
                InlineKeyboardButton(
                    text=f"👤 {admin_id}",
                    callback_data="settings:noop"
                ),
                InlineKeyboardButton(
                    text="❌",
                    callback_data=f"settings:remove_admin:{admin_id}"
                )
            )
    
    builder.row(
        InlineKeyboardButton(text="➕ Добавить", callback_data="settings:add_admin"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="settings:menu:main"),
    )
    return builder.as_markup()


def _register_settings_message(user_id: int, message: Message) -> None:
    _settings_message_refs[user_id] = (message.chat.id, message.message_id)


def _clear_settings_message(user_id: int) -> None:
    _settings_message_refs.pop(user_id, None)


async def _render_settings_menu(bot, user_id: int, chat_id: int | None = None, submenu: str | None = None) -> None:
    """Render settings menu or submenu."""
    if submenu == "interval":
        text = (
            "⏱ <b>Интервал проверки</b>\n\n"
            f"Текущее значение: <b>{_format_minutes(settings.CHECK_INTERVAL_MINUTES)}</b>\n"
            f"Минимум: 3 минуты\n"
            f"Рекомендуется: <i>5 минут</i>\n\n"
            "Используйте кнопки ниже для изменения:"
        )
        keyboard = _build_interval_keyboard()
    elif submenu == "http":
        timeout = app_settings.get_request_timeout()
        retries = app_settings.get_request_max_retries()
        backoff = app_settings.get_request_backoff_factor()
        delay = app_settings.get_request_delay_seconds()
        text = (
            "🌐 <b>HTTP настройки</b>\n\n"
            f"⏳ Таймаут: <b>{timeout:.0f}s</b> <i>(рек. 75s)</i>\n"
            f"🔄 Попытки: <b>{retries}</b> <i>(рек. 6)</i>\n"
            f"📈 Backoff: <b>{backoff:.1f}</b> <i>(рек. 2.5)</i>\n"
            f"⏸ Задержка: <b>{delay:.0f}s</b> <i>(рек. 4s)</i>\n\n"
            "Выберите параметр для настройки:"
        )
        keyboard = _build_http_keyboard()
    elif submenu == "http:timeout":
        timeout = app_settings.get_request_timeout()
        text = (
            "⏳ <b>Таймаут запроса</b>\n\n"
            f"Текущее значение: <b>{timeout:.0f}s</b>\n"
            f"Диапазон: 1-300 секунд\n"
            f"Рекомендуется: <i>75s</i>\n\n"
            "Время ожидания ответа от сервера.\n"
            "Большее значение = надёжнее, но медленнее."
        )
        keyboard = _build_timeout_keyboard()
    elif submenu == "http:retries":
        retries = app_settings.get_request_max_retries()
        text = (
            "🔄 <b>Максимум попыток</b>\n\n"
            f"Текущее значение: <b>{retries}</b>\n"
            f"Диапазон: 0-20\n"
            f"Рекомендуется: <i>6</i>\n\n"
            "Количество повторных попыток при ошибке.\n"
            "Больше попыток = надёжнее."
        )
        keyboard = _build_retries_keyboard()
    elif submenu == "http:backoff":
        backoff = app_settings.get_request_backoff_factor()
        text = (
            "📈 <b>Backoff фактор</b>\n\n"
            f"Текущее значение: <b>{backoff:.1f}</b>\n"
            f"Диапазон: 0-10\n"
            f"Рекомендуется: <i>2.5</i>\n\n"
            "Множитель задержки между попытками.\n"
            "При 2.5: попытки через 2.5s, 6.25s, 15.6s, 39s..."
        )
        keyboard = _build_backoff_keyboard()
    elif submenu == "http:delay":
        delay = app_settings.get_request_delay_seconds()
        text = (
            "⏸ <b>Задержка между запросами</b>\n\n"
            f"Текущее значение: <b>{delay:.0f}s</b>\n"
            f"Диапазон: 0-60 секунд\n"
            f"Рекомендуется: <i>4s</i>\n\n"
            "Пауза между запросами к одному домену.\n"
            "Больше задержка = меньше нагрузка на сервер."
        )
        keyboard = _build_delay_keyboard()
    elif submenu == "admins":
        admins = app_settings.get_admin_ids()
        text = (
            "👥 <b>Администраторы</b>\n\n"
            f"Текущие администраторы:\n"
            f"{_format_admin_list(admins)}\n\n"
            "Администраторы могут управлять ботом."
        )
        keyboard = _build_admins_keyboard()
    else:
        text = _build_settings_overview()
        keyboard = _build_settings_keyboard()

    ref = _settings_message_refs.get(user_id)
    if ref:
        chat_id_ref, message_id = ref
        try:
            await bot.edit_message_text(
                chat_id=chat_id_ref,
                message_id=message_id,
                text=text,
                parse_mode='HTML',
                reply_markup=keyboard,
            )
            return
        except TelegramBadRequest as exc:
            lowered = str(exc).lower()
            if "message is not modified" in lowered:
                return
            if "message to edit not found" not in lowered:
                raise
        except Exception:
            pass

    target_chat = chat_id if chat_id is not None else (ref[0] if ref else user_id)
    sent = await bot.send_message(
        chat_id=target_chat,
        text=text,
        parse_mode='HTML',
        reply_markup=keyboard,
    )
    _register_settings_message(user_id, sent)


def _get_filter(user_id: int | None) -> str:
    if not user_id:
        return "all"
    return _user_filters.get(user_id, "all")


def _set_filter(user_id: int, mode: str) -> str:
    valid_modes = {key for key, _ in FILTER_OPTIONS}
    target = mode if mode in valid_modes else "all"
    _user_filters[user_id] = target
    return target


def _order_label(order: str | None) -> str:
    return SORT_LABEL_MAP.get(order or "", "Актуальные")


def _extract_order_from_url(url: str) -> str | None:
    params = parse_qs(urlparse(url).query)
    values = params.get("order")
    if not values:
        return None
    return values[0] or None


def _build_sort_keyboard(page_id: int, current_order: str | None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for key, label in SORT_OPTIONS:
        is_current = (key or None) == (current_order or None)
        prefix = "🔘" if is_current else "⚪"
        token = key if key else "none"
        builder.row(
            InlineKeyboardButton(
                text=f"{prefix} {label}",
                callback_data=f"tracking:setorder:{page_id}:{token}"
            )
        )

    builder.row(
        InlineKeyboardButton(text="↩️ Назад", callback_data="tracking:refresh"),
        InlineKeyboardButton(text="✖️ Отмена", callback_data="tracking:cancel"),
    )

    return builder.as_markup()


def _register_menu_message(user_id: int, message: Message) -> None:
    _menu_message_refs[user_id] = (message.chat.id, message.message_id)


async def _delete_previous_menu(bot, user_id: int) -> None:
    ref = _menu_message_refs.get(user_id)
    if not ref:
        return
    chat_id, message_id = ref
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass


def _set_pending_action(user_id: int, action: PendingAction) -> None:
    _pending_actions[user_id] = action


def _clear_pending_action(user_id: int) -> None:
    _pending_actions.pop(user_id, None)


async def _cancel_pending_action(bot, user_id: int) -> None:
    pending = _pending_actions.get(user_id)
    if not pending:
        return
    if pending.prompt_chat_id is not None and pending.prompt_message_id is not None:
        try:
            await bot.delete_message(pending.prompt_chat_id, pending.prompt_message_id)
        except Exception:
            pass
    _clear_pending_action(user_id)


async def _refresh_menu_message(
    message: Message,
    repository: TrackedPageRepository,
    user_id: int,
    notice: str | None = None,
) -> None:
    pages = repository.list_pages()
    filter_mode = _get_filter(user_id)
    overview_text, keyboard = _compose_tracking_overview(pages, filter_mode, notice=notice)
    try:
        await message.edit_text(
            overview_text,
            parse_mode='HTML',
            reply_markup=keyboard,
        )
        _register_menu_message(user_id, message)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        raise


async def _render_menu_for_user(
    bot,
    user_id: int,
    repository: TrackedPageRepository,
    notice: str | None = None,
) -> None:
    pages = repository.list_pages()
    filter_mode = _get_filter(user_id)
    overview_text, keyboard = _compose_tracking_overview(pages, filter_mode, notice=notice)

    ref = _menu_message_refs.get(user_id)
    chat_id: int
    message_id: int

    if ref:
        chat_id, message_id = ref
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=overview_text,
                parse_mode='HTML',
                reply_markup=keyboard,
            )
            _menu_message_refs[user_id] = (chat_id, message_id)
            return
        except Exception:
            pass

    chat_id = ref[0] if ref else user_id
    sent = await bot.send_message(
        chat_id=chat_id,
        text=overview_text,
        parse_mode='HTML',
        reply_markup=keyboard,
    )
    _register_menu_message(user_id, sent)


def _extract_user_id(message: Message) -> int | None:
    user = message.from_user
    return user.id if user else None


def _short_label(label: str, limit: int = 40) -> str:
    if len(label) <= limit:
        return label
    return f"{label[:limit - 1]}…"


def _apply_filter(pages: Sequence[TrackedPage], filter_mode: str) -> list[TrackedPage]:
    if filter_mode == "active":
        return [page for page in pages if page.enabled]
    if filter_mode == "paused":
        return [page for page in pages if not page.enabled]
    return list(pages)


def _build_tracking_keyboard(
    pages: Sequence[TrackedPage],
    filter_mode: str,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    filter_buttons = [
        InlineKeyboardButton(
            text=("🔘 " if mode == filter_mode else "⚪ ") + label,
            callback_data=f"tracking:filter:{mode}",
        )
        for mode, label in FILTER_OPTIONS
    ]
    builder.row(*filter_buttons)

    for page in pages:
        current_order = _extract_order_from_url(page.url)
        toggle_text = f"{'✅' if page.enabled else '🚫'} {_short_label(page.label)}"
        builder.row(
            InlineKeyboardButton(
                text=toggle_text,
                callback_data=f"tracking:toggle:{page.id}"
            ),
            InlineKeyboardButton(
                text="✏️ Название",
                callback_data=f"tracking:rename:{page.id}"
            ),
            InlineKeyboardButton(
                text="🗑 Удалить",
                callback_data=f"tracking:remove:{page.id}"
            ),
        )
        builder.row(
            InlineKeyboardButton(
                text=f"⚙️ Сортировка: {_order_label(current_order)}",
                callback_data=f"tracking:sort:{page.id}"
            ),
            InlineKeyboardButton(
                text="📰 Лоты",
                callback_data=f"tracking:latest:{page.id}"
            ),
        )

    builder.row(
        InlineKeyboardButton(text="➕ Добавить", callback_data="tracking:add"),
        InlineKeyboardButton(text="🔄 Обновить", callback_data="tracking:refresh"),
    )

    return builder.as_markup()


def _build_latest_keyboard(page_id: int, index: int, total: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    def nav_button(label: str, target: int, enabled: bool) -> InlineKeyboardButton:
        callback_data = f"tracking:latestnav:{page_id}:{target}" if enabled else "tracking:noop"
        return InlineKeyboardButton(text=label, callback_data=callback_data)

    builder.row(
        nav_button("⏮", 0, index > 0),
        nav_button("◀️", max(index - 1, 0), index > 0),
        nav_button("▶️", min(index + 1, total - 1), index < total - 1),
        nav_button("⏭", max(total - 1, 0), index < total - 1),
    )

    builder.row(
        InlineKeyboardButton(text="✖️ Закрыть", callback_data="tracking:latestclose"),
    )

    return builder.as_markup()


async def _send_gallery(
    bot,
    chat_id: int,
    image_urls: Sequence[str],
    caption: str | None,
) -> list[int]:
    media_ids: list[int] = []
    urls = list(image_urls)[:MAX_MEDIA_GROUP_SIZE]
    if not urls:
        return media_ids

    if len(urls) == 1:
        kwargs = {"chat_id": chat_id, "photo": urls[0]}
        if caption:
            kwargs.update({"caption": caption, "parse_mode": 'HTML'})
        msg = await bot.send_photo(**kwargs)
        media_ids.append(msg.message_id)
        return media_ids

    media_group = []
    for index, url in enumerate(urls):
        if index == 0 and caption:
            media_group.append(InputMediaPhoto(media=url, caption=caption, parse_mode='HTML'))
        else:
            media_group.append(InputMediaPhoto(media=url))
    messages = await bot.send_media_group(chat_id=chat_id, media=media_group)
    media_ids.extend(message.message_id for message in messages)
    return media_ids


def _note_for_gallery(count: int) -> str:
    if count <= 0:
        return ""
    if count == 1:
        return "\n\n🖼 Фото отправлено выше."
    return f"\n\n📸 Галерея из {count} фото отправлена выше."


async def _clear_gallery(bot, chat_id: int, anchor_message_id: int) -> None:
    key = (chat_id, anchor_message_id)
    message_ids = _latest_gallery_messages.pop(key, [])
    for mid in message_ids:
        try:
            await bot.delete_message(chat_id, mid)
        except Exception:
            pass


async def _send_latest_preview_message(bot, chat_id: int, preview: LatestPreview):
    gallery_ids = await _send_gallery(bot, chat_id, preview.image_urls, caption=None)
    note = _note_for_gallery(len(preview.image_urls))
    message = await bot.send_message(
        chat_id=chat_id,
        text=f"{preview.caption}{note}",
        parse_mode='HTML',
        reply_markup=preview.keyboard,
        disable_web_page_preview=True,
    )
    if gallery_ids:
        _latest_gallery_messages[(message.chat.id, message.message_id)] = gallery_ids
    return message


async def _update_latest_preview_message(bot, message: Message, preview: LatestPreview):
    await _clear_gallery(bot, message.chat.id, message.message_id)
    try:
        await message.delete()
    except Exception:
        pass
    return await _send_latest_preview_message(bot, message.chat.id, preview)


def _compose_latest_preview(
    page: TrackedPage,
    items: Sequence[tuple[Item, datetime | None]],
    index: int,
) -> LatestPreview:
    total = len(items)
    if total == 0:
        raise ValueError("Нет доступных лотов")

    if page.id is None:
        raise ValueError("Страница должна иметь идентификатор")

    index = max(0, min(index, total - 1))
    item, saved_at = items[index]

    parts: list[str] = [
        f"📰 <b>{html.escape(page.label)}</b>",
        f"<i>Лот {index + 1} из {total}</i>",
        "",
        f"<b>{html.escape(item.title)}</b>",
    ]

    if item.price:
        parts.append(f"💰 {html.escape(item.price)}")

    if saved_at is not None:
        saved_display = saved_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
        parts.append(f"🗓 {saved_display}")

    parts.append(f"🔗 <a href=\"{html.escape(item.url)}\">Открыть лот</a>")

    text = "\n".join(parts)
    keyboard = _build_latest_keyboard(page.id, index, total)
    images = item.image_urls if getattr(item, "image_urls", None) else (() if not item.img_url else (item.img_url,))
    return LatestPreview(caption=text, keyboard=keyboard, image_urls=images)


def _compose_tracking_overview(
    pages: Sequence[TrackedPage],
    filter_mode: str,
    notice: str | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    total = len(pages)
    enabled_total = sum(1 for page in pages if page.enabled)

    filtered_pages = _apply_filter(pages, filter_mode)
    shown_total = len(filtered_pages)

    parts: list[str] = ["📋 <b>Отслеживаемые страницы</b>"]

    if notice:
        parts.append(f"\n<i>{notice}</i>")

    parts.append(
        "\n\n"
        f"Всего: <b>{total}</b>\n"
        f"Активных: <b>{enabled_total}</b>\n"
    )

    if filter_mode != "all":
        label_map = dict(FILTER_OPTIONS)
        parts.append(f"Отображается: <b>{label_map.get(filter_mode, 'Все')}</b> ({shown_total})\n")
    elif total != shown_total:
        parts.append(f"Отображается: <b>{shown_total}</b>\n")

    if not filtered_pages:
        parts.append(
            "\nПока ничего не отслеживается. Нажмите кнопку «➕ Добавить» ниже, чтобы выбрать новую страницу."
        )
    else:
        for page in filtered_pages:
            status = "✅ Активна" if page.enabled else "⏸ Приостановлена"
            escaped_label = html.escape(page.label)
            escaped_url = html.escape(page.url)
            parts.append(
                "\n"
                f"<b>{page.id}.</b> {status}\n"
                f"<a href=\"{escaped_url}\">{escaped_label}</a>\n"
                f"<code>{escaped_url}</code>"
            )

    parts.append(
        "\n\nУправляйте кнопками ниже: включайте/выключайте, меняйте сортировку, переименовывайте, удаляйте или добавляйте новые ссылки."
    )

    return "".join(parts), _build_tracking_keyboard(filtered_pages, filter_mode)


def _parse_add_payload(payload: str) -> tuple[str, str | None]:
    if not payload:
        raise ValueError("Укажите URL для добавления")

    url_part, label_part = (payload.split("|", 1) + [""])[:2]
    url = url_part.strip()
    label = label_part.strip() or None

    if not url:
        raise ValueError("Укажите корректный URL")

    return url, label


def _parse_rename_payload(payload: str) -> tuple[int, str]:
    parts = payload.split(maxsplit=1)
    if len(parts) < 2:
        raise ValueError("Использование: /tracking rename ID НовоеНазвание")

    page_id = _parse_id(parts[0])
    new_label = parts[1].strip()
    if not new_label:
        raise ValueError("Новое название не может быть пустым")
    return page_id, new_label


def _parse_id(payload: str) -> int:
    try:
        return int(payload.strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("Укажите числовой ID") from exc


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """
    Handler for /start command
    
    Args:
        message: Incoming message
    """
    user_id = _extract_user_id(message)
    logger.info("User %s started the bot", user_id)

    is_admin = user_id in settings.ADMIN_CHAT_IDS if user_id else False

    if is_admin:
        await message.answer(
            "✅ <b>Бот активирован!</b>\n\n"
            "Теперь бот начнёт мониторить лоты и отправлять уведомления о новых поступлениях.\n\n"
            "📋 Доступные команды:\n"
            "/start - Запустить бота\n"
            "/status - Статус мониторинга\n"
            "/tracking - Управление отслеживаемыми страницами\n"
            "/settings - Настройки бота\n"
            "/help - Помощь",
            parse_mode='HTML'
        )
    else:
        await message.answer(
            "👋 Привет! Этот бот предназначен только для администраторов.",
            parse_mode='HTML'
        )


@router.message(Command("tracking"), IsAdmin())
async def cmd_tracking(message: Message) -> None:
    """Display and manage tracked pages configuration."""

    repository = TrackedPageRepository()
    text = message.text or ""
    parts = text.split(maxsplit=2)
    notice: str | None = None

    user_id = _extract_user_id(message)
    if not user_id:
        await message.answer("Не удалось определить пользователя", parse_mode='HTML')
        return

    bot = message.bot
    if bot is None:
        await message.answer("Бот недоступен", parse_mode='HTML')
        return

    await _cancel_pending_action(bot, user_id)

    if len(parts) > 1:
        action = parts[1].lower()
        payload = parts[2] if len(parts) > 2 else ""

        try:
            if action == "add":
                url, label = _parse_add_payload(payload)
                page = repository.add_page(url, label)
                notice = (
                    f"Добавлена новая страница: <b>{html.escape(page.label)}</b>"
                )
            elif action in {"rename", "label"}:
                page_id, new_label = _parse_rename_payload(payload)
                page = repository.update_label(page_id, new_label)
                notice = f"Название обновлено: <b>{html.escape(page.label)}</b>"
            elif action in {"toggle", "switch"}:
                page_id = _parse_id(payload)
                page = repository.toggle_page(page_id)
                state_text = "активирована" if page.enabled else "отключена"
                notice = (
                    f"Страница <b>{html.escape(page.label)}</b> {state_text}."
                )
            elif action in {"remove", "delete"}:
                page_id = _parse_id(payload)
                removed = repository.remove_page(page_id)
                notice = f"Удалена <b>{html.escape(removed.label)}</b>."
            else:
                raise ValueError(
                    "Неизвестное действие. Доступно: add, rename, toggle, remove"
                )
        except ValueError as exc:
            await message.answer(
                f"❌ <b>Ошибка:</b> {html.escape(str(exc))}",
                parse_mode='HTML'
            )
            return

    await _delete_previous_menu(bot, user_id)

    pages = repository.list_pages()
    filter_mode = _get_filter(user_id)
    overview_text, keyboard = _compose_tracking_overview(pages, filter_mode, notice=notice)
    sent = await message.answer(overview_text, parse_mode='HTML', reply_markup=keyboard)
    _register_menu_message(user_id, sent)


@router.message(Command("status"), IsAdmin())
async def cmd_status(message: Message) -> None:
    """
    Handler for /status command (admin only)
    
    Args:
        message: Incoming message
    """
    user_id = _extract_user_id(message)
    logger.info("Admin %s requested status", user_id)

    repository = TrackedPageRepository()
    pages = repository.list_pages()
    active_count = sum(1 for page in pages if page.enabled)

    interval = settings.CHECK_INTERVAL_MINUTES

    status_text = (
        "📊 <b>Статус мониторинга</b>\n\n"
        f"⏱ Интервал проверки: {_format_minutes(interval)}\n"
        f"🔗 Всего страниц: {len(pages)} (активных: {active_count})\n"
        f"👥 Количество админов: {len(settings.ADMIN_CHAT_IDS)}\n\n"
        "<b>Отслеживаемые URL:</b>\n"
    )

    if not pages:
        status_text += "— Пока ничего не настроено. Откройте /tracking и нажмите «➕ Добавить».\n"
    else:
        for page in pages:
            icon = "✅" if page.enabled else "⏸"
            status_text += (
                f"{page.id}. {icon} {page.label}\n"
                f"    {page.url}\n"
            )

    await message.answer(status_text, parse_mode='HTML')


@router.message(Command("help"), IsAdmin())
async def cmd_help(message: Message) -> None:
    """
    Handler for /help command (admin only)
    
    Args:
        message: Incoming message
    """
    user_id = _extract_user_id(message)
    logger.info("Admin %s requested help", user_id)

    help_text = (
        "📖 <b>Помощь по боту</b>\n\n"
        "Этот бот автоматически мониторит указанные URL и отправляет уведомления "
        "о новым лотам всем администраторам.\n\n"
        "<b>Доступные команды:</b>\n"
        "/start - Запустить бота и увидеть приветствие\n"
        "/status - Посмотреть текущий статус мониторинга\n"
        "/tracking - Управлять списком отслеживаемых страниц\n"
        "/settings - Настроить проверки и админов\n"
        "/help - Показать эту справку\n\n"
        "💡 Бот работает автоматически в фоновом режиме и проверяет новые лоты "
        f"{_format_interval_phrase(settings.CHECK_INTERVAL_MINUTES)}."
    )
    
    await message.answer(help_text, parse_mode='HTML')


@router.message(Command("news"), IsAdmin())
async def cmd_news(message: Message) -> None:
    user_id = _extract_user_id(message)
    if user_id is None:
        return

    bot = message.bot
    if bot is None:
        return

    await _cancel_pending_action(bot, user_id)
    await _purge_news_draft(bot, user_id)

    await _ask_news_content(
        bot,
        user_id,
        message.chat.id,
        "Введите текст новости, он будет отправлен всем администраторам.",
    )


@router.message(Command("settings"), IsAdmin())
async def cmd_settings(message: Message) -> None:
    """Handle /settings command for administrators."""

    user_id = _extract_user_id(message)
    if user_id is None:
        return
    logger.info("Admin %s requested settings", user_id)

    bot = message.bot
    if bot is None:
        return

    text = (message.text or "").strip()
    parts = text.split(maxsplit=2)

    if len(parts) == 1:
        await _render_settings_menu(bot, user_id, chat_id=message.chat.id)
        return

    action = parts[1].lower()
    payload = parts[2] if len(parts) > 2 else ""

    if action in {"interval", "интервал"}:
        value = payload.strip()
        if not value:
            await message.answer(
                "❌ <b>Ошибка:</b> укажите количество минут. Пример: <code>/settings interval 5</code>",
                parse_mode='HTML',
            )
            return

        try:
            minutes = int(value)
        except ValueError:
            await message.answer(
                "❌ <b>Ошибка:</b> интервал должен быть целым числом.",
                parse_mode='HTML',
            )
            return

        try:
            new_value = app_settings.set_check_interval(minutes)
        except ValueError as exc:
            await message.answer(
                f"❌ <b>Ошибка:</b> {html.escape(str(exc))}",
                parse_mode='HTML',
            )
            return

        update_monitor_interval(new_value)
        await message.answer(
            "⏱ <b>Интервал обновлён</b>\n"
            f"Проверки выполняются {_format_interval_phrase(new_value)}.",
            parse_mode='HTML',
        )
        await _render_settings_menu(bot, user_id, chat_id=message.chat.id)
        return

    if action in {"add_admin", "add", "admin"}:
        value = payload.strip()
        if not value:
            await message.answer(
                "❌ <b>Ошибка:</b> укажите ID пользователя. Пример: <code>/settings add_admin 123456789</code>",
                parse_mode='HTML',
            )
            return

        try:
            updated_admins = app_settings.add_admin(value)
        except ValueError as exc:
            await message.answer(
                f"❌ <b>Ошибка:</b> {html.escape(str(exc))}",
                parse_mode='HTML',
            )
            return

        await message.answer(
            "👥 <b>Администратор добавлен</b>\n"
            f"Теперь администраторов: {len(updated_admins)}.",
            parse_mode='HTML',
        )
        await _render_settings_menu(bot, user_id, chat_id=message.chat.id)
        return

    if action in {"timeout", "таймаут"}:
        value = payload.strip()
        if not value:
            await message.answer(
                "❌ <b>Ошибка:</b> укажите таймаут в секундах. Пример: <code>/settings timeout 60</code>",
                parse_mode='HTML',
            )
            return

        try:
            timeout = float(value)
            new_value = app_settings.set_request_timeout(timeout)
            await message.answer(
                f"⏳ <b>Таймаут обновлён:</b> {new_value:.1f}s",
                parse_mode='HTML',
            )
            await _render_settings_menu(bot, user_id, chat_id=message.chat.id)
        except ValueError as exc:
            await message.answer(
                f"❌ <b>Ошибка:</b> {html.escape(str(exc))}",
                parse_mode='HTML',
            )
        return

    if action in {"retries", "попытки"}:
        value = payload.strip()
        if not value:
            await message.answer(
                "❌ <b>Ошибка:</b> укажите количество попыток. Пример: <code>/settings retries 5</code>",
                parse_mode='HTML',
            )
            return

        try:
            retries = int(value)
            new_value = app_settings.set_request_max_retries(retries)
            await message.answer(
                f"🔄 <b>Макс. попыток обновлено:</b> {new_value}",
                parse_mode='HTML',
            )
            await _render_settings_menu(bot, user_id, chat_id=message.chat.id)
        except ValueError as exc:
            await message.answer(
                f"❌ <b>Ошибка:</b> {html.escape(str(exc))}",
                parse_mode='HTML',
            )
        return

    if action in {"backoff", "бекофф"}:
        value = payload.strip()
        if not value:
            await message.answer(
                "❌ <b>Ошибка:</b> укажите backoff фактор. Пример: <code>/settings backoff 2.0</code>",
                parse_mode='HTML',
            )
            return

        try:
            backoff = float(value)
            new_value = app_settings.set_request_backoff_factor(backoff)
            await message.answer(
                f"📈 <b>Backoff фактор обновлён:</b> {new_value:.1f}",
                parse_mode='HTML',
            )
            await _render_settings_menu(bot, user_id, chat_id=message.chat.id)
        except ValueError as exc:
            await message.answer(
                f"❌ <b>Ошибка:</b> {html.escape(str(exc))}",
                parse_mode='HTML',
            )
        return

    if action in {"delay", "задержка"}:
        value = payload.strip()
        if not value:
            await message.answer(
                "❌ <b>Ошибка:</b> укажите задержку в секундах. Пример: <code>/settings delay 3</code>",
                parse_mode='HTML',
            )
            return

        try:
            delay = float(value)
            new_value = app_settings.set_request_delay_seconds(delay)
            await message.answer(
                f"⏸ <b>Задержка запросов обновлена:</b> {new_value:.1f}s",
                parse_mode='HTML',
            )
            await _render_settings_menu(bot, user_id, chat_id=message.chat.id)
        except ValueError as exc:
            await message.answer(
                f"❌ <b>Ошибка:</b> {html.escape(str(exc))}",
                parse_mode='HTML',
            )
        return

    if action in {"remove_admin", "remove", "del_admin"}:
        value = payload.strip()
        if not value:
            await message.answer(
                "❌ <b>Ошибка:</b> укажите ID администратора для удаления. Пример: <code>/settings remove_admin 123456789</code>",
                parse_mode='HTML',
            )
            return

        try:
            updated_admins = app_settings.remove_admin(value)
            await message.answer(
                f"👥 <b>Администратор удалён</b>\n"
                f"Теперь администраторов: {len(updated_admins)}.",
                parse_mode='HTML',
            )
            await _render_settings_menu(bot, user_id, chat_id=message.chat.id)
        except ValueError as exc:
            await message.answer(
                f"❌ <b>Ошибка:</b> {html.escape(str(exc))}",
                parse_mode='HTML',
            )
        return

    await message.answer(
        (
            "❌ <b>Неизвестное действие.</b>\n"
            "Используйте: <code>/settings</code>, <code>/settings interval &lt;минуты&gt;</code>, "
            "<code>/settings timeout &lt;секунды&gt;</code>, <code>/settings retries &lt;число&gt;</code>, "
            "<code>/settings backoff &lt;число&gt;</code>, <code>/settings delay &lt;секунды&gt;</code>, "
            "<code>/settings add_admin &lt;chat_id&gt;</code>, "
            "<code>/settings remove_admin &lt;chat_id&gt;</code>"
        ),
        parse_mode='HTML',
    )


@router.callback_query(IsAdmin(), F.data.startswith("settings:"))
async def settings_callback(call: CallbackQuery) -> None:
    user_id = call.from_user.id if call.from_user else None
    if user_id is None:
        await call.answer("Пользователь неизвестен", show_alert=True)
        return

    message = call.message
    if message is None:
        await call.answer("Сообщение недоступно", show_alert=True)
        return

    bot = message.bot
    if bot is None:
        await call.answer()
        return

    data = call.data or ""
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    payload = parts[2] if len(parts) > 2 else ""
    extra = parts[3] if len(parts) > 3 else ""

    try:
        # Navigation handlers
        if action == "menu":
            if payload == "main":
                await _render_settings_menu(bot, user_id, chat_id=message.chat.id)
            elif payload == "interval":
                await _render_settings_menu(bot, user_id, chat_id=message.chat.id, submenu="interval")
            elif payload == "http":
                if not extra:
                    await _render_settings_menu(bot, user_id, chat_id=message.chat.id, submenu="http")
                elif extra == "timeout":
                    await _render_settings_menu(bot, user_id, chat_id=message.chat.id, submenu="http:timeout")
                elif extra == "retries":
                    await _render_settings_menu(bot, user_id, chat_id=message.chat.id, submenu="http:retries")
                elif extra == "backoff":
                    await _render_settings_menu(bot, user_id, chat_id=message.chat.id, submenu="http:backoff")
                elif extra == "delay":
                    await _render_settings_menu(bot, user_id, chat_id=message.chat.id, submenu="http:delay")
            elif payload == "admins":
                await _render_settings_menu(bot, user_id, chat_id=message.chat.id, submenu="admins")
            await call.answer()
            return

        if action == "noop":
            await call.answer()
            return

        if action == "interval":
            try:
                delta = int(payload)
            except ValueError:
                await call.answer("Некорректное значение", show_alert=True)
                return
            current = settings.CHECK_INTERVAL_MINUTES
            new_value = current + delta
            if new_value < 3:
                await call.answer("Минимальный интервал — 3 минуты", show_alert=True)
                return
            try:
                app_settings.set_check_interval(new_value)
                update_monitor_interval(new_value)
                await _render_settings_menu(bot, user_id, chat_id=message.chat.id, submenu="interval")
                await call.answer(f"✅ {_format_minutes(new_value)}")
            except ValueError as e:
                await call.answer(str(e), show_alert=True)
            return

        if action == "timeout":
            try:
                delta = float(payload)
            except ValueError:
                await call.answer("Некорректное значение", show_alert=True)
                return
            current = app_settings.get_request_timeout()
            new_value = current + delta
            if new_value <= 0:
                await call.answer("Минимальный таймаут — 1 секунда", show_alert=True)
                return
            try:
                app_settings.set_request_timeout(new_value)
                await _render_settings_menu(bot, user_id, chat_id=message.chat.id, submenu="http:timeout")
                await call.answer(f"✅ {new_value:.0f}s")
            except ValueError as e:
                await call.answer(str(e), show_alert=True)
            return

        if action == "retries":
            try:
                delta = int(payload)
            except ValueError:
                await call.answer("Некорректное значение", show_alert=True)
                return
            current = app_settings.get_request_max_retries()
            new_value = current + delta
            if new_value < 0:
                await call.answer("Минимум попыток — 0", show_alert=True)
                return
            try:
                app_settings.set_request_max_retries(new_value)
                await _render_settings_menu(bot, user_id, chat_id=message.chat.id, submenu="http:retries")
                await call.answer(f"✅ {new_value}")
            except ValueError as e:
                await call.answer(str(e), show_alert=True)
            return

        if action == "backoff":
            try:
                delta = float(payload)
            except ValueError:
                await call.answer("Некорректное значение", show_alert=True)
                return
            current = app_settings.get_request_backoff_factor()
            new_value = current + delta
            if new_value < 0:
                await call.answer("Минимальный backoff — 0", show_alert=True)
                return
            try:
                app_settings.set_request_backoff_factor(new_value)
                await _render_settings_menu(bot, user_id, chat_id=message.chat.id, submenu="http:backoff")
                await call.answer(f"✅ {new_value:.1f}")
            except ValueError as e:
                await call.answer(str(e), show_alert=True)
            return

        if action == "delay":
            try:
                delta = float(payload)
            except ValueError:
                await call.answer("Некорректное значение", show_alert=True)
                return
            current = app_settings.get_request_delay_seconds()
            new_value = current + delta
            if new_value < 0:
                await call.answer("Минимальная задержка — 0 секунд", show_alert=True)
                return
            try:
                app_settings.set_request_delay_seconds(new_value)
                await _render_settings_menu(bot, user_id, chat_id=message.chat.id, submenu="http:delay")
                await call.answer(f"✅ {new_value:.0f}s")
            except ValueError as e:
                await call.answer(str(e), show_alert=True)
            return

        if action == "add_admin":
            await _cancel_pending_action(bot, user_id)
            prompt = await message.answer(
                "Введите ID администратора, которого нужно добавить:",
                parse_mode='HTML',
                reply_markup=ForceReply(selective=True),
            )
            _set_pending_action(
                user_id,
                PendingAction(
                    action_type="settings_add_admin",
                    prompt_message_id=prompt.message_id,
                    prompt_chat_id=prompt.chat.id,
                ),
            )
            await call.answer("Жду ID администратора")
            return

        if action == "remove_admin":
            try:
                admin_id = int(payload)
            except ValueError:
                await call.answer("Некорректный ID", show_alert=True)
                return
            try:
                app_settings.remove_admin(admin_id)
                await _render_settings_menu(bot, user_id, chat_id=message.chat.id, submenu="admins")
                await call.answer(f"✅ Удален {admin_id}")
            except ValueError as e:
                await call.answer(str(e), show_alert=True)
            return

        if action == "refresh":
            await _render_settings_menu(bot, user_id, chat_id=message.chat.id)
            await call.answer("✅ Обновлено")
            return

        if action == "close":
            ref = _settings_message_refs.pop(user_id, None)
            if ref:
                try:
                    await bot.delete_message(ref[0], ref[1])
                except Exception:
                    pass
            await call.answer()
            return

        await call.answer("Неизвестное действие", show_alert=True)
    except ValueError as exc:
        await call.answer(str(exc), show_alert=True)


@router.callback_query(IsAdmin(), F.data.startswith("news:"))
async def news_callback(call: CallbackQuery) -> None:
    user_id = call.from_user.id if call.from_user else None
    if user_id is None:
        await call.answer("Пользователь неизвестен", show_alert=True)
        return

    message = call.message
    if message is None:
        await call.answer("Сообщение недоступно", show_alert=True)
        return

    bot = message.bot
    if bot is None:
        await call.answer()
        return

    parts = (call.data or "").split(":", 1)
    action = parts[1] if len(parts) > 1 else ""
    draft = _news_drafts.get(user_id)
    chat_id = message.chat.id

    if action == "cancel":
        await _delete_message_safe(bot, chat_id, message.message_id)
        await _purge_news_draft(bot, user_id)
        _clear_pending_action(user_id)
        await call.answer("Отменено")
        await bot.send_message(chat_id=chat_id, text="Рассылка отменена.", parse_mode='HTML')
        return

    if draft is None or not draft.text:
        await call.answer("Нет подготовленной новости", show_alert=True)
        return

    if action == "edit":
        await _clear_news_preview(bot, draft)
        draft.text = None
        await _ask_news_content(bot, user_id, chat_id, "Введите новый текст новости.")
        await call.answer("Жду текст")
        return

    if action == "send":
        admins = app_settings.get_admin_ids()
        if not admins:
            await call.answer("Список администраторов пуст", show_alert=True)
            return
        await call.answer("Отправляю")
        delivered, failed = await _broadcast_news(bot, admins, draft.text)
        await _purge_news_draft(bot, user_id)
        _clear_pending_action(user_id)
        summary = f"Новость отправлена {delivered} из {len(admins)} администраторам."
        if failed:
            summary += f"\nНе доставлено: {len(failed)}."
        await bot.send_message(chat_id=chat_id, text=summary, parse_mode='HTML')
        return

    await call.answer("Неизвестное действие", show_alert=True)


@router.callback_query(IsAdmin(), F.data.startswith("tracking:"))
async def tracking_callback(call: CallbackQuery) -> None:
    """Handle inline actions for tracking management."""

    message = call.message
    if not isinstance(message, Message):
        await call.answer("Нет доступа к сообщению", show_alert=True)
        return

    user_id = call.from_user.id if call.from_user else None
    if not user_id:
        await call.answer("Пользователь неизвестен", show_alert=True)
        return

    bot = message.bot
    if bot is None:
        await call.answer("Бот недоступен", show_alert=True)
        return

    repository = TrackedPageRepository()
    data_parts = (call.data or "").split(":")

    if len(data_parts) < 2:
        await call.answer("Некорректное действие", show_alert=True)
        return

    action = data_parts[1]
    payload = data_parts[2] if len(data_parts) > 2 else ""

    notice: str | None = None
    need_refresh = False

    try:
        if action == "toggle":
            page_id = _parse_id(payload)
            page = repository.toggle_page(page_id)
            state_text = "активирована" if page.enabled else "отключена"
            notice = f"Страница <b>{html.escape(page.label)}</b> {state_text}."
            need_refresh = True
            await _cancel_pending_action(bot, user_id)
            await call.answer("Состояние обновлено")
        elif action == "remove":
            page_id = _parse_id(payload)
            removed = repository.remove_page(page_id)
            notice = f"Удалена <b>{html.escape(removed.label)}</b>."
            need_refresh = True
            await _cancel_pending_action(bot, user_id)
            await call.answer("Страница удалена")
        elif action == "refresh":
            need_refresh = True
            await _cancel_pending_action(bot, user_id)
            await call.answer("Обновлено")
        elif action == "filter":
            mode = payload or "all"
            applied = _set_filter(user_id, mode)
            label = dict(FILTER_OPTIONS).get(applied, "Все")
            notice = f"Отфильтровано: <b>{label}</b>"
            need_refresh = True
            await _cancel_pending_action(bot, user_id)
            await call.answer("Фильтр применён")
        elif action == "sort":
            if len(data_parts) < 3:
                await call.answer("Некорректное действие", show_alert=True)
                return
            page_id = _parse_id(data_parts[2])
            page = repository.get_page(page_id)
            await _cancel_pending_action(bot, user_id)
            prompt = await message.answer(
                (
                    "Выберите сортировку для <b>{label}</b>"
                ).format(label=html.escape(page.label)),
                parse_mode='HTML',
                reply_markup=_build_sort_keyboard(page_id, _extract_order_from_url(page.url)),
            )
            _set_pending_action(
                user_id,
                PendingAction(
                    action_type="sort",
                    page_id=page_id,
                    prompt_message_id=prompt.message_id,
                    prompt_chat_id=prompt.chat.id,
                ),
            )
            await call.answer("Выберите вариант")
            return
        elif action == "setorder":
            if len(data_parts) < 4:
                await call.answer("Некорректное действие", show_alert=True)
                return
            page_id = _parse_id(data_parts[2])
            order_token = data_parts[3]
            selected_order = None if order_token in {"none", ""} else order_token
            page = repository.update_sort(page_id, selected_order)
            notice = (
                f"Сортировка <b>{html.escape(_order_label(selected_order))}</b> "
                f"для <b>{html.escape(page.label)}</b>"
            )
            await _cancel_pending_action(bot, user_id)
            await _render_menu_for_user(bot, user_id, repository, notice=notice)
            await call.answer("Сортировка применена")
            return
        elif action == "cancel":
            await _cancel_pending_action(bot, user_id)
            await call.answer("Действие отменено")
            return
        elif action == "add":
            await _cancel_pending_action(bot, user_id)
            prompt = await message.answer(
                "Введите страницу в формате <b>URL</b> или <b>URL | название</b>",
                parse_mode='HTML',
                reply_markup=ForceReply(selective=True),
            )
            _set_pending_action(
                user_id,
                PendingAction(
                    action_type="add",
                    prompt_message_id=prompt.message_id,
                    prompt_chat_id=prompt.chat.id,
                ),
            )
            await call.answer("Жду ссылку")
            return
        elif action == "rename":
            await _cancel_pending_action(bot, user_id)
            page_id = _parse_id(payload)
            page = repository.get_page(page_id)
            prompt = await message.answer(
                (
                    "Новое название для страницы <b>{label}</b>\n"
                    "Просто отправьте текст сообщением."
                ).format(label=html.escape(page.label)),
                parse_mode='HTML',
                reply_markup=ForceReply(selective=True),
            )
            _set_pending_action(
                user_id,
                PendingAction(
                    action_type="rename",
                    page_id=page_id,
                    prompt_message_id=prompt.message_id,
                    prompt_chat_id=prompt.chat.id,
                ),
            )
            await call.answer("Введите название")
            return
        elif action == "latest":
            page_id = _parse_id(payload)
            page = repository.get_page(page_id)
            items = item_repository.get_recent_items(page.url)
            if not items:
                await call.answer("Для этой страницы пока нет сохранённых лотов.", show_alert=True)
                return
            await _cancel_pending_action(bot, user_id)
            preview = _compose_latest_preview(page, items, index=0)
            await _send_latest_preview_message(bot, message.chat.id, preview)
            await call.answer()
            return
        elif action == "latestnav":
            if len(data_parts) < 4:
                await call.answer("Некорректное действие", show_alert=True)
                return
            page_id = _parse_id(data_parts[2])
            try:
                target_index = int(data_parts[3])
            except ValueError:
                await call.answer("Некорректный индекс", show_alert=True)
                return
            page = repository.get_page(page_id)
            items = item_repository.get_recent_items(page.url)
            if not items:
                await call.answer("Для этой страницы пока нет сохранённых лотов.", show_alert=True)
                if message:
                    try:
                        await message.delete()
                    except Exception:
                        pass
                return
            preview = _compose_latest_preview(page, items, index=target_index)
            await _update_latest_preview_message(bot, message, preview)
            await call.answer()
            return
        elif action == "latestclose":
            if message:
                try:
                    await message.delete()
                except Exception:
                    pass
                await _clear_gallery(bot, message.chat.id, message.message_id)
            await call.answer()
            return
        elif action == "noop":
            await call.answer()
            return
        else:
            await call.answer("Неизвестное действие", show_alert=True)
            return
    except ValueError as exc:
        await call.answer(str(exc), show_alert=True)
        return

    if need_refresh:
        await _refresh_menu_message(message, repository, user_id, notice=notice)


@router.message(IsAdmin(), F.reply_to_message)
async def tracking_reply_handler(message: Message) -> None:
    """Process replies to ForceReply prompts for tracking actions."""

    user_id = _extract_user_id(message)
    if not user_id:
        return

    pending = _pending_actions.get(user_id)
    if not pending:
        return

    reply_message = message.reply_to_message
    if not reply_message or pending.prompt_message_id != reply_message.message_id:
        return

    bot = message.bot
    if bot is None:
        return

    text = (message.text or "").strip()

    if not text:
        await message.answer(
            "❌ <b>Ошибка:</b> сообщение не должно быть пустым",
            parse_mode='HTML'
        )
        return

    if text.lower() in {"/cancel", "cancel", "отмена"}:
        await message.answer("Действие отменено", parse_mode='HTML')
        await _cancel_pending_action(bot, user_id)
        try:
            await bot.delete_message(message.chat.id, message.message_id)
        except Exception:
            pass
        return

    notice: str | None = None
    action_type = pending.action_type

    if action_type == "settings_add_admin":
        try:
            updated_admins = app_settings.add_admin(text)
        except ValueError as exc:
            await message.answer(
                f"❌ <b>Ошибка:</b> {html.escape(str(exc))}",
                parse_mode='HTML'
            )
        else:
            await message.answer(
                "👥 <b>Администратор добавлен</b>\n"
                f"Теперь администраторов: {len(updated_admins)}.",
                parse_mode='HTML'
            )
            await _render_settings_menu(bot, user_id, chat_id=message.chat.id)
        finally:
            _clear_pending_action(user_id)
            if pending.prompt_chat_id is not None and pending.prompt_message_id is not None:
                try:
                    await bot.delete_message(pending.prompt_chat_id, pending.prompt_message_id)
                except Exception:
                    pass
            try:
                await bot.delete_message(message.chat.id, message.message_id)
            except Exception:
                pass
        return

    if action_type == "news_collect":
        draft = _ensure_news_draft(user_id)
        draft.text = text
        await _clear_news_prompt(bot, draft)
        await _delete_message_safe(bot, message.chat.id, message.message_id)
        _clear_pending_action(user_id)
        await _show_news_preview(bot, user_id, message.chat.id)
        return

    repository = TrackedPageRepository()

    try:
        if action_type == "add":
            url, label = _parse_add_payload(text)
            page = repository.add_page(url, label)
            notice = f"Добавлена <b>{html.escape(page.label)}</b>"
        elif action_type == "rename":
            if pending.page_id is None:
                raise ValueError("Неизвестная страница")
            page = repository.update_label(pending.page_id, text)
            notice = f"Название обновлено: <b>{html.escape(page.label)}</b>"
        else:
            return
    except ValueError as exc:
        await message.answer(
            f"❌ <b>Ошибка:</b> {html.escape(str(exc))}",
            parse_mode='HTML'
        )
        return
    finally:
        _clear_pending_action(user_id)

    if pending.prompt_chat_id is not None and pending.prompt_message_id is not None:
        try:
            await bot.delete_message(pending.prompt_chat_id, pending.prompt_message_id)
        except Exception:
            pass

    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    await _render_menu_for_user(bot, user_id, repository, notice=notice)


@router.message(Command("resend"), IsAdmin())
async def cmd_resend_missed_coins(message: Message) -> None:
    """Resend notifications for missed coins from logs."""
    user_id = message.from_user.id
    
    # Extract URLs from message text
    text = message.text or ""
    lines = text.split('\n')[1:]  # Skip command line
    
    urls = []
    for line in lines:
        line = line.strip()
        if line.startswith('/lot/') and line.endswith('.html'):
            # Convert relative URL to full URL
            full_url = f"https://ay.by{line}"
            urls.append(full_url)
    
    if not urls:
        await message.reply(
            "❌ Не найдено URL монет!\n\n"
            "Формат:\n"
            "/resend\n"
            "/lot/moneta-1.html\n"
            "/lot/moneta-2.html\n"
            "..."
        )
        return
    
    await message.reply(
        f"🔄 Начинаю отправку {len(urls)} монет...\n"
        f"Это может занять некоторое время."
    )
    
    sent_count = 0
    error_count = 0
    
    for url in urls:
        try:
            # Fetch item details (forced resend - skip database check)
            html = parser.get_page_content(url)
            if not html:
                logger.warning("Failed to fetch %s", url)
                error_count += 1
                continue
            
            # Parse single item page
            item = parser.parse_single_item_page(html, url)
            if not item:
                logger.warning("No item parsed from %s", url)
                error_count += 1
                continue
            
            # Send notification
            caption = _build_resend_caption(item)
            media_urls = list(item.image_urls) if item.image_urls else ([item.img_url] if item.img_url else [])
            
            try:
                if len(media_urls) > 1:
                    media_group = []
                    for index, media_url in enumerate(media_urls[:MAX_MEDIA_GROUP_SIZE]):
                        if index == 0:
                            media_group.append(
                                InputMediaPhoto(media=media_url, caption=caption, parse_mode="HTML")
                            )
                        else:
                            media_group.append(InputMediaPhoto(media=media_url))
                    await message.bot.send_media_group(chat_id=message.chat.id, media=media_group)
                elif media_urls:
                    await message.bot.send_photo(
                        chat_id=message.chat.id,
                        photo=media_urls[0],
                        caption=caption,
                        parse_mode="HTML"
                    )
                else:
                    await message.bot.send_message(
                        chat_id=message.chat.id,
                        text=caption,
                        parse_mode="HTML"
                    )
                
                # Save to database to avoid duplicates
                item_repository.save_items([item], source_url="resend_command")
                sent_count += 1
                
                # Rate limiting
                await asyncio.sleep(1.5 if len(media_urls) > 1 else 0.8)
                
            except Exception as exc:
                logger.exception("Failed to send notification for %s", url)
                error_count += 1
                
        except Exception as exc:
            logger.exception("Error processing %s", url)
            error_count += 1
    
    # Summary
    summary = (
        f"✅ Завершено!\n\n"
        f"📤 Отправлено: {sent_count}\n"
        f"❌ Ошибок: {error_count}\n"
        f"📊 Всего: {len(urls)}"
    )
    await message.answer(summary)


def _build_resend_caption(item: Item) -> str:
    """Build caption for resent coin notification."""
    title = html.escape(item.title)
    url = html.escape(item.url, quote=True)
    raw_price = (item.price or "").strip()
    has_price = raw_price and raw_price.casefold() != "цена не указана"
    price_value = html.escape(raw_price) if has_price else "Цена не указана"
    price_line = f"💰 <b>{price_value}</b>" if has_price else "💰 <i>Цена не указана</i>"
    
    return "\n".join([
        "🔄 <b>Пропущенная монета</b>",
        f"<b>{title}</b>",
        "",
        price_line,
        "",
        f"🌐 <a href=\"{url}\">Перейти к лоту</a>",
    ])




