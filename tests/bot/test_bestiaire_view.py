"""Bestiaire : un menu pour parcourir une famille, et plus aucun terme
technique sur la fiche."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from app.bot.views.bestiaire_view import ALL_FAMILIES, BestiaireView, family_label
from app.domain.entities.mob_definition import MobDefinition


def _mob(code: str, family: str) -> MobDefinition:
    now = datetime.now(UTC)
    return MobDefinition(id=1, code=code, name=code.capitalize(), description="", image_name=None, family=family,
                         max_hp=100, current_hp=100, attack=10, defense=5, xp_reward=5, gold_reward=2, spawn_weight=30,
                         speed=5, crit_chance=0, crit_damage=100, dodge=0, hp_regeneration=0, loot_table=None,
                         created_at=now, updated_at=now)


class Interaction:
    def __init__(self, user_id=1):
        self.user = SimpleNamespace(id=user_id)
        self.response = self

    async def edit_message(self, **kwargs):
        self.edited = kwargs


def test_le_nom_d_une_famille_se_lit():
    assert family_label("mort_vivant") == "Mort-vivant" and family_label("") == "Sans famille"


def test_filtrer_une_famille_reprend_a_la_premiere_page():
    async def scenario():
        view = BestiaireView(1, [_mob("slime", "slime"), _mob("gobelin", "gobelin"), _mob("chaman", "gobelin")])
        view.index = 2
        await view.show_family(Interaction(), "gobelin")
        assert [m.code for m in view.mobs] == ["gobelin", "chaman"] and view.index == 0
        assert view.counter.label == "1 / 2"
        await view.show_family(Interaction(), ALL_FAMILIES)
        assert len(view.mobs) == 3

    asyncio.run(scenario())


def test_la_fiche_ne_montre_ni_code_ni_poids():
    async def scenario():
        embed, _ = BestiaireView(1, [_mob("gobelin_geant", "gobelin")]).render_current()
        return " ".join(f.value for f in embed.fields)

    text = asyncio.run(scenario())
    assert "gobelin_geant" not in text and "Poids" not in text and "Famille : **Gobelin**" in text
