"""Alchimie d'Elna — règles pures (26/10/2026, demande de l'auteur).

Elna ne fusionne plus d'équipement (Borak fait tout) : elle prépare les
POTIONS. Le joueur fournit les ingrédients — les matériaux de FAMILLE des
monstres, déjà utilisés par la fusion (d'où un vrai choix : fusionner ou se
soigner, et un marché à la brocante) — et paie la confection en or, indexée
sur son niveau (puits d'or). Chaque zone a sa spécialité : soins à la
Clairière (gelée, dent), mana et récupération au Cimetière (fragment d'âme),
élixirs de combat au Berceau (cœur corrompu).

Effets d'un consommable (`stat_bonuses` de l'objet) :
  • `heal_percent` / `mana_percent` : rend X % des PV / du mana max ;
  • `elixir` : effet temporaire `kind` (attack / defense / max_hp en %,
    regen = multiplicateur de la régénération hors combat) pendant `minutes`.

Règles des élixirs :
  • un MÊME effet ne se cumule jamais : en reboire un renouvelle sa durée ;
  • des effets DIFFÉRENTS s'additionnent (+ATK, +DEF, +PV…) ;
  • ils ne comptent qu'en combat de zone et au world boss — PAS dans les
    épreuves de rang, les défis ni le rang affiché (sinon une course à l'or).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime

EFFECT_HEAL = "heal_percent"
EFFECT_MANA = "mana_percent"
EFFECT_ELIXIR = "elixir"

#: Effet d'élixir → `kind` de `player_status_effects`.
ELIXIR_STATUS_KINDS: dict[str, str] = {
    "attack": "elixir_attack",
    "defense": "elixir_defense",
    "max_hp": "elixir_max_hp",
    "regen": "elixir_regen",
}
ELIXIR_LABELS: dict[str, str] = {
    "attack": "💪 Force", "defense": "🛡️ Garde", "max_hp": "❤️ Vitalité",
    "regen": "🌿 Récupération",
}
#: Stat (pool de % de StatsService) de chaque élixir de combat.
STAT_ELIXIRS: dict[str, str] = {
    "elixir_attack": "attack", "elixir_defense": "defense", "elixir_max_hp": "max_hp",
}
REGEN_KIND = "elixir_regen"


@dataclass(frozen=True)
class Recipe:
    item_code: str
    ingredients: tuple[tuple[str, int], ...]   # (code du matériau, quantité)
    fee_per_level: int                         # or × niveau, par potion


@dataclass(frozen=True)
class ElixirEffect:
    kind: str           # attack | defense | max_hp | regen
    value: float        # % (stats) ou multiplicateur (regen)
    minutes: int

    @property
    def status_kind(self) -> str:
        return ELIXIR_STATUS_KINDS[self.kind]

    @property
    def multiplier(self) -> float:
        """Valeur stockée dans `player_status_effects.multiplier`."""
        return self.value if self.kind == "regen" else 1 + self.value / 100


def elixir_of(stat_bonuses: dict | None) -> ElixirEffect | None:
    data = stat_bonuses or {}
    if data.get("effect") != EFFECT_ELIXIR or data.get("kind") not in ELIXIR_STATUS_KINDS:
        return None
    return ElixirEffect(str(data["kind"]), float(data.get("value", 0)), int(data.get("minutes", 60)))


def effect_text(stat_bonuses: dict | None) -> str:
    """Texte joueur de l'effet d'un consommable."""
    data = stat_bonuses or {}
    effect, value = data.get("effect"), data.get("value", 0)
    if effect == EFFECT_HEAL:
        return f"rend {value} % de tes PV"
    if effect == EFFECT_MANA:
        return f"rend {value} % de ton mana"
    elixir = elixir_of(data)
    if elixir is None:
        return "effet inconnu"
    duration = f"{elixir.minutes // 60} h" if elixir.minutes % 60 == 0 else f"{elixir.minutes} min"
    if elixir.kind == "regen":
        return f"régénération des PV et du mana ×{elixir.value:g} hors combat pendant {duration}"
    stat = {"attack": "d'attaque", "defense": "de défense", "max_hp": "de PV max"}[elixir.kind]
    return f"+{elixir.value:g} % {stat} pendant {duration} (combats de zone et world boss)"


def brew_fee(recipe: Recipe, level: int, quantity: int = 1, discount_pct: int = 0) -> int:
    """Or demandé par Elna pour `quantity` potions, remise de maîtrise déduite."""
    raw = recipe.fee_per_level * max(1, int(level)) * max(0, int(quantity))
    return max(0, round(raw * (1 - max(0, discount_pct) / 100)))


def max_brewable(recipe: Recipe, owned: dict[str, int], gold: int, level: int,
                 discount_pct: int = 0) -> int:
    """Combien de potions le joueur peut faire préparer tout de suite."""
    by_ingredients = min((owned.get(code, 0) // qty for code, qty in recipe.ingredients if qty > 0),
                         default=0)
    unit = brew_fee(recipe, level, 1, discount_pct)
    by_gold = gold // unit if unit else by_ingredients
    return max(0, min(by_ingredients, by_gold))


def bonus_potions(quantity: int, bonus_pct: int, rng: random.Random | None = None) -> int:
    """Potions offertes par une alchimiste chevronnée : `bonus_pct` % de
    chance par potion préparée."""
    if bonus_pct <= 0:
        return 0
    rng = rng or random
    return sum(1 for _ in range(max(0, quantity)) if rng.random() < bonus_pct / 100)


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def boosted_seconds(last_updated_at: datetime, now: datetime,
                    boosts=()) -> float:
    """Secondes de régénération écoulées, élixir de récupération compris :
    chaque fenêtre (début, fin, ×M) compte M fois sur son recouvrement avec
    [dernière mise à jour, maintenant]."""
    last, now = _aware(last_updated_at), _aware(now)
    total = (now - last).total_seconds()
    for start, end, mult in boosts or ():
        overlap = (min(_aware(end), now) - max(_aware(start), last)).total_seconds()
        if overlap > 0 and mult > 1:
            total += overlap * (mult - 1)
    return total
