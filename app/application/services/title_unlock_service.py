"""Vérifie après un évènement (kill, duel, craft) si un titre doit être
débloqué pour un joueur. Persiste l'unlock via PlayerTitleRepository.

Centralisé pour pouvoir l'appeler depuis FightMobUseCase, EncounterService,
CraftItemUseCase, ChallengePlayerUseCase, etc., sans dupliquer la logique.
"""

from dataclasses import dataclass

from app.domain.entities.title_definition import TitleDefinition
from app.infrastructure.db.repositories.player_kill_repository import PlayerKillRepository
from app.infrastructure.db.repositories.player_title_repository import (
    PlayerTitleRepository,
)
from app.infrastructure.titles.title_loader import list_for_condition


@dataclass
class TitleUnlockedEvent:
    title: TitleDefinition


class TitleUnlockService:
    def __init__(
        self,
        title_repository: PlayerTitleRepository,
        kill_repository: PlayerKillRepository,
    ) -> None:
        self.title_repository = title_repository
        self.kill_repository = kill_repository

    def check_kills_family(
        self, player_id: int, family: str
    ) -> list[TitleUnlockedEvent]:
        """Appelé après l'incrément d'un kill. Vérifie si un titre de famille
        passe son seuil et le débloque."""
        unlocked: list[TitleUnlockedEvent] = []
        candidates = list_for_condition("kills_family")
        if not candidates:
            return unlocked

        # Compteur pour la famille concernée (un seul calcul SQL)
        family_kills = self.kill_repository.get_kills_for_family(player_id, family)

        for title in candidates:
            if title.condition_target != family:
                continue
            if family_kills < title.condition_value:
                continue
            if self.title_repository.unlock(player_id, title.code):
                unlocked.append(TitleUnlockedEvent(title=title))
        return unlocked

    def check_kills_total(self, player_id: int) -> list[TitleUnlockedEvent]:
        unlocked: list[TitleUnlockedEvent] = []
        candidates = list_for_condition("kills_total")
        if not candidates:
            return unlocked

        total = self.kill_repository.get_total_kills(player_id)
        for title in candidates:
            if total < title.condition_value:
                continue
            if self.title_repository.unlock(player_id, title.code):
                unlocked.append(TitleUnlockedEvent(title=title))
        return unlocked
