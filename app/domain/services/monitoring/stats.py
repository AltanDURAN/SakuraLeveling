"""Petites statistiques robustes (médiane, centiles, Gini, écart à la norme)."""

from __future__ import annotations

import math
from collections.abc import Sequence


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def percentile(values: Sequence[float], p: float) -> float:
    """Centile `p` (0-100), interpolation linéaire ; 0 sur une liste vide."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    k = (len(ordered) - 1) * max(0.0, min(100.0, p)) / 100
    low = math.floor(k)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (k - low)


def median(values: Sequence[float]) -> float:
    return percentile(values, 50)


def percentile_rank(values: Sequence[float], x: float) -> float:
    """Part (0-100) des valeurs strictement en dessous de `x`, les ex aequo
    comptant pour moitié : le meilleur d'un groupe de 10 est à 95, pas 100."""
    if not values:
        return 0.0
    below = sum(1 for v in values if v < x)
    equal = sum(1 for v in values if v == x)
    return 100 * (below + equal / 2) / len(values)


def gini(values: Sequence[float]) -> float:
    """Indice de Gini (0 = tout le monde a pareil, 1 = un seul a tout). Les
    joueurs sans or comptent : ce sont eux qui font la concentration."""
    data = sorted(max(0, v) for v in values)
    n = len(data)
    if n == 0 or sum(data) == 0:
        return 0.0
    cum = sum((i + 1) * v for i, v in enumerate(data))
    return (2 * cum) / (n * sum(data)) - (n + 1) / n


def robust_z(x: float, values: Sequence[float]) -> float:
    """Écart à la médiane en « MAD » (insensible aux extrêmes, contrairement à
    l'écart-type : un seul tricheur ne cache pas un second). 0 si pas assez
    de données ou aucune dispersion."""
    if len(values) < 4:
        return 0.0
    med = median(values)
    mad = median([abs(v - med) for v in values])
    if mad == 0:
        spread = mean([abs(v - med) for v in values])
        return 0.0 if spread == 0 else (x - med) / (1.2533 * spread)
    return (x - med) / (1.4826 * mad)


def share(part: float, whole: float) -> float:
    return 0.0 if not whole else part / whole
