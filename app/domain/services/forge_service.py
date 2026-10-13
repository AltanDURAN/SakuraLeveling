from __future__ import annotations

from app.domain.services.item_upgrade_service import BONUS_PER_LEVEL


class ForgeService:
    """Aide UI pour la forge sacrée. Le CALCUL des stats vit dans StatsService
    (contribution d'un item = stats_base × (1 + 10 % × niveau), cf.
    item_upgrade_service) ; ce service ne fournit que le cap et l'aperçu du
    gain par niveau (= 10 % des stats de base de l'item)."""

    def is_maxed(self, level: int, max_level: int) -> bool:
        return level >= max_level

    def gain_per_level(self, stat_bonuses: dict | None) -> dict[str, float]:
        """Stats ajoutées à chaque montée de niveau (10 % des stats de base)."""
        out: dict[str, float] = {}
        for k, v in (stat_bonuses or {}).items():
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not v:
                continue
            gain = round(v * BONUS_PER_LEVEL, 1)
            out[k] = int(gain) if float(gain).is_integer() else gain
        return out
