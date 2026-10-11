"""Calcul des stats — SAISON 1.

Le modèle a entièrement changé : un socle de trois stats de base monté par des
POINTS DE STATS, et des bonus en POURCENTAGE de ce socle. Ces tests verrouillent
les propriétés qui justifient la refonte, en particulier celle-ci : **un objet
de fin de jeu ne doit presque rien apporter à un débutant**.
"""

from datetime import datetime, UTC

import pytest

from app.domain.entities.item_definition import ItemDefinition
from app.domain.entities.player import Player
from app.domain.entities.player_equipment_item import PlayerEquipmentItem
from app.domain.entities.player_profile import PlayerProfile
from app.domain.entities.player_progression import PlayerProgression
from app.domain.entities.player_resources import PlayerResources
from app.domain.services.stats_service import (
    BASE_CRIT_CHANCE,
    BASE_SPEED,
    MAX_PERCENT_BONUS,
    StatsService,
)
from app.domain.value_objects.base_stats import (
    ATTACK_PER_POINT,
    MAX_HP_PER_POINT,
    START_ATTACK,
    START_DEFENSE,
    START_MAX_HP,
    BaseStats,
)
from app.domain.value_objects.skill_bonuses import SkillBonuses

NOW = datetime.now(UTC)


def build_profile(
    level: int = 1,
    points_attack: int = 0,
    points_defense: int = 0,
    points_max_hp: int = 0,
    stat_points: int = 0,
) -> PlayerProfile:
    return PlayerProfile(
        player=Player(
            id=1, discord_id=1, username="u", display_name="U",
            created_at=NOW, updated_at=NOW, last_seen_at=NOW,
        ),
        progression=PlayerProgression(
            player_id=1, level=level, xp=0, skill_points=0,
            created_at=NOW, updated_at=NOW,
            stat_points=stat_points,
            points_attack=points_attack,
            points_defense=points_defense,
            points_max_hp=points_max_hp,
        ),
        resources=PlayerResources(
            player_id=1, gold=0, created_at=NOW, updated_at=NOW,
        ),
    )


def build_item(bonuses: dict, item_id: int = 1) -> PlayerEquipmentItem:
    return PlayerEquipmentItem(
        id=item_id, player_id=1, slot="arme_1",
        item_definition=ItemDefinition(
            id=item_id, code=f"item{item_id}", name=f"Item {item_id}",
            description="", category="arme", rarity="common",
            stackable=False, max_stack=1, sell_price=0, buy_price=0,
            icon="", stat_bonuses=bonuses, equipment_slot="arme",
            requires_two_hands=False, family="",
            created_at=NOW, updated_at=NOW,
        ),
        created_at=NOW, updated_at=NOW,
    )


def stats_of(profile, items=None, **kwargs):
    return StatsService().calculate_player_stats(
        profile=profile, equipped_items=items or [], **kwargs,
    )


# ------------------------------------------------------------------ socle --
def test_un_joueur_neuf_a_le_socle_de_depart():
    s = stats_of(build_profile())
    assert (s.attack, s.defense, s.max_hp) == (
        START_ATTACK, START_DEFENSE, START_MAX_HP,
    )


def test_les_points_de_stats_montent_le_socle():
    s = stats_of(build_profile(points_attack=10, points_max_hp=4))
    assert s.attack == START_ATTACK + 10 * ATTACK_PER_POINT
    assert s.max_hp == START_MAX_HP + 4 * MAX_HP_PER_POINT
    assert s.defense == START_DEFENSE  # rien investi


def test_les_points_non_depenses_ne_donnent_rien():
    """Avoir des points en réserve ne rend pas plus fort — il faut les placer."""
    assert stats_of(build_profile(stat_points=50)).attack == START_ATTACK


def test_base_stats_from_points_est_reversible():
    base = BaseStats.from_points(attack_points=7, defense_points=3, hp_points=5)
    assert base.invested_points == 15


# ------------------------------------------------------- équipement en % --
def test_l_equipement_s_applique_en_pourcentage_du_socle():
    item = build_item({"attack_pct": 50})
    nu = stats_of(build_profile(points_attack=20))
    equipe = stats_of(build_profile(points_attack=20), [item])
    assert equipe.attack == round(nu.attack * 1.5)


