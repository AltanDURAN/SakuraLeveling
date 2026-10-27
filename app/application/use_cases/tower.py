"""Tour solo (`/tour`) : l'état, un essai, la récompense du jour.

Règles pures dans `app/domain/services/tower_service.py`, étages dans
`tower_floors.json`. Le combat se joue SEUL, à PV et mana pleins, sans potion
ni élixir ; une victoire fait avancer le record et garde le ticket, une
défaite coûte le ticket sans faire reculer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, UTC
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.application.services.combat_passives_resolver import resolve_party_passives
from app.application.services.elemental_resolver import elemental_multipliers
from app.application.services.player_stats_resolver import resolve_player_stats
from app.application.services.title_bonus_resolver import resolve_title_bonuses
from app.application.use_cases.tower_tickets import TicketStatus, TowerTicketsUseCase
from app.domain.entities.player_profile import PlayerProfile
from app.domain.services import tower_service as ts
from app.domain.services.party_combat_service import PartyCombatService
from app.domain.value_objects.party_battle_result import PartyBattleResult
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_career_stats_repository import (
    PlayerCareerStatsRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.tower_repository import TowerRepository
from app.infrastructure.db.unit_of_work import atomic
from app.infrastructure.tower import tower_loader

_PARIS = ZoneInfo("Europe/Paris")


class TowerError(Exception):
    """Essai ou récompense refusés (message pour le joueur)."""


@dataclass(frozen=True)
class TowerStatus:
    best_floor: int
    next_floor: int | None          # None : la tour est terminée
    floor: dict | None              # contenu de l'étage à tenter
    tickets: TicketStatus
    daily_claimed: bool
    daily: ts.TowerReward           # la récompense du jour (selon le record)


@dataclass(frozen=True)
class TowerAttempt:
    floor: int
    floor_data: dict
    victory: bool
    result: PartyBattleResult
    reward: ts.TowerReward          # premier passage (vide après une défaite)
    ticket_used: bool               # perdu sur une défaite
    tickets_left: int
    best_floor: int


def tower_day(now: datetime | None = None) -> date:
    """Jour de la tour (minuit heure de Paris, comme tous les resets du jeu)."""
    return (now or datetime.now(UTC)).astimezone(_PARIS).date()


def status(session: Session, profile: PlayerProfile, now: datetime | None = None) -> TowerStatus:
    player_id = profile.player.id
    progress = TowerRepository(session).get_or_create(player_id)
    nxt = ts.next_floor(progress.best_floor)
    return TowerStatus(
        best_floor=progress.best_floor,
        next_floor=nxt,
        floor=tower_loader.get_floor(nxt) if nxt else None,
        tickets=TowerTicketsUseCase(session).status(player_id, now),
        daily_claimed=progress.daily_claimed_on == tower_day(now),
        daily=ts.daily_reward(progress.best_floor, tower_loader.floor_material(progress.best_floor)),
    )


def attempt(session: Session, profile: PlayerProfile, now: datetime | None = None) -> TowerAttempt:
    """Tente l'étage suivant le record. Il faut un ticket disponible ; il
    n'est consommé que sur une défaite."""
    player_id = profile.player.id
    tickets = TowerTicketsUseCase(session)
    with atomic(session):
        repo = TowerRepository(session)
        progress = repo.get_or_create(player_id)
        floor = ts.next_floor(progress.best_floor)
        floor_data = tower_loader.get_floor(floor) if floor else None
        if floor is None or floor_data is None:
            raise TowerError("🏆 Tu as franchi tous les étages de la tour.")
        if tickets.status(player_id, now).available <= 0:
            raise TowerError("🎟️ Plus de ticket aujourd'hui : reviens demain (minuit, heure de Paris).")

        result = _fight(session, profile, floor_data)
        repo.record_attempt(player_id, floor, result.victory)
        reward = ts.TowerReward()
        if result.victory:
            reward = ts.first_clear_reward(floor, tower_loader.floor_material(floor))
            _grant(session, player_id, reward)
        else:
            tickets.consume(player_id, now)
        return TowerAttempt(
            floor=floor, floor_data=floor_data, victory=result.victory, result=result,
            reward=reward, ticket_used=not result.victory,
            tickets_left=tickets.status(player_id, now).available,
            best_floor=repo.best_floor(player_id),
        )


def claim_daily(session: Session, profile: PlayerProfile, now: datetime | None = None) -> ts.TowerReward:
    """Récompense du jour selon l'étage record, une fois par jour."""
    player_id = profile.player.id
    with atomic(session):
        repo = TowerRepository(session)
        best = repo.get_or_create(player_id).best_floor
        reward = ts.daily_reward(best, tower_loader.floor_material(best))
        if reward.is_empty:
            raise TowerError("🗼 Franchis au moins un étage pour toucher la récompense du jour.")
        if not repo.claim_daily(player_id, tower_day(now)):
            raise TowerError("🎁 Récompense de la tour déjà prise aujourd'hui : reviens demain.")
        _grant(session, player_id, reward)
        return reward


def _fight(session: Session, profile: PlayerProfile, floor_data: dict) -> PartyBattleResult:
    """Le joueur, seul, à PV et mana pleins, SANS élixir, contre l'étage."""
    player_id = profile.player.id
    worn = EquipmentRepository(session).list_by_player_id(player_id)
    stats = resolve_player_stats(session, profile, worn)
    passives, tactics = resolve_party_passives(session, [player_id])
    enemies = floor_data["enemies"]
    out, inc = {}, {}
    for i, enemy in enumerate(enemies):
        o, n = elemental_multipliers(session, [player_id], enemy.get("element", ""), passives)
        out[i], inc[i] = o, n
    member = {
        "player_id": player_id, "user_id": profile.player.discord_id,
        "name": profile.player.display_name, "avatar_url": "",
        "stats": stats, "current_hp": stats.max_hp, "max_hp": stats.max_hp,
        "current_mana": stats.mana_max, "mana_max": stats.mana_max,
    }
    return PartyCombatService().fight_party_vs_mobs(
        [member], ts.enemy_setups(enemies, out, inc),
        title_bonuses_by_player={player_id: resolve_title_bonuses(session, player_id)},
        passives_by_player=passives, tactics_by_player=tactics,
    )


def _grant(session: Session, player_id: int, reward: ts.TowerReward) -> None:
    from app.application.services.encounter_service import EncounterService

    players = PlayerRepository(session)
    if reward.gold:
        players.add_gold(player_id, reward.gold)
        PlayerCareerStatsRepository(session).add(player_id, gold_earned=reward.gold)
    if reward.xp:
        EncounterService._grant_xp(players, player_id, reward.xp)
    items, inventory = ItemRepository(session), InventoryRepository(session)
    for code, qty in reward.materials:
        item = items.get_by_code(code)
        if item is not None:
            inventory.add_item(player_id, item.id, qty)
