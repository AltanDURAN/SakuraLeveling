"""Bestiaire : un menu pour parcourir une famille, plus aucun terme technique
sur la fiche, et à DÉCOUVRIR (07/11/2026) : silhouette tant que le monstre n'a
pas été vaincu, victoires du joueur ensuite."""

import asyncio
import io
from datetime import UTC, datetime
from types import SimpleNamespace

from PIL import Image

from app.bot.rendering import silhouette
from app.bot.views.bestiaire_view import ALL_FAMILIES, BestiaireView, family_label
from app.domain.entities.mob_definition import MobDefinition
from app.shared.paths import MOBS_ASSETS_DIR


def _mob(code: str, family: str, image_name: str | None = None) -> MobDefinition:
    now = datetime.now(UTC)
    return MobDefinition(id=1, code=code, name=code.capitalize(), description="Une gelée qui rôde.",
                         image_name=image_name, family=family,
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
        embed, _ = await BestiaireView(1, [_mob("gobelin_geant", "gobelin")]).render()
        return " ".join(f.value for f in embed.fields)

    text = asyncio.run(scenario())
    assert "gobelin_geant" not in text and "Poids" not in text and "Famille : **Gobelin**" in text


def _all_text(embed) -> str:
    return " ".join([embed.title or "", embed.description or "", embed.footer.text or ""]
                    + [f"{f.name} {f.value}" for f in embed.fields])


def test_un_monstre_jamais_vaincu_n_est_qu_une_silhouette():
    view = BestiaireView(1, [_mob("slime", "slime", "slime.png"), _mob("gobelin", "gobelin", "gobelin.png")],
                         kills={"gobelin": 3})
    embed, file = asyncio.run(view.render())
    text = _all_text(embed)
    assert embed.title == "❔ ???" and "Slime" not in text and "slime.png" not in text and "PV" not in text
    assert file.filename == "inconnu.png" and embed.thumbnail.url == "attachment://inconnu.png"
    assert "📖 1/2 découverts" in embed.footer.text and "Où le trouver" in text


def test_un_monstre_vaincu_montre_sa_fiche_et_les_victoires():
    view = BestiaireView(1, [_mob("slime", "slime", "slime.png")], kills={"slime": 1234})
    embed, file = asyncio.run(view.render())
    victories = next(f for f in embed.fields if f.name == "⚔️ Tes victoires")
    assert embed.title == "📖 Slime" and victories.value == "**1 234**"
    assert file.filename == "slime.png" and "📖 1/1 découverts" in embed.footer.text


def test_sans_image_ni_victoire_pas_de_vignette():
    embed, file = asyncio.run(BestiaireView(1, [_mob("dragon", "draconique")], kills={}).render())
    assert file is None and embed.thumbnail.url is None and embed.title == "❔ ???"


def test_le_menu_des_familles_dit_ce_qui_reste_a_decouvrir():
    view = BestiaireView(1, [_mob("slime", "slime"), _mob("gobelin", "gobelin"), _mob("chaman", "gobelin")],
                         kills={"chaman": 2})
    menu = next(item for item in view.children if hasattr(item, "options"))
    assert [o.description for o in menu.options] == ["📖 1/3 découverts", "📖 0/1 découverts",
                                                     "📖 1/2 découverts"]


def test_la_silhouette_garde_la_forme_et_cache_tout_le_reste():
    data = silhouette.silhouette_png(MOBS_ASSETS_DIR / "gobelin.png")
    image = Image.open(io.BytesIO(data)).convert("RGBA")
    assert image.size == (silhouette.SIZE, silhouette.SIZE)
    raw = image.tobytes()
    pixels = [tuple(raw[i:i + 4]) for i in range(0, len(raw), 4)]
    opaque = [p for p in pixels if p[3] == 255]
    assert len(opaque) > 5000                                           # la forme du monstre
    assert all(abs(p[c] - silhouette.FILL[c]) <= 2 for p in opaque for c in range(3))   # aucune de ses couleurs
    assert image.getpixel((0, 0))[3] == 0                               # le fond reste transparent
    halo = [p for p in pixels if 0 < p[3] < 200 and p[:3] == silhouette.GLOW]
    assert len(halo) > 100                                              # un halo pour le thème sombre
