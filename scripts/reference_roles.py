"""Les TROIS joueurs de rôle (DPS, Tank, Support) — calibrage du contenu de GROUPE.

Le joueur de référence (`app/domain/services/reference_player.py`) reste LA
mesure du contenu SOLO : neutre, équilibré, sans classe. Un contenu de groupe
se juge autrement : un DPS, un tank et un soigneur doivent y faire mieux
ensemble que trois DPS (décision de l'auteur, 25/10/2026). Ce module construit
ces trois joueurs — et un GÉNÉRALISTE (G : classes de base et de jonction,
aucune spécialisation) — à un niveau donné avec les VRAIES règles du jeu
(arbre, seuil de voie et exclusivité des spécialisations, StatsService,
rareté d'équipement, passifs, panoplie) ; les scripts de calibrage et les
tests d'équilibre les font combattre avec le vrai moteur.

Méthode (issue du labo d'équilibrage d'octobre 2026) :
  • points de stats : DPS 60 / 20 / 20 % (ATK / DEF / PV), Tank 15 / 42,5 /
    42,5, Support 45 / 20 / 35 ;
  • arbre : allocation gloutonne selon les priorités du rôle (`WEIGHTS`), en
    regardant quelques cases plus loin, dans les RÈGLES de l'arbre (seuil de
    voie, une seule spécialisation) ; chaque rôle ne vise que les classes qui
    lui servent (`CLASS_OK`) ;
  • équipement : 7 pièces de la rareté attendue au niveau (même courbe que le
    joueur de référence), kit de stats du rôle, 4 passifs de rôle dès
    l'épique, panoplie du type du rôle ;
  • tactique : le Support soigne en « pragmatique ».

Ce sont des joueurs PLAUSIBLES, pas des optimums : ils servent à comparer des
compositions et à calibrer, pas à prédire le meilleur build.
"""

from __future__ import annotations

import functools
import random
import statistics
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from app.domain.entities.item_definition import ItemDefinition
from app.domain.entities.mob_definition import MobDefinition
from app.domain.entities.player import Player
from app.domain.entities.player_equipment_item import PlayerEquipmentItem
from app.domain.entities.player_profile import PlayerProfile
from app.domain.entities.player_progression import PlayerProgression
from app.domain.entities.player_resources import PlayerResources
from app.domain.services.combat_passives import CombatPassives
from app.domain.services.gear_service import PRIMARY_MULTIPLIER, RARITY_ORDER
from app.domain.services.party_combat_service import PartyCombatService
from app.domain.services.reference_player import _gear_rarity_multiplier
from app.domain.services.set_bonus_service import SetBonusService
from app.domain.services.skill_tree_service import SkillTreeService
from app.domain.services.stats_service import StatsService
from app.domain.value_objects.stats import Stats

NOW = datetime.now(UTC)

ROLE_OF = {"D": "dps", "T": "tank", "S": "support", "G": "general"}

#: Priorités de chaque rôle dans l'arbre : poids d'un type d'effet.
WEIGHTS: dict[str, dict[str, float]] = {
    "dps": {"atk_percent": 3, "crit_chance_flat": 2, "crit_damage_flat": 1.2, "speed_flat": 2.5,
            "damage_dealt_percent": 3, "crit_chance_multiplier": 8, "armor_penetration_percent": 3,
            "lifesteal_percent": 1, "hp_max_percent": 0.6, "def_percent": 0.4, "dodge_flat": 0.5},
    "tank": {"def_percent": 3, "hp_max_percent": 3, "damage_taken_reduction_percent": 4,
             "redirect_ally_damage_percent": 5, "taunt_chance_percent": 5, "last_stand": 3,
             "dodge_flat": 1, "team_shield_percent": 2, "atk_percent": 0.5, "speed_flat": 0.5,
             "damage_dealt_percent": 1, "defense_to_attack_percent": 4, "threat_percent": 4},
    "support": {"healer_spell": 8, "team_shield_percent": 5, "heal_buff_percent": 4,
                "heal_received_percent": 2, "speed_per_ally": 1, "hp_max_percent": 1.5,
                "def_percent": 1, "atk_percent": 1.5, "speed_flat": 1.5, "lifesteal_percent": 0.5,
                "team_damage_percent": 4, "ally_heal_on_hit_percent": 3},
}
#: Le généraliste : un peu de tout, mais ni sort de soin, ni aura, ni
#: Rempart, ni Assassin (les spécialisations lui sont fermées de toute façon).
WEIGHTS["general"] = {k: v for role in ("dps", "tank", "support") for k, v in WEIGHTS[role].items()
                      if k not in ("healer_spell", "team_damage_percent", "redirect_ally_damage_percent",
                                   "crit_chance_multiplier")}
