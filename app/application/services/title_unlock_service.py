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

    def check_kills_mob(
        self, player_id: int, mob_code: str
    ) -> list[TitleUnlockedEvent]:
        """Titre Chasseur Légendaire : seuil de kills sur un mob donné.
        Filtré par condition_target=mob_code pour ne checker que les titres
        liés au mob qui vient d'être tué."""
        unlocked: list[TitleUnlockedEvent] = []
        candidates = list_for_condition("kills_mob")
        if not candidates:
            return unlocked

        kills_per_mob = self.kill_repository.get_kills_per_mob(player_id)
        mob_kills = kills_per_mob.get(mob_code, 0)

        for title in candidates:
            if title.condition_target != mob_code:
                continue
            if mob_kills < title.condition_value:
                continue
            if self.title_repository.unlock(player_id, title.code):
                unlocked.append(TitleUnlockedEvent(title=title))
        return unlocked

    def check_dodges_total(
        self, player_id: int, current_total: int
    ) -> list[TitleUnlockedEvent]:
        """Titre Intouchable : seuil d'esquives encaissées en encounter."""
        unlocked: list[TitleUnlockedEvent] = []
        candidates = list_for_condition("dodges_total")
        if not candidates:
            return unlocked

        for title in candidates:
            if current_total < title.condition_value:
                continue
            if self.title_repository.unlock(player_id, title.code):
                unlocked.append(TitleUnlockedEvent(title=title))
        return unlocked

    def check_daily_streak(
        self, player_id: int, current_streak: int
    ) -> list[TitleUnlockedEvent]:
        """Titre Taverne Addict : seuil de daily streak."""
        unlocked: list[TitleUnlockedEvent] = []
        candidates = list_for_condition("daily_streak")
        if not candidates:
            return unlocked

        for title in candidates:
            if current_streak < title.condition_value:
                continue
            if self.title_repository.unlock(player_id, title.code):
                unlocked.append(TitleUnlockedEvent(title=title))
        return unlocked
