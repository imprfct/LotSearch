from __future__ import annotations

import importlib

import pytest

from config import settings
from services.storage import AppSettingsRepository


@pytest.mark.usefixtures("mock_env_vars")
def test_format_minutes_variations():
    handlers = importlib.import_module("bot.handlers")
    handlers = importlib.reload(handlers)
    assert handlers._format_minutes(1) == "1 минута"
    assert handlers._format_minutes(2) == "2 минуты"
    assert handlers._format_minutes(5) == "5 минут"
    assert handlers._format_minutes(21) == "21 минута"
    assert handlers._format_interval_phrase(1) == "каждую 1 минуту"
    assert handlers._format_interval_phrase(2) == "каждые 2 минуты"
    assert handlers._format_interval_phrase(5) == "каждые 5 минут"


@pytest.mark.usefixtures("mock_env_vars")
def test_app_settings_interval_persistence(temp_db):
    repository = AppSettingsRepository(db_path=temp_db)
    assert settings.CHECK_INTERVAL_MINUTES == 60

    repository.set_check_interval(7)
    assert settings.CHECK_INTERVAL_MINUTES == 7

    repository_again = AppSettingsRepository(db_path=temp_db)
    assert repository_again.get_check_interval() == 7
    assert settings.CHECK_INTERVAL_MINUTES == 7


@pytest.mark.usefixtures("mock_env_vars")
def test_app_settings_add_admin(temp_db):
    repository = AppSettingsRepository(db_path=temp_db)
    base_admins = set(settings.ADMIN_CHAT_IDS)

    new_admin = 555666777
    updated = repository.add_admin(new_admin)
    assert new_admin in updated
    assert new_admin in settings.ADMIN_CHAT_IDS

    repository_again = AppSettingsRepository(db_path=temp_db)
    assert new_admin in repository_again.get_admin_ids()

    with pytest.raises(ValueError):
        repository.add_admin(new_admin)
    assert set(settings.ADMIN_CHAT_IDS) == base_admins | {new_admin}
