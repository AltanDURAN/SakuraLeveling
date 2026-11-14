"""« Prochaine étape » : la première chose utile à faire, affichée sous la
bannière de `/profil` (décision de l'auteur, 14/11/2026).

Un joueur accumulait des points sans le savoir, gardait des pièces sans les
porter, oubliait son booster offert : une seule ligne, la plus urgente."""

from __future__ import annotations

from datetime import UTC, datetime

from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.gear_repository import GearRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session

#: Emplacements d'équipement d'un joueur.
SLOTS = 7


def next_step(session, player_id: int) -> str | None:
    profile = PlayerRepository(session).get_profile_by_player_id(player_id)
    if profile is None:
        return None
    progression = profile.progression
    if progression.stat_points > 0:
        n = progression.stat_points
        return f"👉 **Prochaine étape** : tu as {n} point{'s' if n > 1 else ''} de stats à placer — `/stats`."
    if progression.skill_points > 0:
        n = progression.skill_points
        return f"👉 **Prochaine étape** : tu as {n} point{'s' if n > 1 else ''} d'arbre à investir — `/arbre`."
    gear = GearRepository(session).list_owned(player_id)
    worn = sum(1 for g in gear if g.equipped)
    if worn < SLOTS and any(not g.equipped for g in gear):
        return "👉 **Prochaine étape** : tu as une pièce que tu ne portes pas — `/equiper`."
    daily = CooldownRepository(session).get_by_player_and_action(player_id, "daily")
    due = daily is None or (daily.next_available_at.replace(tzinfo=daily.next_available_at.tzinfo or UTC)
                            <= datetime.now(UTC))
    if due:
        return "👉 **Prochaine étape** : ta solde du jour t'attend — `/daily`."
    try:
        from app.application.use_cases import cards

        if cards.collection(session, player_id).free_booster:
            return "👉 **Prochaine étape** : un booster de cartes offert t'attend — `/booster`, dans le salon des cartes."
    except Exception:  # noqa: BLE001 — une ligne d'aide ne casse jamais le profil
        pass
    return None


def next_step_for(discord_id: int) -> str | None:
    """Depuis le bot (sa propre session ; jamais d'exception)."""
    try:
        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(discord_id)
            return next_step(session, profile.player.id) if profile else None
    except Exception:  # noqa: BLE001
        return None
