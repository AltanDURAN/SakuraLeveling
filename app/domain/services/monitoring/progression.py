"""Progression : XP cumulée, projections (« combien de temps le jeu va
durer ») et courbe de référence du design.

Le rythme d'un joueur se mesure en KILLS ÉQUIVALENTS par jour (XP gagnée ÷
XP d'un monstre de son niveau) et non en XP brute : l'XP par monstre monte
avec le niveau, l'XP demandée aussi — projeter l'XP brute de ses derniers
jours donnerait une date fausse (trop proche) dès qu'on change de palier.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache

from app.domain.services.progression_service import (
    LEVEL_CAP,
    XP_PER_KILL_COEF,
    ProgressionService,
    newcomer_xp_multiplier,
)

#: Tranche de niveaux de chaque zone (joueur de référence, cf. CLAUDE.md
#: « Zones de farm ») — S n'est pas encore ouverte.
ZONE_LEVELS: dict[str, tuple[int, int]] = {
    "F": (1, 20), "E": (21, 33), "D": (34, 45), "C": (46, 56),
    "B": (57, 67), "A": (68, 80), "S": (81, 100),
}

MAX_PROJECTION_DAYS = 3650


@lru_cache(maxsize=1)
def _cumulative() -> tuple[int, ...]:
    """XP cumulée nécessaire pour atteindre chaque niveau (index = niveau)."""
    prog = ProgressionService()
    out = [0, 0]
    for level in range(1, LEVEL_CAP):
        out.append(out[-1] + prog.xp_required_for_next_level(level))
    return tuple(out)


def total_xp(level: int, xp: int) -> int:
    """XP gagnée depuis le niveau 1."""
    level = max(1, min(level, LEVEL_CAP))
    return _cumulative()[level] + max(0, xp)


def xp_to_reach(level: int) -> int:
    return _cumulative()[max(1, min(level, LEVEL_CAP))]


def kills_per_day(xp_per_day: float, level: int) -> float:
    """Rythme en kills équivalents (monstres de son niveau) par jour."""
    return xp_per_day / (XP_PER_KILL_COEF * max(1, level))


def project_days(level: int, xp: int, kills_daily: float, target: int = LEVEL_CAP) -> int | None:
    """Jours pour atteindre `target` au rythme `kills_daily` (None : jamais,
    ou plus de 10 ans)."""
    if level >= target:
        return 0
    if kills_daily <= 0:
        return None
    prog = ProgressionService()
    for day in range(1, MAX_PROJECTION_DAYS + 1):
        gained = kills_daily * XP_PER_KILL_COEF * level * newcomer_xp_multiplier(level)
        r = prog.apply_level_up(current_level=level, current_xp=xp, gained_xp=int(gained),
                                current_skill_points=0, current_stat_points=0)
        level, xp = r.level, r.xp
        if level >= target:
            return day
    return None


def reference_curve(minutes_per_day: float, days: int, minutes_per_kill: float = 3.0,
                    quest_xp_at_20: float = 0.0) -> list[int]:
    """Niveau à la fin de chaque jour du joueur de référence qui joue
    `minutes_per_day` (1 combat toutes les `minutes_per_kill`) et fait ses
    quêtes (`quest_xp_at_20` = XP de quêtes par jour au niveau 20, × niveau/20
    comme `quest_reward_service`). Même modèle que `scripts/simulate_season`
    (« zones complètes »)."""
    prog = ProgressionService()
    level, xp = 1, 0
    kills = minutes_per_day / minutes_per_kill
    out = []
    for _ in range(days):
        gained = kills * XP_PER_KILL_COEF * level * newcomer_xp_multiplier(level) + quest_xp_at_20 * level / 20
        r = prog.apply_level_up(current_level=level, current_xp=xp, gained_xp=int(gained),
                                current_skill_points=0, current_stat_points=0)
        level, xp = r.level, r.xp
        out.append(level)
    return out


def day_reaching(curve: Sequence[int], level: int) -> int | None:
    """Premier jour (1 = le premier) où la courbe atteint `level`."""
    return next((i + 1 for i, lv in enumerate(curve) if lv >= level), None)


def zone_for_level(level: int) -> str:
    for rank, (low, high) in ZONE_LEVELS.items():
        if low <= level <= high:
            return rank
    return "S"
