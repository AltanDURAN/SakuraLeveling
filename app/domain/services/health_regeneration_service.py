from datetime import datetime, UTC


class HealthRegenerationService:
    def apply_out_of_combat_regeneration(
        self,
        current_hp: int,
        max_hp: int,
        hp_regeneration: int,
        last_updated_at: datetime,
        now: datetime,
    ) -> int:
        if max_hp <= 0:
            return 0

        if current_hp >= max_hp:
            return max_hp

        if hp_regeneration <= 0:
            return max(0, min(current_hp, max_hp))

        # 🔥 NORMALISATION UTC
        if last_updated_at.tzinfo is None:
            last_updated_at = last_updated_at.replace(tzinfo=UTC)

        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)

        elapsed_seconds = (now - last_updated_at).total_seconds()

        if elapsed_seconds <= 0:
            return max(0, min(current_hp, max_hp))

        elapsed_minutes = int(elapsed_seconds // 60)

        if elapsed_minutes <= 0:
            return max(0, min(current_hp, max_hp))

        regenerated_hp = elapsed_minutes * hp_regeneration
        new_current_hp = current_hp + regenerated_hp

        return max(0, min(new_current_hp, max_hp))