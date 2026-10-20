"""Investir dans son arbre depuis le web (connexion Discord du joueur).

Vérifie : 401 sans connexion, 403 sur l'arbre d'un autre, refus d'une origine
étrangère (CSRF), investissement réel pour le propriétaire, et que la connexion
joueur ne délivre JAMAIS de session admin.
"""

from __future__ import annotations

import importlib
import os
import pkgutil
from contextlib import contextmanager
from datetime import datetime, UTC

os.environ.setdefault("ADMIN_SESSION_SECRET", "test-secret-for-pytest-only-32chars-min-aaaaa")
os.environ.setdefault("DISCORD_TOKEN", "x")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("BETA_CHANNEL_ID", "1")
os.environ.setdefault("ENCOUNTER_CHANNEL_ID", "1")
os.environ.setdefault("ADMIN_DISCORD_IDS", "")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

OWNER, OTHER = 111, 222
ORIGIN = {"Origin": "http://localhost:8001"}


@pytest.fixture
def client(monkeypatch):
    import app.infrastructure.db.models as models_pkg
    for mod in pkgutil.iter_modules(models_pkg.__path__):
        importlib.import_module(f"{models_pkg.__name__}.{mod.name}")
    from app.infrastructure.db.base import Base
    from app.infrastructure.db.models.player_model import PlayerModel
    from app.infrastructure.db.models.progression_model import PlayerProgressionModel
    from app.infrastructure.db.models.resource_model import PlayerResourceModel

    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine)
    with maker() as s:
        now = datetime.now(UTC)
        for pid, did in ((1, OWNER), (2, OTHER)):
            p = PlayerModel(id=pid, discord_id=did, username=f"u{pid}", display_name=f"U{pid}",
                            created_at=now, updated_at=now, last_seen_at=now)
            p.progression = PlayerProgressionModel(level=10, xp=0, skill_points=50,
                                                   created_at=now, updated_at=now)
            p.resources = PlayerResourceModel(gold=0, created_at=now, updated_at=now)
            s.add(p)
        s.commit()

    @contextmanager
    def fake_session():
        with maker() as s:
            yield s

    import webapp.main as main
    monkeypatch.setattr(main, "get_db_session", fake_session)
    with TestClient(main.app) as c:
        c.maker = maker
        yield c


def _cookie(discord_id, name="Joueur"):
    from webapp.player_auth import _serializer
    return {"sakura_player_session": _serializer().dumps(
        {"discord_id": discord_id, "display_name": name})}


def _unlockable_code():
    from app.domain.services.skill_tree_service import SkillTreeService
    from app.infrastructure.skill_tree.skill_tree_loader import get_definition
    definition = get_definition()
    service = SkillTreeService(definition)
    return next(n.code for n in definition.skills.values()
                if not n.start and service.compute_node_state({}, n.code) == "unlockable")


def test_page_propose_la_connexion_si_anonyme(client):
    html = client.get(f"/skill/{OWNER}").text
    assert "Se connecter avec Discord" in html
    assert f"/skill/login?next=/skill/{OWNER}" in html


def test_investir_sans_connexion_401(client):
    r = client.post(f"/api/skill/{OWNER}/invest", json={"code": _unlockable_code()}, headers=ORIGIN)
    assert r.status_code == 401


def test_investir_dans_l_arbre_d_un_autre_403(client):
    client.cookies.update(_cookie(OTHER))
    r = client.post(f"/api/skill/{OWNER}/invest", json={"code": _unlockable_code()}, headers=ORIGIN)
    assert r.status_code == 403


def test_origine_etrangere_refusee(client):
    client.cookies.update(_cookie(OWNER))
    r = client.post(f"/api/skill/{OWNER}/invest", json={"code": _unlockable_code()},
                    headers={"Origin": "https://evil.example.com"})
    assert r.status_code == 403


def test_le_proprietaire_investit_pour_de_vrai(client):
    from app.infrastructure.db.repositories.player_skill_allocation_repository import (
        PlayerSkillAllocationRepository,
    )
    code = _unlockable_code()
    client.cookies.update(_cookie(OWNER))
    r = client.post(f"/api/skill/{OWNER}/invest", json={"code": code}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] and "<svg" in data["svg"] and data["available_points"] < 50
    assert any(n["code"] == code and n["current_level"] == 1 for n in data["nodes"])
    with client.maker() as s:
        assert PlayerSkillAllocationRepository(s).list_by_player(1).get(code) == 1

    page = client.get(f"/skill/{OWNER}").text
    assert '"is_owner": true' in page and "Se déconnecter" in page


def test_case_invalide_refusee_sans_rien_changer(client):
    client.cookies.update(_cookie(OWNER))
    r = client.post(f"/api/skill/{OWNER}/invest", json={"code": "nexiste_pas"}, headers=ORIGIN)
    assert r.status_code == 400 and r.json()["ok"] is False


def test_login_joueur_valide_la_destination(client):
    r = client.get("/skill/login?next=https://evil.example.com", follow_redirects=False)
    assert r.headers["location"] == "/"
    r = client.get(f"/skill/login?next=/skill/{OWNER}", follow_redirects=False)
    assert "discord.com" in r.headers["location"]
    assert r.cookies.get("sakura_oauth_next") == str(OWNER)


def test_callback_joueur_ne_donne_pas_de_session_admin(client, monkeypatch):
    import webapp.admin.routers.auth_router as auth_router

    async def fake_token(code):
        return "tok"

    async def fake_identity(token):
        return {"id": str(OWNER), "username": "u1", "global_name": "Joueur"}

    monkeypatch.setattr(auth_router, "exchange_code_for_token", fake_token)
    monkeypatch.setattr(auth_router, "fetch_user_identity", fake_identity)
    client.cookies.update({"sakura_oauth_state": "st", "sakura_oauth_next": str(OWNER)})
    r = client.get("/admin/auth/callback?code=c&state=st", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/skill/{OWNER}"
    assert "sakura_player_session" in r.cookies
    assert "sakura_admin_session" not in r.cookies
