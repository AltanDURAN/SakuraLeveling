from datetime import datetime, UTC


class ManaRegenerationService:
    """Régénération du mana HORS combat uniquement (miroir strict de
    HealthRegenerationService). Le mana ne remonte JAMAIS pendant un combat :
    `mana_regeneration` est purement passif entre les combats, appliqué selon
    le temps écoulé (mana par minute)."""

    def apply_out_of_combat_regeneration(
        self,
        current_mana: int,
        mana_max: int,
        mana_regeneration: int,
        last_updated_at: datetime,
        now: datetime,
    ) -> int:
        if mana_max <= 0:
            return 0

        if current_mana >= mana_max:
            return mana_max

        if mana_regeneration <= 0:
            return max(0, min(current_mana, mana_max))

        if last_updated_at.tzinfo is None:
            last_updated_at = last_updated_at.replace(tzinfo=UTC)

        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)

        elapsed_seconds = (now - last_updated_at).total_seconds()

        if elapsed_seconds <= 0:
            return max(0, min(current_mana, mana_max))

        elapsed_minutes = int(elapsed_seconds // 60)

        if elapsed_minutes <= 0:
            return max(0, min(current_mana, mana_max))

        regenerated_mana = elapsed_minutes * mana_regeneration
        new_current_mana = current_mana + regenerated_mana

        return max(0, min(new_current_mana, mana_max))
