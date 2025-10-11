from __future__ import annotations

import pytest

from config import settings
from services.storage import TrackedPageRepository


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
