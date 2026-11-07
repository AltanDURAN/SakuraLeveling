"""Le rang gagné survit à un départ du serveur, et les classes ne passent plus
sous le badge de /profil (audit d'ouverture, 07/11/2026)."""

import asyncio
from types import SimpleNamespace

from PIL import ImageFont

from app.bot import rank_roles
from app.bot.rendering.profile_banner import _fit_classes
from app.infrastructure.config.settings import Settings

ROLES = {"F": 1, "E": 2, "D": 3}


class Guild:
    def get_role(self, role_id):
        return SimpleNamespace(id=role_id)


class Member:
    bot = False

    def __init__(self, role_ids=()):
        self.id = 42
        self.guild = Guild()
        self.roles = [SimpleNamespace(id=r) for r in role_ids]

    async def add_roles(self, role, reason=""):
        self.roles.append(role)

    async def remove_roles(self, *roles, reason=""):
        gone = {r.id for r in roles}
        self.roles = [r for r in self.roles if r.id not in gone]


def _configure(monkeypatch, earned: str = "F") -> list:
    monkeypatch.setattr(Settings, "rank_roles", property(lambda self: ROLES))
    saved = []
    monkeypatch.setattr(rank_roles, "_earned_rank", lambda discord_id: earned)
    monkeypatch.setattr(rank_roles, "_save_earned_rank", lambda discord_id, rank: saved.append(rank))
    return saved


def test_un_joueur_qui_revient_retrouve_son_rang(monkeypatch):
    saved = _configure(monkeypatch, earned="D")
    member = Member()
    asyncio.run(rank_roles.ensure_start_rank_role(member))
    assert [r.id for r in member.roles] == [3] and saved == ["D"]


def test_un_nouveau_recoit_le_rang_f(monkeypatch):
    _configure(monkeypatch)
    member = Member()
    asyncio.run(rank_roles.ensure_start_rank_role(member))
    assert [r.id for r in member.roles] == [1]


def test_un_rang_porte_n_est_jamais_touche(monkeypatch):
    saved = _configure(monkeypatch, earned="D")
    member = Member([2])
    asyncio.run(rank_roles.ensure_start_rank_role(member))
    assert [r.id for r in member.roles] == [2] and saved == []


def test_chaque_changement_de_rang_est_garde(monkeypatch):
    saved = _configure(monkeypatch)
    member = Member([1])
    assert asyncio.run(rank_roles.set_rank_role(member, "E"))
    assert [r.id for r in member.roles] == [2] and saved == ["E"]


def test_les_classes_qui_ne_tiennent_pas_deviennent_un_nombre():
    font = ImageFont.load_default(24)
    classes = "Guerrier · Gardien · Clerc · Paladin · Rempart"
    assert _fit_classes("Niveau 30", classes, font, 2000) == f"Niveau 30  ·  {classes}"
    short = _fit_classes("Niveau 30", classes, font, 300)
    assert short.startswith("Niveau 30  ·  Guerrier") and short.rstrip("0123456789").endswith("+")
    assert _fit_classes("Niveau 30", None, font, 300) == "Niveau 30"
