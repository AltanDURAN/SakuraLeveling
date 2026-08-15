from __future__ import annotations

from collections.abc import Iterable

from app.domain.value_objects.status_effect_bonuses import StatusEffectBonuses


class StatusEffectService:
    """Agrège les multiplicateurs des effets temporaires actifs.

    Les effets se cumulent MULTIPLICATIVEMENT : buff +10% (×1.1) puis debuff ÷2
    (×0.5) → ×0.55. Bornage doux pour éviter les extrêmes (0.1 .. 5.0)."""

    MIN_MULT = 0.1
    MAX_MULT = 5.0

    def aggregate(self, multipliers: Iterable[float]) -> StatusEffectBonuses:
        total = 1.0
        for m in multipliers:
            total *= float(m)
        total = max(self.MIN_MULT, min(self.MAX_MULT, total))
        return StatusEffectBonuses(all_stats_multiplier=total)