WEIGHTS["general"].update({"ally_heal_on_hit_percent": 5, "threat_percent": 3, "damage_dealt_percent": 4})

#: Classes autorisées par rôle (celles de sa voie).
BASE_CLASSES = {"guerrier", "gardien", "clerc"}
CLASS_OK: dict[str, set[str]] = {
    "dps": {"assassin", "combattant", "mage", "vampire", "titan"} | BASE_CLASSES,
    "tank": {"rempart", "titan", "paladin", "combattant"} | BASE_CLASSES,
    "support": {"soigneur", "egide", "paladin"} | BASE_CLASSES,
    "general": {"combattant", "titan", "vampire", "mage", "paladin", "egide"} | BASE_CLASSES,
}

#: Répartition des points de stats (ATK, DEF, PV).
POINTS: dict[str, tuple[float, float, float]] = {
    "dps": (0.6, 0.2, 0.2), "tank": (0.15, 0.425, 0.425), "support": (0.45, 0.2, 0.35),
    "general": (1 / 3, 1 / 3, 1 / 3),
}

#: Stats au COMMUN des 7 pièces portées (grille d'items.json).
KITS: dict[str, list[dict]] = {
    "dps": [{"attack_pct": 8, "crit_chance": 2}, {"attack_pct": 8, "crit_damage": 6},
            {"max_hp_pct": 6, "crit_chance": 2}, {"defense_pct": 6, "max_hp_pct": 6},
            {"crit_damage": 9}, {"crit_chance": 3}, {"speed": 1}],
    "tank": [{"defense_pct": 6, "max_hp_pct": 4}, {"defense_pct": 6, "max_hp_pct": 4},
             {"max_hp_pct": 6, "dodge": 1}, {"defense_pct": 6, "max_hp_pct": 6},
             {"dodge": 2}, {"hp_regeneration": 4}, {"speed": 1}],
    "support": [{"attack_pct": 8, "mana_max": 15}, {"defense_pct": 6, "max_hp_pct": 4},
                {"max_hp_pct": 6, "mana_max": 15}, {"defense_pct": 6, "max_hp_pct": 6},
                {"speed": 1}, {"hp_regeneration": 4}, {"crit_chance": 3}],
    "general": [{"attack_pct": 8, "crit_chance": 2}, {"defense_pct": 6, "max_hp_pct": 4},
                {"max_hp_pct": 6, "crit_chance": 2}, {"defense_pct": 6, "max_hp_pct": 6},
                {"crit_damage": 9}, {"speed": 1}, {"hp_regeneration": 4}],
}
GEAR_PASSIVES: dict[str, list[str]] = {
    "dps": ["first_strike_crit", "double_strike", "rising_fury", "executioner"],
    "tank": ["taunt_guard", "stone_skin", "thorns", "undying"],
    "support": ["healing_hands", "weakening_cry", "anti_heal", "blast_ward"],
    "general": ["double_strike", "stone_skin", "healing_hands", "rising_fury"],
}
PANOPLIE: dict[str, str] = {"dps": "attack", "tank": "defense", "support": "max_hp",
                            "general": "attack"}
TACTIC: dict[str, str] = {"support": "pragmatique"}


@dataclass(frozen=True)
class RoleBuild:
    role: str
    stats: Stats
    passives: CombatPassives
    allocations: dict
    tactic: str | None


