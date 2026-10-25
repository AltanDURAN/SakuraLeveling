from dataclasses import dataclass

from app.application.services.player_stats_resolver import resolve_player_stats_bulk
from app.domain.services.leaderboard_service import (
    Leaderboard,
    LeaderboardEntry,
    LeaderboardService,
)
from app.domain.services.power_score_service import PowerScoreService
from app.domain.services.stats_service import StatsService
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.repositories.player_kill_repository import PlayerKillRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.shared.formatters import format_int as _format_int


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


class GetLeaderboardUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        equipment_repository: EquipmentRepository,
        kill_repository: PlayerKillRepository,
        mob_repository: MobRepository,
        stats_service: StatsService,
        power_score_service: PowerScoreService,
        leaderboard_service: LeaderboardService,
        role_trial_repository=None,
    ) -> None:
        self.player_repository = player_repository
        self.equipment_repository = equipment_repository
        self.kill_repository = kill_repository
        self.mob_repository = mob_repository
        self.stats_service = stats_service
        self.power_score_service = power_score_service
        self.leaderboard_service = leaderboard_service
        self.role_trial_repository = role_trial_repository

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

        if category_code.startswith("defi_"):
            return self._compute_role_trial(category_code.split("_", 1)[1], limit)

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
        # On réutilise la session du player_repository — toutes les routes du
        # leaderboard partagent une même session live.
        session = self.player_repository.session

        profiles = self.player_repository.list_all_profiles()

        # Resolver EN LOT : ~6 requêtes au total au lieu de ~6 par joueur.
        # Avant, /classement faisait du N+1 (≈1 000 requêtes à 200 joueurs) —
        # cf. audit §5. Le résultat par joueur est identique à l'appel unitaire.
        stats_by_player = resolve_player_stats_bulk(
            session=session,
            profiles=profiles,
            stats_service=self.stats_service,
        )

        for profile in profiles:
            stats = stats_by_player.get(profile.player.id)
            if stats is None:
                continue
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

    def _compute_role_trial(self, key: str, limit: int) -> Leaderboard | None:
        """Défis de rôle, semaine EN COURS (5 meilleurs jours) : `dps`,
        `tank`, `soutien` (score brut) ou `general` (moyenne des trois rôles,
        chacun ramené à 100 = le meilleur de la semaine)."""
        from datetime import UTC, datetime, timedelta

        from app.domain.services import role_trial_service as rts

        if self.role_trial_repository is None or key not in (*rts.ROLES, rts.GENERAL):
            return None
        week = rts.week_start(rts.trial_day(datetime.now(UTC)))
        weekly = rts.weekly_scores(
            self.role_trial_repository.week_rows(week, week + timedelta(days=6)))
        if key == rts.GENERAL:
            board = rts.ranking(rts.general_scores(weekly))
            label, fmt = rts.GENERAL_LABEL, (lambda v: f"{v:.1f}".replace(".", ",") + " / 100")
        else:
            board = rts.ranking(weekly[key])
            label, fmt = rts.ROLE_LABELS[key], (lambda v: _format_int(round(v)))
        entries = []
        for pid, value in board[:limit]:
            profile = self.player_repository.get_profile_by_player_id(pid)
            name = profile.player.display_name if profile is not None else f"Joueur#{pid}"
            entries.append(LeaderboardEntry(player_id=pid, display_name=name,
                                            value=round(value), formatted_value=fmt(value)))
        return Leaderboard(
            category_code=f"defi_{key}",
            category_label=f"Défis de la semaine — {label}",
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
