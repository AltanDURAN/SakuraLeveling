from app.bot.checks.admin_check import is_admin_user
from app.infrastructure.config.settings import settings


def test_settings_parses_admin_discord_ids():
    """L'id 701782195844546662 (Altan) doit être reconnu comme admin via .env."""

    assert 701782195844546662 in settings.admin_ids


def test_is_admin_user_recognizes_admin_id():
    assert is_admin_user(701782195844546662) is True


def test_is_admin_user_rejects_non_admin_id():
    assert is_admin_user(123456789) is False
    assert is_admin_user(0) is False
