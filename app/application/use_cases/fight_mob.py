from app.domain.services.combat_service import CombatService
from app.domain.services.loot_service import LootService
from app.domain.services.progression_service import ProgressionService
from app.domain.services.quest_service import QuestService
from app.domain.services.skill_tree_service import SkillTreeService
from app.domain.services.stats_service import StatsService
from app.domain.value_objects.battle_result import BattleResult
from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.repositories.player_kill_repository import PlayerKillRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.db.repositories.quest_repository import QuestRepository
from app.infrastructure.skill_tree.skill_tree_loader import (
    get_definition as get_skill_tree_definition,
)


class FightMobUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        equipment_repository: EquipmentRepository,
        mob_repository: MobRepository,
        inventory_repository: InventoryRepository,
        item_repository: ItemRepository,
        quest_repository: QuestRepository,
        kill_repository: PlayerKillRepository,
        stats_service: StatsService,
        combat_service: CombatService,
        loot_service: LootService,
        progression_service: ProgressionService,
        quest_service: QuestService,
        class_repository: ClassRepository,
        skill_allocation_repository: PlayerSkillAllocationRepository | None = None,
    ):
        self.player_repository = player_repository
        self.equipment_repository = equipment_repository
        self.mob_repository = mob_repository
        self.inventory_repository = inventory_repository
        self.item_repository = item_repository
        self.quest_repository = quest_repository
        self.kill_repository = kill_repository
        self.stats_service = stats_service
        self.combat_service = combat_service
        self.loot_service = loot_service
        self.progression_service = progression_service
        self.quest_service = quest_service
        self.class_repository = class_repository
        self.skill_allocation_repository = skill_allocation_repository

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
        mob_code: str,
    ) -> BattleResult | None:
        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )

        mob = self.mob_repository.get_by_code(mob_code)
        if mob is None:
            return None

        equipped_items = self.equipment_repository.list_by_player_id(profile.player.id)
        active_class = self.class_repository.get_current_class_for_player(profile.player.id)

        # Bonus de l'arbre de compétences (None si repository non fourni)
        if self.skill_allocation_repository is not None:
            allocations = self.skill_allocation_repository.list_by_player(profile.player.id)
            skill_bonuses = SkillTreeService(get_skill_tree_definition()).aggregate_bonuses(
                allocations
            )
        else:
            skill_bonuses = None

        # Bonus de titres (Champion 1v1 actif s'applique aussi en combat solo).
        try:
            from app.application.services.title_bonus_resolver import (
                resolve_title_bonuses,
            )
            title_bonuses = resolve_title_bonuses(
                self.kill_repository.session, profile.player.id,
            )
        except Exception:
            title_bonuses = None

        player_stats = self.stats_service.calculate_player_stats(
            profile=profile,
            equipped_items=equipped_items,
            active_class=active_class,
            skill_bonuses=skill_bonuses,
            title_bonuses=title_bonuses,
        )

        result = self.combat_service.fight_player_vs_mob(
            player_stats=player_stats,
            mob=mob,
        )

        if not result.victory:
            return result

        # Application des bonus xp/gold/drop de l'arbre + Farmer Fou.
        gold_multiplier = 1.0 + (skill_bonuses.gold_drop_percent if skill_bonuses else 0.0)
        xp_multiplier = 1.0 + (skill_bonuses.xp_drop_percent if skill_bonuses else 0.0)
        drop_multiplier = skill_bonuses.drop_rate_multiplier if skill_bonuses else 1.0
        farmer_pct = (title_bonuses.gold_xp_bonus_pct / 100.0) if title_bonuses else 0.0

        final_gold = round(result.gold_gained * gold_multiplier * (1 + farmer_pct))
        final_xp = round(result.xp_gained * xp_multiplier * (1 + farmer_pct))

        self.player_repository.add_gold(profile.player.id, final_gold)
        self.kill_repository.increment(profile.player.id, mob.code)

        # Check titres : la famille du mob peut débloquer un titre. Best
        # effort : si le repo n'est pas fourni (rétrocompat tests), skip.
        title_repo = getattr(self, "title_repository", None)
        if title_repo is not None:
            from app.application.services.title_unlock_service import (
                TitleUnlockService,
            )
            TitleUnlockService(title_repo, self.kill_repository).check_kills_family(
                profile.player.id, mob.family
            )
            TitleUnlockService(title_repo, self.kill_repository).check_kills_total(
                profile.player.id
            )

            # Titre exclusif Farmer Fou : transfert si le candidat dépasse
            # STRICTEMENT le détenteur actuel.
            try:
                from app.application.services.exclusive_title_service import (
                    ExclusiveTitleService,
                )
                excl = ExclusiveTitleService(self.kill_repository.session)
                holder_id = excl.current_holder("farmer_fou")
                candidate_total = self.kill_repository.get_total_kills(profile.player.id)
                if holder_id is None and candidate_total > 0:
                    excl.award_to("farmer_fou", profile.player.id)
                elif holder_id is not None and holder_id != profile.player.id:
                    holder_total = self.kill_repository.get_total_kills(holder_id)
                    if candidate_total > holder_total:
                        excl.award_to("farmer_fou", profile.player.id)
            except Exception as _e:
                import logging
                logging.getLogger(__name__).warning(
                    "Farmer Fou title hook (solo) failed: %s", _e, exc_info=True,
                )

        new_level, new_xp, new_skill_points = self.progression_service.apply_level_up(
            current_level=profile.progression.level,
            current_xp=profile.progression.xp,
            gained_xp=final_xp,
            current_skill_points=profile.progression.skill_points,
        )

        leveled_up = new_level > profile.progression.level

        self.player_repository.apply_progression(
            player_id=profile.player.id,
            new_level=new_level,
            new_xp=new_xp,
            new_skill_points=new_skill_points,
        )

        dropped_items = self.loot_service.generate_loot(
            mob, drop_rate_multiplier=drop_multiplier
        )

        for item_code, quantity in dropped_items:
            item = self.item_repository.get_by_code(item_code)
            if item is None:
                continue

            self.inventory_repository.add_item(
                player_id=profile.player.id,
                item_definition_id=item.id,
                quantity=quantity,
            )

        player_quests = self.quest_repository.list_definitions()

        for quest in player_quests:
            if quest.objective_type != "kill_mob":
                continue

            state = self.quest_repository.get_or_create_player_quest_state(
                profile.player.id,
                quest.id,
            )

            progress, is_completed = self.quest_service.compute_progress_for_kill_quest(
                quest=quest,
                current_progress=state.progress_quantity,
                killed_mob_code=mob.code,
            )

            self.quest_repository.update_progress(
                profile.player.id,
                quest.id,
                progress,
                is_completed,
            )

        # On reflète les valeurs boostées dans le résultat affiché au joueur
        result.gold_gained = final_gold
        result.xp_gained = final_xp
        result.items_gained = dropped_items
        result.leveled_up = leveled_up
        result.new_level = new_level if leveled_up else None

        return result