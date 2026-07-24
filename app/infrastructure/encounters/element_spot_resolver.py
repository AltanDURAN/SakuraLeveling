"""Résolution de l'élément (et du spot) au spawn d'un monstre.

Un monstre spawne dans un élément choisi ainsi :
  candidats = éléments dont la ZONE a un spot disponible à l'heure courante
              (time = always/day/night, réf Europe/Paris)
              ∩ éléments que le MONSTRE peut prendre (poids > 0 ; s'il n'a
                aucun poids défini, il hérite de tous les éléments de la zone).
  proba = poids du monstre pour l'élément, sinon poids global
          (element_spawn_weights.json).
Puis on renvoie (element, spot) — le spot porte le décor du spawn.

Fallback : zone sans spots → (None, None) → l'appelant retombe sur l'ancien
comportement (tirage global + décor de zone + placement auto).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.infrastructure.encounters import farm_zone_loader, mob_placement_loader
from app.infrastructure.elements.element_spawn_weight_loader import get_spawn_weights

_PARIS = ZoneInfo("Europe/Paris")


def _is_day(now: datetime | None = None) -> bool:
    """Jour = 6h ≤ heure < 18h (Europe/Paris)."""
    now = now or datetime.now(_PARIS)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_PARIS)
    hour = now.astimezone(_PARIS).hour
    return 6 <= hour < 18


def _time_ok(time_window: str, day: bool) -> bool:
    tw = (time_window or "always").strip().lower()
    if tw == "day":
        return day
    if tw == "night":
        return not day
    return True


def resolve_spawn(
    channel_id: int,
    mob_code: str | None,
    rng=None,
    now: datetime | None = None,
) -> tuple[str | None, dict | None]:
    """Renvoie (element, spot) ou (None, None) si la zone n'a pas de spot
    exploitable (→ fallback appelant)."""
    import random as _random

    spots = farm_zone_loader.get_spots(channel_id)
    if not spots:
        return None, None

    day = _is_day(now)
    mob_weights = mob_placement_loader.get_element_weights(mob_code)
    global_weights = get_spawn_weights()

    candidates: list[str] = []
    weights: list[int] = []
    for spot in spots:
        elem = str(spot.get("element", "")).strip().lower()
        if not elem or not _time_ok(spot.get("time", "always"), day):
            continue
        if mob_weights:
            w = mob_weights.get(elem, 0)
            if w <= 0:
                continue
        else:
            # Monstre sans poids défini : hérite de l'élément avec le poids global.
            w = global_weights.get(elem, 1)
            if w <= 0:
                w = 1
        candidates.append(elem)
        weights.append(w)

    if not candidates:
        return None, None

    picker = rng or _random
    element = picker.choices(candidates, weights=weights, k=1)[0]
    return element, farm_zone_loader.get_spot(channel_id, element)