@functools.lru_cache(maxsize=1)
def _tree() -> tuple[SkillTreeService, dict[str, list[str]]]:
    from app.infrastructure.skill_tree.skill_tree_loader import get_definition

    definition = get_definition()
    children: dict[str, list[str]] = {}
    for link in definition.links:
        children.setdefault(link.source, []).append(link.target)
    return SkillTreeService(definition), children


def _class_of(node) -> str | None:
    for effect in node.effects:
        if effect.type == "grant_class":
            value = effect.values[0] if effect.values else None
            return value[0] if isinstance(value, list) else value
    return None


def _gain(role: str, node) -> float:
    return sum(WEIGHTS[role].get(e.type, 0.0) for e in node.effects) + 0.05


def _future(role: str, code: str, depth: int = 4, seen: frozenset = frozenset()) -> float:
    """Valeur des meilleures cases que celle-ci ouvre (le glouton voit loin)."""
    svc, children = _tree()
    if depth <= 0:
        return 0.0
    best = 0.0
    for child in children.get(code, []):
        node = svc.definition.get(child)
        if child in seen or node is None:
            continue
        best = max(best, _gain(role, node) * node.max_level
                   + 0.7 * _future(role, child, depth - 1, seen | {child}))
    return best


def allocate(role: str, points: int) -> dict[str, int]:
    """Cases investies par un joueur de ce rôle avec `points` points d'arbre."""
    svc, _ = _tree()
    alloc: dict[str, int] = {}
    while points > 0:
        best, best_value = None, -1.0
        for node in svc.compute_unlockable_skills(alloc, limit=999):
            level = alloc.get(node.code, 0)
            cost = (node.costs or [1] * node.max_level)[level]
            if cost > points or node.node_type == "utilite":
                continue
            cls = _class_of(node)
            if cls and cls not in CLASS_OK[role]:
                continue
            value = _gain(role, node) + 0.7 * _future(role, node.code)
            if value > best_value:
                best, best_value = node, value
        if best is None:
            break
        level = alloc.get(best.code, 0)
        points -= (best.costs or [1] * best.max_level)[level]
        alloc[best.code] = level + 1
    return alloc


def _profile(level: int, role: str) -> PlayerProfile:
    pts = level - 1
    pa, pd, _ = POINTS[role]
    a, d = round(pts * pa), round(pts * pd)
    return PlayerProfile(
        player=Player(id=1, discord_id=1, username="ref", display_name="ref",
                      created_at=NOW, updated_at=NOW, last_seen_at=NOW),
        progression=PlayerProgression(
            player_id=1, level=level, xp=0, skill_points=0, created_at=NOW, updated_at=NOW,
            stat_points=0, points_attack=a, points_defense=d, points_max_hp=pts - a - d),
        resources=PlayerResources(player_id=1, gold=0, created_at=NOW, updated_at=NOW),
    )


def _rarity_for(level: int) -> str | None:
    """Rareté uniforme la plus proche (par défaut) de la rareté moyenne attendue."""
    mult = _gear_rarity_multiplier(level)
    if mult <= 0:
        return None
    best = "common"
    for rarity in RARITY_ORDER[:5]:
        if PRIMARY_MULTIPLIER[rarity] <= mult + 1e-9:
            best = rarity.value
    return best


def _items(role: str, level: int) -> list[PlayerEquipmentItem]:
    rarity = _rarity_for(level)
    if rarity is None:
        return []
    passives = GEAR_PASSIVES[role] if RARITY_ORDER.index(rarity) >= 3 else []
    return [
        PlayerEquipmentItem(
            id=i, player_id=1, slot=f"s{i}",
            item_definition=ItemDefinition(
                id=i, code=f"kit{i}", name=f"kit{i}", description="", category="arme",
                rarity="common", stackable=False, max_stack=1, sell_price=0, buy_price=0,
                icon="", stat_bonuses=stats, equipment_slot="arme", requires_two_hands=False,
                family="", created_at=NOW, updated_at=NOW,
                passive=passives[i] if i < len(passives) else ""),
            created_at=NOW, updated_at=NOW, rarity=rarity, forge_level=0)
        for i, stats in enumerate(KITS[role])
    ]