def test_LA_propriete_clef_un_item_late_game_ne_cheate_pas_un_debutant():
    """Le cœur de la refonte.

    La même pièce surpuissante donne quelques points à un joueur neuf et des
    dizaines à un vétéran : offrir son stuff à un nouveau ne le propulse plus.
    """
    item = build_item({"attack_pct": 60})

    debutant_nu = stats_of(build_profile())
    debutant = stats_of(build_profile(), [item])
    veteran_nu = stats_of(build_profile(points_attack=90))
    veteran = stats_of(build_profile(points_attack=90), [item])

    gain_debutant = debutant.attack - debutant_nu.attack
    gain_veteran = veteran.attack - veteran_nu.attack

    assert gain_debutant <= 6, "un débutant ne doit gagner qu'une poignée de points"
    assert gain_veteran > 100, "le même objet doit transformer un vétéran"
    assert gain_veteran > 15 * gain_debutant


def test_les_pourcentages_de_plusieurs_pieces_s_additionnent():
    """+20 % et +30 % donnent +50 %, PAS ×1,2×1,3 = +56 %."""
    deux = stats_of(
        build_profile(points_attack=20),
        [build_item({"attack_pct": 20}, 1), build_item({"attack_pct": 30}, 2)],
    )
    socle = stats_of(build_profile(points_attack=20)).attack
    assert deux.attack == round(socle * 1.5)


def test_les_pourcentages_de_l_arbre_s_ajoutent_a_ceux_de_l_equipement():
    profile = build_profile(points_attack=20)
    socle = stats_of(profile).attack
    s = stats_of(
        profile, [build_item({"attack_pct": 20})],
        skill_bonuses=SkillBonuses(atk_percent=0.10),
    )
    assert s.attack == round(socle * 1.30)


def test_le_cumul_de_pourcentages_est_plafonne():
    items = [build_item({"attack_pct": 200}, i) for i in range(1, 5)]
    socle = stats_of(build_profile(points_attack=10)).attack
    s = stats_of(build_profile(points_attack=10), items)
    assert s.attack == round(socle * (1 + MAX_PERCENT_BONUS))


# --------------------------------------------------- stats secondaires --
def test_les_stats_secondaires_partent_de_leur_valeur_de_base():
    s = stats_of(build_profile())
    assert s.speed == BASE_SPEED
    assert s.crit_chance == BASE_CRIT_CHANCE


def test_les_stats_secondaires_se_cumulent_a_PLAT():
    """Pas de pourcentage sur le crit : un « % de % » n'aurait aucun sens."""
    s = stats_of(build_profile(), [build_item({"crit_chance": 7, "speed": 3})])
    assert s.crit_chance == BASE_CRIT_CHANCE + 7
    assert s.speed == BASE_SPEED + 3


def test_les_points_de_stats_ne_touchent_jamais_les_secondaires():
    riche = stats_of(build_profile(points_attack=99))
    neuf = stats_of(build_profile())
    assert riche.speed == neuf.speed
    assert riche.crit_chance == neuf.crit_chance
    assert riche.mana_max == neuf.mana_max


@pytest.mark.parametrize(
    "bonuses, champ, plafond",
    [({"crit_chance": 500}, "crit_chance", 75.0), ({"dodge": 500}, "dodge", 50.0)],
)
def test_les_secondaires_restent_plafonnees(bonuses, champ, plafond):
    assert getattr(stats_of(build_profile(), [build_item(bonuses)]), champ) == plafond


# ------------------------------------------------------------- robustesse --
def test_une_cle_inconnue_est_ignoree_sans_planter():
    """Le contenu est éditable depuis l'admin : une faute de frappe ne doit
    jamais faire planter un combat."""
    s = stats_of(build_profile(), [build_item({"atak_pct": 50, "attack_pct": 10})])
    assert s.attack == round(START_ATTACK * 1.10)


def test_une_valeur_non_numerique_est_ignoree():
    s = stats_of(build_profile(), [build_item({"attack_pct": "beaucoup"})])
    assert s.attack == START_ATTACK


def test_le_mana_est_toujours_reporte():
    """Invariant du projet : aucune reconstruction de Stats ne doit perdre le
    mana (les défauts à 0 l'effaceraient silencieusement)."""
    s = stats_of(build_profile(), [build_item({"mana_max": 40})])
    assert s.mana_max > 0 and s.mana_regeneration > 0


def test_la_forge_multiplie_les_bonus_de_la_piece():
    """Forge sacrée : chaque niveau rajoute une fois les bonus de base."""
    item = build_item({"attack_pct": 10})
    socle = stats_of(build_profile(points_attack=20)).attack
    s = stats_of(
        build_profile(points_attack=20), [item],
        item_levels={item.item_definition.id: 2},
    )
    assert s.attack == round(socle * 1.30)  # 10 % × (1 + 2)
