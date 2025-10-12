from __future__ import annotations

import pytest

from config import settings
from models import Item
from services.storage import ItemRepository, TrackedPageRepository


def test_tracked_page_repository_seed(temp_db):
    repository = TrackedPageRepository()
    pages = repository.list_pages()

    assert len(pages) == len(settings.MONITOR_URLS)
    assert {page.url for page in pages} == set(settings.MONITOR_URLS)


def test_tracked_page_repository_add_toggle_remove(temp_db):
    repository = TrackedPageRepository()

    page = repository.add_page(
        "https://example.com/some-page?order=create",
        "Новые предложения",
    )
    assert page.id is not None
    assert page.enabled is True

    toggled = repository.toggle_page(page.id)
    assert toggled.enabled is False

    renamed = repository.update_label(page.id, "Обновлённые предложения")
    assert renamed.label == "Обновлённые предложения"

    removed = repository.remove_page(page.id)
    assert removed.id == page.id

    with pytest.raises(ValueError):
        repository.toggle_page(page.id)


def test_tracked_page_repository_disable_all_then_empty_enabled_list(temp_db):
    repository = TrackedPageRepository()
    pages = repository.list_pages()

    for page in pages:
        assert page.id is not None
        toggle_result = repository.toggle_page(page.id)
        assert toggle_result.enabled is False

    assert repository.get_enabled_urls() == []


def test_tracked_page_repository_get_enabled_pages(temp_db):
    repository = TrackedPageRepository()

    enabled_pages = repository.get_enabled_pages()

    assert [page.url for page in enabled_pages] == list(settings.MONITOR_URLS)
    assert [page.label for page in enabled_pages]
    assert all(page.enabled for page in enabled_pages)


def test_tracked_page_repository_no_reseed_after_clear(temp_db):
    repository = TrackedPageRepository()

    for page in repository.list_pages():
        assert page.id is not None
        repository.remove_page(page.id)

    assert repository.list_pages() == []

    # Recreate repository against same DB, defaults should not reappear
    repository_again = TrackedPageRepository()
    assert repository_again.list_pages() == []


def test_tracked_page_repository_update_sort(temp_db):
    repository = TrackedPageRepository()
    pages = repository.list_pages()
    assert pages
    page = pages[0]
    assert page.id is not None

    updated = repository.update_sort(page.id, "cost_desc")
    assert "order=cost_desc" in updated.url

    updated_again = repository.update_sort(page.id, None)
    assert "order=" not in updated_again.url

    with pytest.raises(ValueError):
        repository.update_sort(page.id, "unknown-sort")


def test_update_sort_preserves_existing_query_parameters(temp_db):
    repository = TrackedPageRepository()
    page = repository.add_page(
        "https://example.com/catalog?f=1&ti1=6",
        "Каталог",
    )
    assert page.id is not None

    sorted_page = repository.update_sort(page.id, "create")
    assert sorted_page.url == "https://example.com/catalog?f=1&ti1=6&order=create"

    reverted_page = repository.update_sort(page.id, None)
    assert reverted_page.url == "https://example.com/catalog?f=1&ti1=6"


def test_item_repository_get_recent_items(temp_db):
    item_repository = ItemRepository()
    source_url = "https://example.com/list"

    initial_batch = [
        Item(
            url=f"https://example.com/lot{i}",
            title=f"Lot {i}",
            price=f"{i * 10}",
            img_url=f"https://example.com/img{i}",
        )
        for i in range(1, 6)
    ]

    item_repository.save_items(initial_batch, source_url)

    new_batch = [
        Item(
            url=f"https://example.com/lot{i}",
            title=f"Lot {i}",
            price=f"{i * 10}",
            img_url=f"https://example.com/img{i}",
        )
        for i in range(6, 18)
    ]

    item_repository.save_items(new_batch, source_url)

    recent_all = item_repository.get_recent_items(source_url)

    assert len(recent_all) == len(initial_batch) + len(new_batch)
    first_item, saved_at = recent_all[0]
    assert first_item.url == new_batch[-1].url
    assert saved_at is not None

    limited = item_repository.get_recent_items(source_url, limit=5)
    assert len(limited) == 5
    assert limited[0][0].url == new_batch[-1].url

    empty_limited = item_repository.get_recent_items(source_url, limit=0)
    assert empty_limited == []
