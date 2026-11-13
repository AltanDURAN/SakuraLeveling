"""`/titre` tient dans les limites de Discord quel que soit le nombre de titres.

Le 11/11/2026, la commande a planté en production (« Embed size exceeds
maximum size of 6000 ») : avec les 83 titres du jeu, la liste des titres à
débloquer dépassait la limite pour presque tous les joueurs (de 2 à 13 titres
débloqués). C'est désormais un livre à pages."""

import re

import pytest

from app.bot.cogs.title_cog import HOLDER_NAME_MAX, TitleProgress
from app.bot.embeds.title_embeds import build_title_pages, locked_sections
from app.infrastructure.db.repositories.player_kill_repository import PlayerKillRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_title_repository import PlayerTitleRepository
from app.infrastructure.titles.title_loader import list_definitions
from tests.infrastructure.test_use_consumable import session  # noqa: F401

LONG_NAME = "X" * 32          # le plus long pseudo que Discord accepte


def _check_limits(pages) -> None:
    for embed in pages:
        assert len(embed) <= 6000
        assert len(embed.fields) <= 25
        assert len(embed.title) <= 256 and len(embed.description) <= 4096
        for field in embed.fields:
            assert len(field.name) <= 256 and 0 < len(field.value) <= 1024


def _worst_label(title) -> str:
    """La ligne la plus longue qu'un titre puisse afficher."""
    if title.condition_type == "kills_record":
        return (f"détenu par **{LONG_NAME[:HOLDER_NAME_MAX]}** (**123 456** monstres vaincus) · "
                "toi : **123 455**, il t'en manque **123 456**")
    return f"détenu par **{LONG_NAME[:HOLDER_NAME_MAX]}** · sois le meilleur contributeur du prochain boss vaincu"


@pytest.mark.parametrize("unlocked_count", [0, 1, 2, 5, 10, 13, 40, 83])
def test_chaque_page_tient_dans_les_limites_de_discord(unlocked_count):
    definitions = list_definitions()
    unlocked, locked = definitions[:unlocked_count], definitions[unlocked_count:]
    labels = {t.code: _worst_label(t) for t in locked}
    pages = build_title_pages(LONG_NAME, unlocked, locked, labels,
                              active_code=unlocked[0].code if unlocked else None, total=len(definitions))
    assert pages
    _check_limits(pages)
    # Rien n'est coupé en silence : chaque titre du jeu figure dans le livre.
    text = "\n".join(f.value for embed in pages for f in embed.fields)
    for title in definitions:
        assert f"**{title.name}**" in text, title.code


def test_un_contenu_deux_fois_plus_gros_tient_toujours():
    """Chaque monstre ajouté apporte un titre : le livre ajoute des pages."""
    definitions = list_definitions() * 3
    pages = build_title_pages("Joueur", [], definitions, {t.code: _worst_label(t) for t in definitions})
    _check_limits(pages)
    assert len(pages) > 3


def test_le_plus_proche_vient_d_abord_dans_sa_section():
    hunters = [t for t in list_definitions() if t.condition_type == "kills_mob"][:4]
    closeness = {hunters[0].code: 0.1, hunters[1].code: 0.9, hunters[2].code: 0.0, hunters[3].code: 0.5}
    (_, lines), = locked_sections(hunters, {t.code: "x" for t in hunters}, closeness)
    order = [next(t.code for t in hunters if f"**{t.name}**" in line) for line in lines]
    assert order == [hunters[1].code, hunters[3].code, hunters[0].code, hunters[2].code]


def test_la_progression_se_lit_en_clair_pour_chaque_type_de_titre(session):
    profile = PlayerRepository(session).get_or_create_by_discord_id(1, "u", "Joueur")
    other = PlayerRepository(session).get_or_create_by_discord_id(2, "v", LONG_NAME)
    kills = PlayerKillRepository(session)
    for _ in range(3):
        kills.increment(profile.player.id, "slime")
    titles = PlayerTitleRepository(session)
    for title in list_definitions():
        if getattr(title, "exclusive", False):
            titles.unlock(other.player.id, title.code)             # un autre les détient
    session.commit()

    progress = TitleProgress(session, PlayerRepository(session).get_by_discord_id(1))
    seen_types = set()
    for title in list_definitions():
        label, closeness = progress.of(title)
        seen_types.add(title.condition_type)
        assert 0.0 <= closeness <= 1.0
        assert label and len(label) < 200
        # Ni terme technique, ni code, ni pseudo interminable.
        assert "Condition" not in label and title.condition_type not in label
        assert not re.search(r"[a-z]+_[a-z]+", label.replace("_à découvrir_", "")) or "`/" in label, label
        assert LONG_NAME not in label
    assert len(seen_types) >= 12

    slime = next(t for t in list_definitions() if t.condition_type == "kills_mob" and t.condition_target == "slime")
    assert progress.of(slime) == (f"**3/{slime.condition_value}** victoires", 3 / slime.condition_value)
