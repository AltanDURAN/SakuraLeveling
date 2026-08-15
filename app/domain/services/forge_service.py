from __future__ import annotations


class ForgeService:
    """Aide UI pour la forge sacrée. Le CALCUL des stats vit dans StatsService
    (contribution d'un item = stats_base × (1 + niveau)) ; ce service ne fournit
    que le cap et l'aperçu du gain par niveau (= les stats de base de l'item)."""

    def is_maxed(self, level: int, max_level: int) -> bool:
        return level >= max_level

    def gain_per_level(self, stat_bonuses: dict | None) -> dict[str, float]:
        """Stats ajoutées à chaque montée de niveau (= stats de base non nulles)."""
        return {
            k: v
            for k, v in (stat_bonuses or {}).items()
            if isinstance(v, (int, float)) and v
        }
