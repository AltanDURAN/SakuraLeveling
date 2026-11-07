"""Bestiaire des world boss (`/bestiaire boss`, 07/11/2026) : même style que
celui des monstres, à découvrir ; `/boss list` n'existe plus."""

import asyncio

from app.bot.cogs.bestiaire_cog import BestiaireCog
from app.bot.cogs.world_boss_cog import WorldBossCog
from app.bot.views.boss_bestiary_view import BossBestiaryView, mechanics_lines
from app.infrastructure.world_boss.boss_definition_loader import list_definitions


def _text(embed) -> str:
    return " ".join([embed.title or "", embed.description or "", embed.footer.text or ""]
                    + [f"{f.name} {f.value}" for f in embed.fields])


def test_bestiaire_est_un_groupe_et_boss_list_a_disparu():
    assert {c.name for c in BestiaireCog.bestiaire.commands} == {"monstres", "boss"}
    assert "list" not in {c.name for c in WorldBossCog.boss.commands}


def test_un_boss_jamais_abattu_n_est_qu_une_silhouette():
    bosses = list_definitions()
    first = min(bosses, key=lambda b: b.level)
    view = BossBestiaryView(1, bosses, victories={}, boss_channel_id=99)
    embed, file = asyncio.run(view.render())
    text = _text(embed)
    assert embed.title == "❔ ???" and first.name not in text and "PV" not in text
    assert file.filename == "inconnu.png" and "<#99>" in text and f"niveau **{first.level}**" in text
    assert f"👑 0/{len(bosses)} vaincus" in embed.footer.text


def test_un_boss_abattu_montre_sa_fiche_ses_mecaniques_et_les_victoires():
    bosses = list_definitions()
    first = min(bosses, key=lambda b: b.level)
    view = BossBestiaryView(1, bosses, victories={first.code: 2})
    embed, file = asyncio.run(view.render())
    text = _text(embed)
    victories = next(f for f in embed.fields if f.name == "⚔️ Tes victoires")
    assert embed.title == f"👑 {first.name}" and victories.value == "**2**"
    assert all(phase["name"] in text for phase in first.phases) and first.ultimate["name"] in text
    assert "_" not in " ".join(mechanics_lines(first))                  # aucun nom technique
    assert file.filename == first.image_name and f"👑 1/{len(bosses)} vaincus" in embed.footer.text
    assert all(len(f.value) <= 1024 for f in embed.fields) and len(embed) <= 6000


def test_les_boss_sont_tries_par_niveau():
    view = BossBestiaryView(1, list_definitions(), victories=None)
    levels = [b.level for b in view.pages]
    assert levels == sorted(levels) and view.counter.label == f"1 / {len(levels)}"
