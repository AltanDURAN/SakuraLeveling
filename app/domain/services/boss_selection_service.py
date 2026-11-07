"""Quel world boss pour la semaine ? (audit d'ouverture, 07/11/2026)

Avant, seul le poids du contenu décidait : le Titan sortait 88 % des semaines,
même contre des joueurs de niveau 100, et dès 60 d'attaque on pouvait tirer un
boss de niveau 100 impossible à entamer. Désormais :

  • chaque boss a son `level` : le niveau de l'équipe pour laquelle il est
    calibré (`scripts/restat_bosses.py`) ;
  • le boss est choisi selon le NIVEAU MÉDIAN des joueurs actifs, à `MARGIN`
    niveaux près : les boss à portée, le plus récent le plus souvent, et jamais
    deux fois de suite le même quand il y a le choix ;
  • sans équipe capable de l'entamer (`team_level`, le 4e meilleur joueur actif,
    sous le plus petit boss), PAS de raid cette semaine : sous le niveau 12, une
    équipe de 4 fait 0 dégât au Titan.
"""

from __future__ import annotations

import random
from statistics import median_low

#: Un boss est à portée `MARGIN` niveaux avant celui pour lequel il est calibré.
MARGIN = 5
#: Taille de l'équipe du calibrage.
TEAM_SIZE = 4
#: Chaque boss plus faible que le plus fort à portée est N fois moins probable.
STEP_DOWN = 3


def server_level(levels: list[int]) -> int:
    """Le niveau médian des joueurs actifs (0 sans joueur actif)."""
    return int(median_low(levels)) if levels else 0


def team_level(levels: list[int]) -> int:
    """Le niveau de l'équipe de 4 la plus forte (celui de son 4e membre)."""
    if not levels:
        return 0
    ranked = sorted(levels, reverse=True)
    return ranked[min(TEAM_SIZE, len(ranked)) - 1]


def within_reach(definitions: list, levels: list[int]) -> list:
    """Les boss à portée du serveur, du plus faible au plus fort. Vide si
    l'équipe la plus forte n'entame même pas le plus faible."""
    ordered = sorted(definitions, key=lambda d: d.level)
    if not ordered or team_level(levels) < ordered[0].level - MARGIN:
        return []
    reach = [d for d in ordered if d.level - MARGIN <= server_level(levels)]
    return reach or ordered[:1]


def pick(definitions: list, levels: list[int], rng: random.Random | None = None,
         previous_code: str = ""):
    """Le boss de la semaine, ou None si le serveur n'est pas prêt."""
    reach = within_reach(definitions, levels)
    if not reach:
        return None
    if len(reach) > 1:
        reach = [d for d in reach if d.code != previous_code] or reach
    weights = [STEP_DOWN ** index for index in range(len(reach))]
    return (rng or random).choices(reach, weights=weights, k=1)[0]
