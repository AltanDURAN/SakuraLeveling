"""Use case d'utilisation d'un consommable depuis l'inventaire.

V1 : ne supporte que `effect=heal_percent` (potions de soin I/II/III).
L'effet est lu depuis `item.stat_bonuses["effect"]` + `["value"]`.

Sécurité : décrément atomique de l'inventaire ; refus si quantité < 1
ou si l'item n'est pas marqué `category=consumable`.
"""

from dataclasses import dataclass

from app.domain.services.stats_service import StatsService
from app.domain.services.skill_tree_service import SkillTreeService
from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_health_repository import (
    PlayerHealthRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.skill_tree.skill_tree_loader import (
    get_definition as get_skill_tree_definition,
)


CONSUMABLE_CATEGORY = "consumable"
EFFECT_HEAL_PERCENT = "heal_percent"


@dataclass
class UseConsumableResult:
    success: bool
    message: str
    item_name: str = ""
    hp_before: int = 0
    hp_after: int = 0
    max_hp: int = 0


class UseConsumableUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        item_repository: ItemRepository,
        inventory_repository: InventoryRepository,
        equipment_repository: EquipmentRepository,
        class_repository: ClassRepository,
        skill_allocation_repository: PlayerSkillAllocationRepository,
        health_repository: PlayerHealthRepository,
        stats_service: StatsService,
    ) -> None:
        self.player_repository = player_repository
        self.item_repository = item_repository
        self.inventory_repository = inventory_repository
        self.equipment_repository = equipment_repository
        self.class_repository = class_repository
        self.skill_allocation_repository = skill_allocation_repository
        self.health_repository = health_repository
        self.stats_service = stats_service

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
        item_code: str,
    ) -> UseConsumableResult:
        item = self.item_repository.get_by_code(item_code)
        if item is None:
            return UseConsumableResult(
                success=False, message=f"❌ Item `{item_code}` introuvable."
            )
        if item.category != CONSUMABLE_CATEGORY:
            return UseConsumableResult(
                success=False,
                message=f"❌ **{item.name}** n'est pas un consommable.",
            )

        bonuses = item.stat_bonuses or {}
        effect = bonuses.get("effect")
        if effect != EFFECT_HEAL_PERCENT:
            return UseConsumableResult(
                success=False,
                message=f"❌ Effet de **{item.name}** non géré (V1 = heal_percent uniquement).",
            )

        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id, username=username, display_name=display_name,
        )

        # Décrément atomique : retire 1 d'abord, refuse si pas en inventaire
        removed = self.inventory_repository.remove_item(
            player_id=profile.player.id, item_definition_id=item.id, quantity=1,
        )
        if not removed:
            return UseConsumableResult(
                success=False,
                message=f"❌ Vous n'avez pas de **{item.name}** en inventaire.",
                item_name=item.name,
            )

        # Calcul du max_hp courant (4e étage = skill bonuses)
        equipped = self.equipment_repository.list_by_player_id(profile.player.id)
        active_class = self.class_repository.get_current_class_for_player(
            profile.player.id
        )
        allocations = self.skill_allocation_repository.list_by_player(profile.player.id)
        skill_bonuses = SkillTreeService(get_skill_tree_definition()).aggregate_bonuses(
            allocations
        )
        from app.application.services.set_bonus_resolver import resolve_set_bonuses
        set_bonuses = resolve_set_bonuses(equipped)
        stats = self.stats_service.calculate_player_stats(
            profile=profile,
            equipped_items=equipped,
            active_class=active_class,
            skill_bonuses=skill_bonuses,
            set_bonuses=set_bonuses,
        )
        max_hp = stats.max_hp

        # Lecture / création de l'état HP. Default = max_hp si aucune ligne.
        health_state = self.health_repository.get_or_create(
            profile.player.id, default_current_hp=max_hp
        )
        hp_before = health_state.current_hp

        # Application de l'effet
        percent = int(bonuses.get("value", 0))
        heal_amount = round(max_hp * percent / 100)
        hp_after = min(max_hp, hp_before + heal_amount)
        self.health_repository.update_current_hp(profile.player.id, hp_after)

        # Quête quotidienne : on_consumable_used (best effort)
        try:
            from app.application.use_cases.daily_quests import (
                DailyQuestProgressService,
            )
            from app.infrastructure.db.repositories.daily_quest_repository import (
                DailyQuestRepository,
            )
            session = self.inventory_repository.session
            DailyQuestProgressService(DailyQuestRepository(session)).on_consumable_used(
                profile.player.id, count=1,
            )
        except Exception as _e:
            import logging
            logging.getLogger(__name__).warning(
                "Quest progress hook failed: %s", _e, exc_info=True,
            )

        return UseConsumableResult(
            success=True,
            message=(
                f"💚 **{item.name}** utilisé : "
                f"PV {hp_before} → **{hp_after}** / {max_hp} (+{hp_after - hp_before})"
            ),
            item_name=item.name,
            hp_before=hp_before,
            hp_after=hp_after,
            max_hp=max_hp,
        )
