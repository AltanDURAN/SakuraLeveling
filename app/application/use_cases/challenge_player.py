"""Duel 1v1 entre joueurs (commande /fight @target).

Règles métier :
    1. Pas de bot, pas de soi-même.
    2. Cible doit avoir un profil joueur.
    3. Le challenger doit être STRICTEMENT moins bien classé que la cible
       (rank_position challenger > rank_position target). Si le challenger
       est mieux classé ou ex-aequo, le défi est refusé.
    4. Cooldown 60 s entre deux challenges sortants par challenger.
    5. Combat lancé avec full HP des deux côtés (pas de lecture du current_hp
       réel). Aucun current_hp n'est écrit après le duel.
    6. Si le challenger gagne → swap des rank_position. Sinon, rien ne bouge
       côté ladder (mais wins/losses sont incrémentés des deux côtés).
"""

from dataclasses import dataclass
from datetime import datetime, UTC

from app.domain.services.cooldown_service import CooldownService
from app.domain.services.duel_combat_service import DuelCombatService
from app.domain.services.skill_tree_service import SkillTreeService
from app.domain.services.stats_service import StatsService
from app.domain.value_objects.duel_result import DuelResult
from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.player_duel_rank_repository import (
    PlayerDuelRankRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.skill_tree.skill_tree_loader import (
    get_definition as get_skill_tree_definition,
)


DUEL_COOLDOWN_KEY = "duel_challenge"
DUEL_COOLDOWN_SECONDS = 60


@dataclass
class DuelOutcome:
    success: bool
    message: str
    result: DuelResult | None = None
    challenger_display_name: str = ""
    target_display_name: str = ""
    challenger_old_position: int = 0
    target_old_position: int = 0
    challenger_new_position: int = 0
    target_new_position: int = 0
    swapped: bool = False
    challenger_won: bool = False


class ChallengePlayerUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        equipment_repository: EquipmentRepository,
        class_repository: ClassRepository,
        skill_allocation_repository: PlayerSkillAllocationRepository,
        duel_rank_repository: PlayerDuelRankRepository,
        cooldown_repository: CooldownRepository,
        stats_service: StatsService,
        duel_combat_service: DuelCombatService,
        cooldown_service: CooldownService,
    ) -> None:
        self.player_repository = player_repository
        self.equipment_repository = equipment_repository
        self.class_repository = class_repository
        self.skill_allocation_repository = skill_allocation_repository
        self.duel_rank_repository = duel_rank_repository
        self.cooldown_repository = cooldown_repository
        self.stats_service = stats_service
        self.duel_combat_service = duel_combat_service
        self.cooldown_service = cooldown_service

    def execute(
        self,
        challenger_discord_id: int,
        challenger_username: str,
        challenger_display_name: str,
        target_discord_id: int,
        target_display_name: str,
    ) -> DuelOutcome:
        if challenger_discord_id == target_discord_id:
            return DuelOutcome(
                success=False, message="❌ Vous ne pouvez pas vous défier vous-même."
            )

        challenger_profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=challenger_discord_id,
            username=challenger_username,
            display_name=challenger_display_name,
        )
        target_profile = self.player_repository.get_by_discord_id(target_discord_id)
        if target_profile is None:
            return DuelOutcome(
                success=False,
                message=f"❌ {target_display_name} n'a pas encore de profil joueur.",
            )

        # Cooldown anti-spam
        now = datetime.now(UTC)
        cooldown = self.cooldown_repository.get_by_player_and_action(
            challenger_profile.player.id, DUEL_COOLDOWN_KEY
        )
        if not self.cooldown_service.is_available(cooldown, now):
            ts = int(cooldown.next_available_at.timestamp())
            return DuelOutcome(
                success=False,
                message=f"⏳ Vous devez attendre avant un nouveau défi (<t:{ts}:R>).",
            )

        # Auto-inscription au ladder pour les deux
        challenger_rank = self.duel_rank_repository.get_or_create(
            challenger_profile.player.id
        )
        target_rank = self.duel_rank_repository.get_or_create(target_profile.player.id)

        # Règle d'éligibilité : challenger doit être STRICTEMENT moins bien classé
        if challenger_rank.rank_position <= target_rank.rank_position:
            return DuelOutcome(
                success=False,
                message=(
                    f"❌ Vous êtes déjà mieux classé(e) (ou ex-aequo) que "
                    f"{target_display_name} dans le ladder 1v1 "
                    f"(vous : #{challenger_rank.rank_position}, "
                    f"cible : #{target_rank.rank_position}). "
                    f"Vous ne pouvez défier que des joueurs mieux classés."
                ),
            )

        # Calcul des stats finales (équipement + classe + skill bonuses)
        skill_tree_def = get_skill_tree_definition()
        skill_service = SkillTreeService(skill_tree_def)

        challenger_stats = self._compute_stats(challenger_profile, skill_service)
        target_stats = self._compute_stats(target_profile, skill_service)

        # Combat (a = challenger, b = target). Démarre full HP des deux côtés.
        result = self.duel_combat_service.fight_player_vs_player(
            a_stats=challenger_stats,
            b_stats=target_stats,
        )

        challenger_won = result.winner == "a"
        old_chal_pos = challenger_rank.rank_position
        old_tgt_pos = target_rank.rank_position

        if challenger_won:
            self.duel_rank_repository.swap_positions(
                challenger_profile.player.id, target_profile.player.id
            )
            new_chal_pos = old_tgt_pos
            new_tgt_pos = old_chal_pos
            self.duel_rank_repository.increment_wins(challenger_profile.player.id)
            self.duel_rank_repository.increment_losses(target_profile.player.id)
        else:
            new_chal_pos = old_chal_pos
            new_tgt_pos = old_tgt_pos
            self.duel_rank_repository.increment_wins(target_profile.player.id)
            self.duel_rank_repository.increment_losses(challenger_profile.player.id)

        # Cooldown : posé même en cas de défaite (anti-spam)
        last_used, next_avail = self.cooldown_service.build_next_duel_challenge_cooldown(
            now, seconds=DUEL_COOLDOWN_SECONDS
        )
        self.cooldown_repository.upsert(
            challenger_profile.player.id, DUEL_COOLDOWN_KEY, last_used, next_avail
        )

        # Progress quête hebdo : duel_win pour le vainqueur (best effort)
        try:
            from app.application.use_cases.weekly_quests import (
                WeeklyQuestProgressService,
            )
            from app.infrastructure.db.repositories.weekly_quest_repository import (
                WeeklyQuestRepository,
            )
            session = self.duel_rank_repository.session  # même session SQLAlchemy
            wqp = WeeklyQuestProgressService(WeeklyQuestRepository(session))
            winner_pid = (
                challenger_profile.player.id if challenger_won
                else target_profile.player.id
            )
            wqp.on_duel_won(winner_pid, count=1)
        except Exception:
            pass  # quête hebdo = best effort, ne casse pas le duel

        return DuelOutcome(
            success=True,
            message=(
                f"🏆 Victoire ! Vous prenez la place de {target_display_name} "
                f"dans le ladder."
                if challenger_won
                else f"💀 Défaite. {target_display_name} conserve sa position."
            ),
            result=result,
            challenger_display_name=challenger_display_name,
            target_display_name=target_display_name,
            challenger_old_position=old_chal_pos,
            target_old_position=old_tgt_pos,
            challenger_new_position=new_chal_pos,
            target_new_position=new_tgt_pos,
            swapped=challenger_won,
            challenger_won=challenger_won,
        )

    def _compute_stats(self, profile, skill_service: SkillTreeService):
        equipped_items = self.equipment_repository.list_by_player_id(profile.player.id)
        active_class = self.class_repository.get_current_class_for_player(
            profile.player.id
        )
        allocations = self.skill_allocation_repository.list_by_player(profile.player.id)
        skill_bonuses = skill_service.aggregate_bonuses(allocations)
        return self.stats_service.calculate_player_stats(
            profile=profile,
            equipped_items=equipped_items,
            active_class=active_class,
            skill_bonuses=skill_bonuses,
        )
