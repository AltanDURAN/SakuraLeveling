from datetime import datetime, UTC

from app.domain.services.alchemy_service import boosted_seconds


class HealthRegenerationService:
    def apply_out_of_combat_regeneration(
        self,
        current_hp: int,
        max_hp: int,
        hp_regeneration: int,
        last_updated_at: datetime,
        now: datetime,
        boosts=(),
    ) -> int:
        # boosts : fenêtres (début, fin, ×M) de l'élixir de récupération
        # d'Elna, cf. alchemy_service.boosted_seconds.
        if max_hp <= 0:
            return 0

        if current_hp >= max_hp:
            return max_hp

        if hp_regeneration <= 0:
            return max(0, min(current_hp, max_hp))

        # 🔥 NORMALISATION
        if last_updated_at.tzinfo is None:
            last_updated_at = last_updated_at.replace(tzinfo=UTC)

        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)

        elapsed_seconds = boosted_seconds(last_updated_at, now, boosts)

        if elapsed_seconds <= 0:
            return max(0, min(current_hp, max_hp))

        elapsed_minutes = int(elapsed_seconds // 60)

        if elapsed_minutes <= 0:
            return max(0, min(current_hp, max_hp))

        regenerated_hp = elapsed_minutes * hp_regeneration
        new_current_hp = current_hp + regenerated_hp

        return max(0, min(new_current_hp, max_hp))