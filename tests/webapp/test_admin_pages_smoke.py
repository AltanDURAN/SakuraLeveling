"""Toutes les pages GET de l'admin s'affichent sans erreur serveur.

Filet contre les régressions silencieuses : une constante emportée par un
nettoyage (cf. `SKILL_EFFECT_TYPES`, oct. 2026) ne cassait qu'une page que
personne n'ouvrait. La base est en mémoire, avec le contenu réel seedé et un
joueur.
"""

from __future__ import annotations

import importlib
import os
import pkgutil
from datetime import UTC, datetime

os.environ.setdefault("ADMIN_SESSION_SECRET", "test-secret-for-pytest-only-32chars-min-aaaaa")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

SUBS = {
    "code": "gobelin", "family": "gobelin", "element": "feu", "event_type": "chest",
    "mob_code": "gobelin", "discord_id": "424242", "scope": "daily",
}


def _collect(routes):
    for r in routes:
        if type(r).__name__ == "_IncludedRouter":
            yield from _collect(r.original_router.routes)
        else:
            yield r


@pytest.fixture
def client(monkeypatch):
    import app.infrastructure.db.models as models_pkg
    for mod in pkgutil.iter_modules(models_pkg.__path__):
        importlib.import_module(f"{models_pkg.__name__}.{mod.name}")
    from app.infrastructure.db import session as db_session
    from app.infrastructure.db.base import Base

    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    old_bind = db_session.SessionLocal.kw.get("bind")
    db_session.SessionLocal.configure(bind=engine)
    try:
        from app.infrastructure.db.repositories.player_repository import PlayerRepository
        from app.infrastructure.db.seeders import seed_content
        seed_content.main() if hasattr(seed_content, "main") else None
        with db_session.get_db_session() as s:
            pid = PlayerRepository(s).get_or_create_by_discord_id(424242, "t", "Testeur").player.id

        from webapp.admin.auth import AdminUser, require_admin
        from webapp.main import app

        app.dependency_overrides[require_admin] = lambda: AdminUser(1, "a", "A")

        async def _no_avatar(*a, **k):
            return ""

        monkeypatch.setattr("webapp.admin.discord_api.avatar_url_for", _no_avatar)
        with TestClient(app, raise_server_exceptions=False) as c:
            c.player_id = pid
            c.app_routes = list(_collect(app.routes))
            yield c
        app.dependency_overrides.pop(require_admin, None)
    finally:
        db_session.SessionLocal.configure(bind=old_bind)


def test_toutes_les_pages_admin_s_affichent(client):
    from app.infrastructure.encounters.farm_zone_loader import list_zones

    subs = {**SUBS, "player_id": str(client.player_id),
            "channel_id": str(list_zones()[0]["channel_id"])}
    failures = []
    checked = 0
    for route in client.app_routes:
        if "GET" not in getattr(route, "methods", set()):
            continue
        path = route.path
        if not path.startswith("/admin") or "auth/callback" in path:
            continue
        for key, value in subs.items():
            path = path.replace("{" + key + "}", value)
        if "{" in path:
            continue
        status = client.get(path, follow_redirects=False).status_code
        checked += 1
        if status >= 500:
            failures.append((path, status))
    assert checked > 30
    assert failures == []
