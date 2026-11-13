"""Les messages qui grossissent avec le jeu tiennent dans les limites de
Discord (revue du 13/11/2026, après le plantage de `/titre` en production).

Un embed refusé, c'est tout le message qui disparaît : la victoire d'un raid
jamais annoncée, un brouillon d'échange bloqué. Chaque constructeur est appelé
ici avec le pire cas réaliste d'une fin de saison."""

from datetime import UTC, datetime, timedelta

import discord
import pytest

from app.application.use_cases.create_trade import MAX_LOTS_PER_SIDE
from app.application.use_cases.fuse_gear import FusionCandidate
from app.application.use_cases.world_boss import BossRewardEntry
from app.bot.embeds import limits
from app.bot.embeds.event_embeds import girl_result_embed
from app.bot.embeds.trade_embeds import build_trade_embed
from app.bot.embeds.world_boss_embeds import build_boss_defeated_embed, build_boss_escaped_embed
from app.bot.views.fusion_view import menu_order
from app.bot.views.trade_draft_view import TradeDraft, build_draft_embed
from app.domain.entities.trade import Trade, TradeItemOffer, TradeSide, TradeStatus
from app.domain.entities.world_boss import WorldBoss

LONG = "W" * 32             # le plus long pseudo que Discord accepte


def check(embed: discord.Embed) -> None:
    assert len(embed) <= limits.EMBED_MAX
    assert len(embed.fields) <= 25
    assert len(embed.description or "") <= limits.DESCRIPTION_MAX
    for field in embed.fields:
        assert len(field.name) <= 256 and 0 < len(field.value) <= limits.FIELD_VALUE_MAX


# ------------------------------------------------------------- les outils --
def test_fit_lines_compte_ce_qu_il_ne_montre_pas():
    lines = [f"ligne {i:03d} " + "x" * 40 for i in range(100)]
    text = limits.fit_lines(lines, budget=500)
    assert len(text) <= 500
    shown = text.count("ligne ")
    assert text.endswith(f"… et {100 - shown} de plus") and 0 < shown < 100
    assert limits.fit_lines(lines[:3], budget=500) == "\n".join(lines[:3])      # rien de coupé : rien d'ajouté


def test_add_lines_decoupe_en_champs_et_borne_leur_nombre():
    embed = discord.Embed()
    lines = [f"{i} " + "y" * 60 for i in range(200)]
    limits.add_lines(embed, "Liste", lines, max_fields=3)
    assert [f.name for f in embed.fields] == ["Liste", "Liste (suite)", "Liste (suite)"]
    check(embed)
    assert "de plus" in embed.fields[-1].value
    shown = sum(f.value.count("\n") + 1 for f in embed.fields) - 1
    assert embed.fields[-1].value.endswith(f"… et {200 - shown} de plus")

    empty = discord.Embed()
    limits.add_lines(empty, "Liste", [], empty="_Rien_")
    assert empty.fields[0].value == "_Rien_"


# ------------------------------------------------------------ world boss --
def _boss() -> WorldBoss:
    fields = {name: 0 for name in WorldBoss.__dataclass_fields__}
    fields.update(id=1, code="slime_titan", name="Titan Visqueux", status="defeated", element="feu",
                  max_hp=5000, current_hp=0)
    known = {k: v for k, v in fields.items() if k in WorldBoss.__dataclass_fields__}
    return WorldBoss(**known)


@pytest.mark.parametrize("players", [1, 14, 30, 60])
def test_la_victoire_du_raid_s_annonce_quel_que_soit_le_nombre_de_joueurs(players):
    """À 14 participants, le champ des récompenses dépassait 1 024 caractères
    et Discord refusait le message de victoire."""
    rewards = [BossRewardEntry(player_id=i, display_name=LONG, role="participant", gold=1_234_567, xp=987_654,
                               items=[("potion_soin", 3), ("ecaille_de_dragon", 12)]) for i in range(players)]
    names = {"potion_soin": "Potion de soin", "ecaille_de_dragon": "Écaille de dragon"}
    embed = build_boss_defeated_embed(_boss(), rewards, names)
    check(embed)
    text = "\n".join(f.value for f in embed.fields)
    assert "Potion de soin" in text and "potion_soin" not in text            # jamais un code d'objet
    assert "1 234 567 or" in text
    check(build_boss_escaped_embed(_boss(), rewards))


