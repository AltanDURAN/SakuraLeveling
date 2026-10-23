from __future__ import annotations

from app.domain.services.gear_service import FORGE_BONUS_PER_LEVEL as BONUS_PER_LEVEL


class ForgeService:
    """Aide UI pour la forge sacrée. Le CALCUL des stats vit dans
    gear_service (stats × rareté × (1 + 1 % × niveau)) ; ce service ne fournit
    que le cap et l'aperçu du gain par niveau (= 1 % des stats de la pièce)."""

    def is_maxed(self, level: int, max_level: int) -> bool:
        return level >= max_level

    def gain_per_level(self, stat_bonuses: dict | None) -> dict[str, float]:
        """Stats ajoutées à chaque montée de niveau (1 % des stats de la pièce)."""
        out: dict[str, float] = {}
        for k, v in (stat_bonuses or {}).items():
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not v:
                continue
            gain = round(v * BONUS_PER_LEVEL, 2)
            out[k] = int(gain) if float(gain).is_integer() else gain
        return out
