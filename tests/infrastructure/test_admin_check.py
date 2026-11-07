import pytest

from app.bot.checks.admin_check import is_admin_user
from app.infrastructure.config.settings import settings

ADMIN_ID = 701782195844546662


@pytest.fixture(autouse=True)
def _admins(monkeypatch):
    """La liste vient du `.env` : absent sur GitHub, on la pose ici."""
    monkeypatch.setattr(settings, "admin_discord_ids", f"{ADMIN_ID}, 42")


def test_settings_parses_admin_discord_ids():
    assert settings.admin_ids == [ADMIN_ID, 42]


def test_is_admin_user_recognizes_admin_id():
    assert is_admin_user(ADMIN_ID) is True


def test_is_admin_user_rejects_non_admin_id():
    assert is_admin_user(123456789) is False
    assert is_admin_user(0) is False
