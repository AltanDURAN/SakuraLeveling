"""Tests de la vérification d'origine CSRF (logique pure)."""

from webapp.admin.csrf import request_origin_is_allowed


def test_safe_methods_always_pass():
    assert request_origin_is_allowed("GET", "/admin/items", None, None) is True
    assert request_origin_is_allowed("HEAD", "/admin", "https://evil.test", None) is True


def test_non_admin_paths_not_enforced():
    assert request_origin_is_allowed("POST", "/skill/123", "https://evil.test", None) is True


def test_post_admin_without_origin_or_referer_rejected():
    assert request_origin_is_allowed("POST", "/admin/players/1/reset", None, None) is False


def test_post_admin_foreign_origin_rejected():
    assert request_origin_is_allowed(
        "POST", "/admin/items/x/delete", "https://evil.example.com", None
    ) is False


def test_post_admin_localhost_origin_allowed():
    assert request_origin_is_allowed(
        "POST", "/admin/items/x/delete", "http://localhost:8001", None
    ) is True


def test_referer_used_as_fallback():
    assert request_origin_is_allowed(
        "DELETE", "/admin/mobs/x/delete", None, "http://127.0.0.1:8001/admin/mobs"
    ) is True