@functools.lru_cache(maxsize=None)
def build(role: str, level: int) -> RoleBuild:
    """Le joueur de ce rôle à ce niveau (stats, passifs, cases, tactique)."""
    from app.application.services.combat_passives_resolver import with_gear_passives

    svc, _ = _tree()
    items = _items(role, level)
    alloc = allocate(role, level - 1)
    sets = SetBonusService().aggregate(items, PANOPLIE[role]) if items else None
    stats = StatsService().calculate_player_stats(
        profile=_profile(level, role), equipped_items=items,
        skill_bonuses=svc.aggregate_bonuses(alloc), set_bonuses=sets)
    passives = with_gear_passives(svc.combat_passives(alloc), items)
    return RoleBuild(role, stats, passives, alloc, TACTIC.get(role))


def party(compo: str, level: int, stats_hook=None) -> tuple[list[dict], dict, dict]:
    """(équipe, passifs, tactiques) pour PartyCombatService. `compo` = "DTS"…
    `stats_hook(stats, n)` : ajuste les stats (ex. bonus d'équipe du raid)."""
    members, passives, tactics = [], {}, {}
    for i, letter in enumerate(compo):
        b = build(ROLE_OF[letter], level)
        stats = stats_hook(b.stats, len(compo)) if stats_hook else b.stats
        pid = i + 1
        members.append({"player_id": pid, "user_id": pid, "name": f"{letter}{pid}",
                        "avatar_url": "", "stats": stats, "current_hp": stats.max_hp,
                        "max_hp": stats.max_hp, "current_mana": stats.mana_max,
                        "mana_max": stats.mana_max})
        passives[pid] = b.passives
        if b.tactic:
            tactics[pid] = b.tactic
    return members, passives, tactics


def fight(compo: str, level: int, mob: MobDefinition, abilities: dict | None = None,
          n: int = 20, **kw) -> dict:
    """Taux de victoire, actions (médiane), morts moyennes de `compo` contre `mob`."""
    wins, actions, deaths = 0, [], 0
    for seed in range(n):
        random.seed(seed)
        members, passives, tactics = party(compo, level)
        result = PartyCombatService().fight_party_vs_mob(
            members, mob, mob_abilities=abilities or {}, passives_by_player=passives,
            tactics_by_player=tactics, **kw)
        wins += result.victory
        actions.append(result.turns)
        deaths += sum(1 for c in result.contributions if not c.survived)
    return {"win": wins / n, "actions": statistics.median(actions), "deaths": deaths / n}


def with_hp(mob: MobDefinition, hp: int) -> MobDefinition:
    return replace(mob, max_hp=hp, current_hp=hp)


def typical_power(level: int) -> int:
    """Power score d'un joueur TYPIQUE à ce niveau : la médiane des quatre
    profils (DPS, Tank, Support, généraliste). C'est la courbe des rangs
    affichés et des seuils d'épreuve — le joueur de référence, sans classes
    ni vrai arbre, restait ~2 fois plus faible qu'un joueur investi au niveau
    100 (il affichait S+ dès le niveau 70)."""
    from app.domain.services.power_score_service import PowerScoreService

    service = PowerScoreService()
    powers = sorted(service.calculate_from_stats(build(role, level).stats, build(role, level).passives)
                    for role in ("dps", "tank", "support", "general"))
    return round((powers[1] + powers[2]) / 2)


def gate_power(level: int) -> int:
    """Seuil des épreuves de rang : la puissance du GÉNÉRALISTE à ce niveau —
    le profil équilibré. Chacun atteint ainsi chaque rang au niveau prévu ou
    avant (les spécialistes un peu plus tôt)."""
    from app.domain.services.power_score_service import PowerScoreService

    b = build("general", level)
    return PowerScoreService().calculate_from_stats(b.stats, b.passives)
