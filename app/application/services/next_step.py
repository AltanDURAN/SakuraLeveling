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


def _trial_ready(session, profile) -> str | None:
    """Le rang dont l'épreuve est OUVERTE (puissance atteinte, pas d'attente) :
    en bêta, personne n'avait tenté `/epreuve` (revue du 20/11/2026)."""
    try:
        from app.application.services.combat_passives_resolver import resolve_player_power
        from app.application.services.player_stats_resolver import resolve_player_stats
        from app.domain.services.rank_trial_service import RankTrialService
        from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
        from app.infrastructure.rank_trials.rank_trial_loader import list_trials

        ranks = ("F", "E", "D", "C", "B", "A", "S", "SS", "SSS")
        trial = RankTrialService(list_trials(), ranks).trial_for(profile.player.earned_rank or "F")
        if trial is None:
            return None
        cooldown = CooldownRepository(session).get_by_player_and_action(profile.player.id, "rank_trial")
        if cooldown is not None and cooldown.next_available_at.replace(
                tzinfo=cooldown.next_available_at.tzinfo or UTC) > datetime.now(UTC):
            return None
        worn = EquipmentRepository(session).list_by_player_id(profile.player.id)
        power = resolve_player_power(session, profile.player.id, resolve_player_stats(session, profile, worn))
        return trial.rank if power >= trial.required_power else None
    except Exception:  # noqa: BLE001 — une ligne d'aide ne casse jamais le profil
        return None


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
    trial = _trial_ready(session, profile)
    if trial is not None:
        return (f"👉 **Prochaine étape** : tu as la puissance pour l'épreuve du **rang {trial}** — "
                "`/epreuve`. Elle ouvre une nouvelle zone.")
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
