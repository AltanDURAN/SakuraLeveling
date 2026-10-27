"""Tour solo (`/tour`) — règles pures (27/10/2026, décisions de l'auteur).

  • 100 étages, les MÊMES pour tout le monde (`tower_floors.json`, généré et
    calibré par `scripts/build_tower.py`) : ils couvrent toute la durée du
    jeu — l'étage N est du niveau N, les étages élevés sont du jeu de fin.
    Chaque étage oppose 1 à 4 monstres (combats contre plusieurs ennemis),
    un BOSS tous les 10 étages ;
  • on combat SEUL, à PV et mana PLEINS, sans potion ni élixir (comme les
    épreuves de rang) : la tour mesure le build, pas les réserves ;
  • la progression est PERMANENTE : une défaite ne fait pas redescendre, elle
    coûte seulement le ticket ; tant qu'on gagne, on garde son ticket et on
    enchaîne. Tickets : 1 par jour, +1 avec la case « Confort » de l'arbre
    (`TowerTicketsUseCase`) ;
  • récompense du PREMIER passage de chaque étage, et récompense QUOTIDIENNE
    indexée sur l'étage record (pas sur le niveau du joueur).
"""

from __future__ import annotations

from dataclasses import dataclass, field

TOWER_FLOORS = 100
BOSS_EVERY = 10

#: Valeur d'une victoire contre un monstre de niveau L (cf. restat_mobs) :
#: c'est l'unité des récompenses de la tour.
GOLD_PER_KILL_LEVEL = 3
XP_PER_KILL_LEVEL = 6.25

#: Premier passage d'un étage : l'or de 8 victoires et l'XP de 4 à son
#: niveau ; un boss en vaut 3 fois plus, plus des matériaux de sa famille.
#: Sur les 100 étages : ~150 000 or et ~11 % de l'XP du niveau 100.
FIRST_CLEAR_GOLD_KILLS = 8
FIRST_CLEAR_XP_KILLS = 4
BOSS_REWARD_MULT = 3

#: Récompense du jour : 10 or par étage du record, et des matériaux de fusion
#: de la famille de cet étage (1 + record / 10).
DAILY_GOLD_PER_FLOOR = 10


@dataclass(frozen=True)
class TowerReward:
    gold: int = 0
    xp: int = 0
    #: ((code d'objet, quantité), …) — matériaux de fusion.
    materials: tuple[tuple[str, int], ...] = field(default_factory=tuple)

    @property
    def is_empty(self) -> bool:
        return not (self.gold or self.xp or self.materials)


def floor_level(floor: int) -> int:
    """Niveau des monstres de l'étage `floor` (l'étage N est du niveau N)."""
    return max(1, min(TOWER_FLOORS, int(floor)))


def is_boss_floor(floor: int) -> bool:
    return floor > 0 and floor % BOSS_EVERY == 0


def next_floor(best_floor: int) -> int | None:
    """Étage à tenter après un record `best_floor` (None : tour terminée)."""
    return best_floor + 1 if best_floor < TOWER_FLOORS else None


def boss_materials(floor: int) -> int:
    """Matériaux de la famille du boss au premier passage d'un étage de boss."""
    return 5 + floor // 5


def first_clear_reward(floor: int, material: str | None = None) -> TowerReward:
    """Récompense du premier passage de l'étage `floor` ; `material` = le
    matériau de fusion de la famille du boss (étages de boss)."""
    level = floor_level(floor)
    mult = BOSS_REWARD_MULT if is_boss_floor(floor) else 1
    materials = ((material, boss_materials(floor)),) if material and is_boss_floor(floor) else ()
    return TowerReward(
        gold=round(FIRST_CLEAR_GOLD_KILLS * GOLD_PER_KILL_LEVEL * level * mult),
        xp=round(FIRST_CLEAR_XP_KILLS * XP_PER_KILL_LEVEL * level * mult),
        materials=materials,
    )


def daily_materials(best_floor: int) -> int:
    return 1 + best_floor // 10


def daily_reward(best_floor: int, material: str | None = None) -> TowerReward:
    """Récompense du jour selon l'étage RECORD (rien avant le premier étage) ;
    `material` = le matériau de fusion de la famille de cet étage."""
    if best_floor <= 0:
        return TowerReward()
    materials = ((material, daily_materials(best_floor)),) if material else ()
    return TowerReward(gold=DAILY_GOLD_PER_FLOOR * best_floor, materials=materials)


def enemy_setups(enemies: list[dict], elemental_out: dict | None = None,
                 elemental_in: dict | None = None) -> list:
    """Ennemis d'un étage (`tower_floors.json`) → `EnemySetup` du moteur, dans
    l'ordre de la formation. `elemental_out` / `elemental_in` : {index de
    l'ennemi: {joueur: multiplicateur}}. Le boss y est un boss (immunisé à
    l'exécution, à l'étourdissement et au gel)."""
    from datetime import UTC, datetime

    from app.domain.entities.mob_definition import MobDefinition
    from app.domain.services.mob_ability_service import get_mob_abilities
    from app.domain.services.party_combat_service import EnemySetup

    now = datetime.now(UTC)
    setups = []
    for i, e in enumerate(enemies):
        mob = MobDefinition(
            id=0, code=e["code"], name=e["name"], description="", image_name=e.get("image_name", ""),
            family=e.get("family", ""), max_hp=e["max_hp"], current_hp=e["max_hp"],
            attack=e["attack"], defense=e["defense"], speed=e["speed"],
            crit_chance=e["crit_chance"], crit_damage=e["crit_damage"], dodge=e["dodge"],
            hp_regeneration=0, xp_reward=0, gold_reward=0, spawn_weight=1, loot_table=None,
            created_at=now, updated_at=now, element=e.get("element", ""))
        setups.append(EnemySetup(
            mob=mob, abilities=get_mob_abilities(e["code"]), is_boss=bool(e.get("boss")),
            elemental_out=(elemental_out or {}).get(i, {}), elemental_in=(elemental_in or {}).get(i, {}),
        ))
    return setups
