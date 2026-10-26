from __future__ import annotations

from collections.abc import Iterable

from app.domain.services.alchemy_service import STAT_ELIXIRS
from app.domain.value_objects.status_effect_bonuses import StatusEffectBonuses


class StatusEffectService:
    """Agrège les multiplicateurs des effets temporaires actifs.

    Les effets se cumulent MULTIPLICATIVEMENT : buff +10% (×1.1) puis debuff ÷2
    (×0.5) → ×0.55. Bornage doux pour éviter les extrêmes (0.1 .. 5.0)."""

    MIN_MULT = 0.1
    MAX_MULT = 5.0

    def aggregate(self, multipliers: Iterable[float],
                  elixirs: dict[str, float] | None = None) -> StatusEffectBonuses:
        """`elixirs` : {kind: multiplicateur} des élixirs de combat actifs (un
        par effet : ils ne se cumulent pas avec eux-mêmes)."""
        total = 1.0
        for m in multipliers:
            total *= float(m)
        total = max(self.MIN_MULT, min(self.MAX_MULT, total))
        pct = {stat: 0.0 for stat in STAT_ELIXIRS.values()}
        for kind, mult in (elixirs or {}).items():
            if kind in STAT_ELIXIRS:
                pct[STAT_ELIXIRS[kind]] += float(mult) - 1
        return StatusEffectBonuses(
            all_stats_multiplier=total,
            attack_percent=pct["attack"],
            defense_percent=pct["defense"],
            max_hp_percent=pct["max_hp"],
        )