# ---------------------------------------------------------------- échange --
def _trade(lots: int) -> Trade:
    items = [TradeItemOffer(f"carte_{i}", f"Carte — Le Seigneur de Guerre Gobelin n°{i} ✨", 99, side)
             for side in (TradeSide.INITIATOR, TradeSide.TARGET) for i in range(lots)]
    return Trade(id=3, initiator_player_id=1, initiator_discord_id=11, initiator_display_name=LONG,
                 target_player_id=2, target_discord_id=22, target_display_name=LONG, status=TradeStatus.PENDING,
                 initiator_gold_offered=999_999_999, target_gold_offered=999_999_999, items=items,
                 expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=5))


def test_un_echange_au_plafond_de_lots_s_affiche_en_entier():
    embed = build_trade_embed(_trade(MAX_LOTS_PER_SIDE))
    check(embed)
    text = "\n".join(f.value for f in embed.fields)
    for i in range(MAX_LOTS_PER_SIDE):                     # tout ce qui s'échange est visible
        assert text.count(f"n°{i} ✨") == 2
    assert "de plus" not in text


def test_le_brouillon_refuse_un_lot_de_trop_et_le_dit():
    draft = TradeDraft()
    for i in range(MAX_LOTS_PER_SIDE):
        code = f"objet_{i}"
        draft.labels[code] = f"Objet au nom plutôt long numéro {i} pour le pire cas"
        assert draft.add_offered_item(code, 5)
        assert draft.add_requested_item(code, 5)
    assert draft.add_offered_item("objet_0", 2)            # un lot déjà là : la quantité monte
    assert not draft.add_offered_item("de_trop", 1)
    assert len(draft.offered_items) == MAX_LOTS_PER_SIDE and "au plus" in draft.notice

    draft.offered_gold = draft.requested_gold = 999_999_999
    embed = build_draft_embed(draft, LONG, LONG)
    check(embed)
    assert "au plus" in embed.description


# ----------------------------------------------------------- petite fille --
def test_le_sort_de_la_petite_fille_liste_tout_le_monde():
    lines = [f"😈 **{LONG}** a aidé : il perd **1 234 567** or et la moitié de ses PV." for _ in range(45)]
    embed = girl_result_embed(True, lines)
    check(embed)
    shown = sum(f.value.count(LONG) for f in embed.fields)
    assert shown > 30                                                 # plus de coupe silencieuse à 20
    assert embed.fields[-1].value.endswith(f"… et {45 - shown} autre(s) participant(s)")   # le reste est compté
    check(girl_result_embed(False, []))


# ----------------------------------------------------------------- fusion --
def test_le_menu_de_fusion_montre_d_abord_ce_qui_est_pret():
    """Un menu Discord a 25 options : triées par catégorie, les têtes et les
    corps prêts à fusionner d'un joueur à plus de 25 lots restaient hors menu."""
    waiting = [FusionCandidate(f"arme_{i}", f"Arme {i:02d}", "arme", "common", 1) for i in range(30)]
    ready = [FusionCandidate("casque", "Casque", "tete", "rare", 2),
             FusionCandidate("cuirasse", "Cuirasse", "corps", "epic", 3)]
    capped = [FusionCandidate("relique", "Relique", "accessoire", "legendary", 2)]   # ne se fusionne plus
    menu = menu_order(waiting + ready + capped)[:25]
    assert menu[:2] == ready
    assert capped[0] not in menu[:2]
