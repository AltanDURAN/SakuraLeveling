"""Récompense quotidienne (/daily) — SAISON 1.

Décision d'octobre 2026, simulée sur une saison complète :

  • l'or est INDEXÉ SUR LE NIVEAU (`GOLD_PER_LEVEL` × niveau), comme les
    quêtes : le daily vaut environ une journée de combats, un bonus de
    présence et non un salaire. Avant (100 × série, sans plafond), il pesait
    84 % de tout l'or du jeu — 36 500 or/jour à J365 contre 3 000 en combat —
    et l'écart entre un ancien et un nouveau ne se refermait jamais ;
  • la SÉRIE ajoute +3 % par jour, plafonnée à +90 % (30 jours) ;
  • c'est désormais une vraie série : chaque jour manqué la DIVISE PAR DEUX
    (au lieu de tout perdre — trop punitif pour un jeu Discord) ;
  • les paliers de série (7, 30, 100 jours) donnent des TITRES à effets
    faibles (titles.json, condition `daily_streak`), jamais d'objets.
"""

from __future__ import annotations

from datetime import datetime, timedelta, UTC

GOLD_PER_LEVEL = 20
STREAK_BONUS_PCT_PER_DAY = 3
STREAK_BONUS_CAP_DAYS = 30


def streak_bonus_pct(streak: int) -> int:
    return STREAK_BONUS_PCT_PER_DAY * max(0, min(streak, STREAK_BONUS_CAP_DAYS))


def daily_gold(level: int, streak: int) -> int:
    """Or du /daily pour un joueur de ce niveau avec cette série (après claim)."""
    base = GOLD_PER_LEVEL * max(1, level)
    return round(base * (1 + streak_bonus_pct(streak) / 100))


def missed_days(next_available_at: datetime | None, now: datetime) -> int:
    """Jours entiers manqués : le daily s'ouvre à `next_available_at` (minuit
    Paris) et reste réclamable 24 h ; chaque journée complète passée au-delà
    est un jour manqué."""
    if next_available_at is None:
        return 0
    if next_available_at.tzinfo is None:
        next_available_at = next_available_at.replace(tzinfo=UTC)
    late = now - next_available_at
    return max(0, int(late // timedelta(days=1)))


def streak_after_absence(streak: int, missed: int) -> int:
    """Chaque jour manqué divise la série par deux (arrondi inférieur)."""
    for _ in range(min(max(0, missed), 32)):
        streak //= 2
    return streak
