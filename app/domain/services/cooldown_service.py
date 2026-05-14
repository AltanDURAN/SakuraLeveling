from datetime import datetime, timedelta, UTC
from zoneinfo import ZoneInfo

from app.domain.value_objects.cooldown import Cooldown


# Reset du /daily à minuit heure de Paris (DST automatique). Le bot
# tourne en UTC sur le VPS mais les joueurs vivent en France.
_PARIS = ZoneInfo("Europe/Paris")


def _normalize(dt: datetime) -> datetime:
    """SQLite ne préserve pas le tzinfo : on assume UTC pour les datetimes
    naïfs ressortis de la DB afin que les comparaisons soient toujours
    cohérentes avec un `now` UTC-aware."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class CooldownService:
    def is_available(self, cooldown: Cooldown | None, now: datetime) -> bool:
        if cooldown is None or cooldown.next_available_at is None:
            return True

        return _normalize(now) >= _normalize(cooldown.next_available_at)

    def build_next_daily_cooldown(self, now: datetime) -> tuple[datetime, datetime]:
        """Reset à minuit heure de Paris (CET/CEST selon la saison) : la
        prochaine récup' est dispo dès le lendemain 00:00 Paris. Stocké
        en UTC (DST géré automatiquement par zoneinfo).

        Exemples (heure d'été CEST = UTC+2) :
        - Récup à 14h30 UTC (16h30 Paris) → next = 22h UTC (00h Paris)
        - Récup à 23h UTC (01h Paris, déjà demain Paris !) → next = 22h UTC
        """
        last_used_at = now
        now_aware = (
            now.astimezone(UTC) if now.tzinfo is not None
            else now.replace(tzinfo=UTC)
        )
        # On convertit en heure Paris pour calculer "demain 00:00 local",
        # puis on repasse en UTC pour stockage.
        now_paris = now_aware.astimezone(_PARIS)
        next_midnight_paris = (now_paris + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        next_midnight_utc = next_midnight_paris.astimezone(UTC)
        return last_used_at, next_midnight_utc

    def build_next_skill_reset_cooldown(
        self, now: datetime, days: int = 7
    ) -> tuple[datetime, datetime]:
        last_used_at = now
        next_available_at = now + timedelta(days=days)
        return last_used_at, next_available_at

    def build_next_duel_challenge_cooldown(
        self, now: datetime, seconds: int = 60
    ) -> tuple[datetime, datetime]:
        last_used_at = now
        next_available_at = now + timedelta(seconds=seconds)
        return last_used_at, next_available_at