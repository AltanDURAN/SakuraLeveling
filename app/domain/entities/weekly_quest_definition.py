"""Définition statique d'une quête hebdomadaire."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WeeklyQuestDefinition:
    code: str
    name: str
    description: str
    tier: str  # "easy" | "medium" | "hard"

    # Type d'objectif (ce qui incrémente le compteur). V1 supportés :
    #   "kill_family"     : target=family,   value=N kills
    #   "kill_total"      : target="",       value=N kills
    #   "duel_win"        : target="",       value=N victoires
    #   "craft_any"       : target="",       value=N crafts
    #   "gather_count"    : target="",       value=N récoltes
    #   "gold_earned"     : target="",       value=N or gagnés via combats
    #   "boss_damage"     : target="",       value=N dégâts au world boss
    #   "daily_streak"    : target="",       value=streak min à atteindre
    objective_type: str
    objective_target: str
    objective_quantity: int

    reward_gold: int
    reward_xp: int
    # Liste de tuples (item_code, quantity) — JSON la stocke en list[list[...]]
    reward_items: list = field(default_factory=list)
