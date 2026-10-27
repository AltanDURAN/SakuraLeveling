"""Assaut de world boss : le boss, ses gardes, ses phases et son ultime.

Décidé avec l'auteur (27/10/2026, mécaniques A, B et C) :
  A. de vraies PHASES — sous 75 / 50 / 25 % de ses PV, le boss gagne des
     capacités et de l'attaque, annoncées en combat ;
  B. une ATTAQUE ULTIME annoncée — une action de charge, puis un coup énorme
     sur tout le groupe, que le joueur en provocation intercepte seul ;
  C. des GARDES — de vraies cibles à ses côtés, qui le protègent (−50 % de
     dégâts tant qu'il en reste un) : on les abat d'abord, et les dégâts de
     zone touchent le boss au passage. Ils reviennent à chaque assaut.

Une seule source pour le combat réel (`LaunchPartyFightWorldBossUseCase`) et
le calibrage (`scripts/restat_bosses.py`).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from app.domain.entities.mob_definition import MobDefinition
from app.domain.services.party_combat_service import EnemySetup

GUARDED_REDUCTION_PCT = 50


def guard_mob(guard: dict, element: str = "") -> MobDefinition:
    now = datetime.now(UTC)
    hp = int(guard.get("max_hp", 1))
    return MobDefinition(
        id=0, code=guard.get("code", "garde"), name=guard.get("name", "Garde"), description="",
        image_name=guard.get("image_name", ""), family=guard.get("family", ""), max_hp=hp, current_hp=hp,
        attack=int(guard.get("attack", 1)), defense=int(guard.get("defense", 0)),
        speed=int(guard.get("speed", 8)), crit_chance=int(guard.get("crit_chance", 0)),
        crit_damage=int(guard.get("crit_damage", 150)), dodge=int(guard.get("dodge", 0)),
        hp_regeneration=0, xp_reward=0, gold_reward=0, spawn_weight=1, loot_table=None,
        created_at=now, updated_at=now, element=element)


def assault_enemies(boss_mob: MobDefinition, *, phases: list | None = None, ultimate: dict | None = None,
                    guards: list | None = None, immunity: int = 0, heal_per_turn: int = 0,
                    reflect_pct: int = 0, adds: dict | None = None, elemental_out: dict | None = None,
                    elemental_in: dict | None = None, infusion: dict | None = None
                    ) -> tuple[list[EnemySetup], int]:
    """(ennemis dans l'ordre de la formation, index du boss) : les gardes
    de part et d'autre du boss. Les multiplicateurs élémentaires du boss
    valent aussi pour ses gardes (même élément)."""
    elemental = dict(elemental_out=elemental_out or {}, elemental_in=elemental_in or {},
                     infusion=infusion or {})
    boss = EnemySetup(
        mob=boss_mob, is_boss=True, decisive=True, immunity_threshold=immunity,
        heal_per_turn=heal_per_turn, reflect_pct=reflect_pct, adds=adds,
        phases=[dict(ph) for ph in phases or []], ultimate=ultimate,
        guarded_reduction_pct=GUARDED_REDUCTION_PCT if guards else 0, **elemental)
    sides = [EnemySetup(mob=guard_mob(g, boss_mob.element), abilities=dict(g.get("abilities") or {}),
                        guard=True, **elemental) for g in guards or []]
    left, right = sides[: (len(sides) + 1) // 2], sides[(len(sides) + 1) // 2:]
    return [*left, boss, *right], len(left)


def boss_as_mob(boss, attack: int | None = None) -> MobDefinition:
    """L'instance de world boss (PV conservés) en ennemi du moteur."""
    now = datetime.now(UTC)
    base = MobDefinition(
        id=0, code=boss.code, name=boss.name, description="", image_name=boss.image_name or "",
        family="", max_hp=boss.max_hp, current_hp=boss.current_hp, attack=boss.attack,
        defense=boss.defense, speed=boss.speed, crit_chance=boss.crit_chance,
        crit_damage=boss.crit_damage, dodge=boss.dodge, hp_regeneration=0, xp_reward=0,
        gold_reward=0, spawn_weight=1, loot_table=None, created_at=now, updated_at=now,
        element=boss.element or "")
    return replace(base, attack=attack) if attack is not None else base
