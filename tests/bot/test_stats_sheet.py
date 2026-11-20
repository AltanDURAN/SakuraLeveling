"""`/stats` en image (demande de l'auteur, 20/11/2026), embed texte en repli."""

from PIL import Image

from app.bot.cogs import stats_cog
from app.bot.rendering.stats_sheet import compose_stats_sheet

DATA = {"player_id": 7, "display_name": "W" * 32, "level": 100, "xp": 0, "xp_required": 0, "stat_points": 12,
        "points": {"attack": 40, "defense": 30, "max_hp": 29}, "base": {"attack": 90, "defense": 65, "max_hp": 1550},
        "final": {"attack": 1234567, "defense": 98765, "max_hp": 1234567},
        "secondary": {"speed": 99, "crit_chance": 100, "crit_damage": 999, "dodge": 100,
                      "hp_regeneration": 9999, "mana_max": 99999}}


def test_la_feuille_se_dessine_meme_dans_le_pire_cas(tmp_path):
    out = tmp_path / "s.png"
    compose_stats_sheet(str(out), DATA, gains={"attack": 2, "defense": 2, "max_hp": 50})
    with Image.open(out) as img:
        assert img.width == 1024 and 500 < img.height < 800


def test_le_rendu_rate_retombe_sur_l_embed_texte(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("Pillow en panne")

    monkeypatch.setattr("app.bot.rendering.stats_sheet.compose_stats_sheet", boom)
    embed, files = stats_cog._render(DATA)
    assert files == [] and "12 points de stats" in embed.description
