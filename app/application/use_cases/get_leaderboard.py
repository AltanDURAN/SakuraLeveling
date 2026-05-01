from dataclasses import dataclass

from app.domain.services.leaderboard_service import Leaderboard, LeaderboardService
from app.domain.services.power_score_service import PowerScoreService
from app.domain.services.stats_service import StatsService
from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.repositories.player_kill_repository import PlayerKillRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository


COMPUTED_STAT_FIELDS = {
    "max_hp",
    "attack",
    "defense",
    "speed",
    "crit_chance",
    "crit_damage",
    "dodge",
    "hp_regeneration",
}


@dataclass
class LeaderboardCategory:
    code: str
    label: str
    icon: str = "📊"


def _format_int(value: int) -> str:
    return f"{value:,}".replace(",", " ")


class GetLeaderboardUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        equipment_repository: EquipmentRepository,
        class_repository: ClassRepository,
        kill_repository: PlayerKillRepository,
        mob_repository: MobRepository,
        stats_service: StatsService,
        power_score_service: PowerScoreService,
        leaderboard_service: LeaderboardService,
    ) -> None:
        self.player_repository = player_repository
        self.equipment_repository = equipment_repository
        self.class_repository = class_repository
        self.kill_repository = kill_repository
        self.mob_repository = mob_repository
        self.stats_service = stats_service
        self.power_score_service = power_score_service
        self.leaderboard_service = leaderboard_service

    def execute(self, category_code: str, limit: int = 10) -> Leaderboard | None:
        if category_code == "power":
            return self._compute_power(limit)

        if category_code == "level":
            return self._compute_level(limit)

        if category_code == "gold":
            return self._compute_gold(limit)

        if category_code in COMPUTED_STAT_FIELDS:
            return self._compute_stat(category_code, limit)

        if category_code == "kills_total":
            return self._compute_kills_total(limit)

        if category_code.startswith("kills_mob:"):
            mob_code = category_code.split(":", 1)[1]
            return self._compute_kills_mob(mob_code, limit)

        if category_code.startswith("kills_family:"):
            family = category_code.split(":", 1)[1]
            return self._compute_kills_family(family, limit)

        return None

    def _compute_power(self, limit: int) -> Leaderboard:
        scored = self._compute_for_each_player(
            value_fn=lambda stats: self.power_score_service.calculate_from_stats(stats),
        )
        entries = self.leaderboard_service.rank(
            scored,
            limit=limit,
            format_value=self.power_score_service.format_score,
        )
        return Leaderboard(
            category_code="power",
            category_label="Puissance",
            entries=entries,
        )

    def _compute_stat(self, stat_field: str, limit: int) -> Leaderboard:
        scored = self._compute_for_each_player(
            value_fn=lambda stats: int(getattr(stats, stat_field)),
        )
        entries = self.leaderboard_service.rank(
            scored,
            limit=limit,
            format_value=_format_int,
        )
        return Leaderboard(
            category_code=stat_field,
            category_label=_STAT_LABELS.get(stat_field, stat_field),
            entries=entries,
        )

    def _compute_for_each_player(self, value_fn) -> list[tuple[int, str, int]]:
        results: list[tuple[int, str, int]] = []

        profiles = self.player_repository.list_all_profiles()
        for profile in profiles:
            equipped_items = self.equipment_repository.list_by_player_id(profile.player.id)
            active_class = self.class_repository.get_current_class_for_player(profile.player.id)

            stats = self.stats_service.calculate_player_stats(
                profile=profile,
                equipped_items=equipped_items,
                active_class=active_class,
            )

            value = value_fn(stats)
            results.append((profile.player.id, profile.player.display_name, value))

        return results

    def _compute_level(self, limit: int) -> Leaderboard:
        profiles = self.player_repository.list_all_profiles()
        scored = [
            (profile.player.id, profile.player.display_name, profile.progression.level)
            for profile in profiles
        ]
        entries = self.leaderboard_service.rank(
            scored,
            limit=limit,
            format_value=_format_int,
        )
        return Leaderboard(
            category_code="level",
            category_label="Niveau",
            entries=entries,
        )

    def _compute_gold(self, limit: int) -> Leaderboard:
        profiles = self.player_repository.list_all_profiles()
        scored = [
            (profile.player.id, profile.player.display_name, profile.resources.gold)
            for profile in profiles
        ]
        entries = self.leaderboard_service.rank(
            scored,
            limit=limit,
            format_value=_format_int,
        )
        return Leaderboard(
            category_code="gold",
            category_label="Or",
            entries=entries,
        )

    def _compute_kills_total(self, limit: int) -> Leaderboard:
        rows = self.kill_repository.top_total_kills(limit=limit)
        entries = self.leaderboard_service.rank(
            rows,
            limit=limit,
            format_value=_format_int,
        )
        return Leaderboard(
            category_code="kills_total",
            category_label="Monstres tués (total)",
            entries=entries,
        )

    def _compute_kills_mob(self, mob_code: str, limit: int) -> Leaderboard | None:
        mob = self.mob_repository.get_by_code(mob_code)
        if mob is None:
            return None

        rows = self.kill_repository.top_kills_for_mob(mob_code=mob_code, limit=limit)
        entries = self.leaderboard_service.rank(
            rows,
            limit=limit,
            format_value=_format_int,
        )
        return Leaderboard(
            category_code=f"kills_mob:{mob_code}",
            category_label=f"Tués : {mob.name}",
            entries=entries,
        )

    def _compute_kills_family(self, family: str, limit: int) -> Leaderboard:
        rows = self.kill_repository.top_kills_for_family(family=family, limit=limit)
        entries = self.leaderboard_service.rank(
            rows,
            limit=limit,
            format_value=_format_int,
        )
        return Leaderboard(
            category_code=f"kills_family:{family}",
            category_label=f"Tués : famille {family.capitalize()}",
            entries=entries,
        )


_STAT_LABELS = {
    "max_hp": "Points de vie",
    "attack": "Attaque",
    "defense": "Défense",
    "speed": "Vitesse",
    "crit_chance": "Chance de critique",
    "crit_damage": "Dégâts de critique",
    "dodge": "Esquive",
    "hp_regeneration": "Régénération",
}
