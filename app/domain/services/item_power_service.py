"""Puissance d'une PIÈCE d'équipement — SAISON 1.

Les bonus d'équipement sont désormais des POURCENTAGES du socle du joueur. La
même pièce ne vaut donc pas la même chose selon qui la porte : +20 % d'attaque
ne veut rien dire dans l'absolu.

On la mesure contre un joueur de RÉFÉRENCE pris au niveau requis de la pièce —
c'est-à-dire le joueur à qui elle est destinée. Une arme de niveau 70 est
évaluée sur un personnage de niveau 70, pas sur un débutant.

Sert à fixer le prix du travail des artisans et le palier de maîtrise requis.
"""

from __future__ import annotations

from app.domain.services.power_score_service import PowerScoreService
from app.domain.value_objects.base_stats import (
    ATTACK_PER_POINT,
    DEFENSE_PER_POINT,
    MAX_HP_PER_POINT,
    START_ATTACK,
    START_DEFENSE,
    START_MAX_HP,
)
from app.domain.value_objects.stats import Stats

#: Valeurs de départ des stats secondaires (miroir de StatsService).
_BASE_SECONDARY = {
    "speed": 5, "crit_chance": 5.0, "crit_damage": 150.0, "dodge": 0.0,
    "hp_regeneration": 5, "mana_max": 100, "mana_regeneration": 5,
}

PERCENT_KEYS = {"attack_pct": "attack", "defense_pct": "defense", "max_hp_pct": "max_hp"}


def reference_stats(level: int) -> Stats:
    """Joueur de référence à ce niveau, construit sur une répartition ÉQUILIBRÉE.

    Un joueur a `niveau - 1` points de stats ; on en met un tiers dans chacune
    des trois stats de base. C'est l'hypothèse la plus neutre possible pour
    comparer des objets entre eux.
    """
    points = max(0, level - 1) / 3
    return Stats(
        max_hp=int(START_MAX_HP + MAX_HP_PER_POINT * points),
        attack=int(START_ATTACK + ATTACK_PER_POINT * points),
        defense=int(START_DEFENSE + DEFENSE_PER_POINT * points),
        speed=_BASE_SECONDARY["speed"],
        crit_chance=_BASE_SECONDARY["crit_chance"],
        crit_damage=_BASE_SECONDARY["crit_damage"],
        dodge=_BASE_SECONDARY["dodge"],
        hp_regeneration=_BASE_SECONDARY["hp_regeneration"],
        mana_max=_BASE_SECONDARY["mana_max"],
        mana_regeneration=_BASE_SECONDARY["mana_regeneration"],
    )


class ItemPowerService:
    def __init__(self, power_service: PowerScoreService | None = None) -> None:
        self._power = power_service or PowerScoreService()

    def marginal_power(
        self, stat_bonuses: dict | None, level_requirement: int = 1,
    ) -> int:
        """Ce que la pièce apporte au joueur auquel elle est destinée.

        Toujours ≥ 0 : une pièce à malus net ne peut pas coûter un prix négatif.
        """
        if not stat_bonuses:
            return 0
        base = reference_stats(max(1, level_requirement))
        with_item = self._apply(base, stat_bonuses)
        return max(
            0,
            self._power.calculate_from_stats(with_item)
            - self._power.calculate_from_stats(base),
        )

    @staticmethod
    def _apply(stats: Stats, bonuses: dict) -> Stats:
        """Applique les bonus d'une pièce. Reporte TOUTES les stats — dont le
        mana (invariant : aucune reconstruction de Stats ne doit l'oublier)."""
        values = {
            "max_hp": float(stats.max_hp), "attack": float(stats.attack),
            "defense": float(stats.defense), "speed": float(stats.speed),
            "crit_chance": stats.crit_chance, "crit_damage": stats.crit_damage,
            "dodge": stats.dodge,
            "hp_regeneration": float(stats.hp_regeneration),
            "mana_max": float(stats.mana_max),
            "mana_regeneration": float(stats.mana_regeneration),
        }

        for pct_key, target in PERCENT_KEYS.items():
            raw = bonuses.get(pct_key)
            if raw is None:
                continue
            try:
                values[target] *= 1 + float(raw) / 100.0
            except (TypeError, ValueError):
                continue

        for key in _BASE_SECONDARY:
            raw = bonuses.get(key)
            if raw is None:
                continue
            try:
                values[key] += float(raw)
            except (TypeError, ValueError):
                continue

        return Stats(
            max_hp=max(1, int(values["max_hp"])),
            attack=max(1, int(values["attack"])),
            defense=max(1, int(values["defense"])),
            speed=max(1, int(values["speed"])),
            crit_chance=max(0.0, values["crit_chance"]),
            crit_damage=max(100.0, values["crit_damage"]),
            # Bornée à 99 : à 100 la survie deviendrait infinie et la puissance
            # exploserait.
            dodge=min(99.0, max(0.0, values["dodge"])),
            hp_regeneration=max(0, int(values["hp_regeneration"])),
            mana_max=max(0, int(values["mana_max"])),
            mana_regeneration=max(0, int(values["mana_regeneration"])),
        )
