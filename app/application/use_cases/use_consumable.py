"""Use case d'utilisation d'un consommable depuis l'inventaire.

V1 : ne supporte que `effect=heal_percent` (potion de soin unique : 10% PV max).
L'effet est lu depuis `item.stat_bonuses["effect"]` + `["value"]`.

Sécurité : décrément atomique de l'inventaire ; refus si quantité < 1
ou si l'item n'est pas marqué `category=consumable`.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from app.application.services.player_stats_resolver import resolve_player_stats
from app.domain.services.health_regeneration_service import HealthRegenerationService
from app.domain.services.stats_service import StatsService
from app.domain.services.skill_tree_service import SkillTreeService
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
        skill_allocation_repository: PlayerSkillAllocationRepository,
        health_repository: PlayerHealthRepository,
        stats_service: StatsService,
    ) -> None:
        self.player_repository = player_repository
        self.item_repository = item_repository
        self.inventory_repository = inventory_repository
        self.equipment_repository = equipment_repository
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

        owned = sum(
            i.quantity for i in self.inventory_repository.list_by_player_id(profile.player.id)
            if i.item_definition.id == item.id
        )
        if owned < 1:
            return UseConsumableResult(
                success=False,
                message=f"❌ Vous n'avez pas de **{item.name}** en inventaire.",
                item_name=item.name,
            )

        # PV réels AVANT de consommer quoi que ce soit : max_hp par la chaîne
        # complète (arbre, sets, titres…) et régénération hors combat écoulée
        # depuis la dernière mise à jour. Sans elle, boire une potion après
        # une pause effaçait les PV régénérés entre-temps.
        equipped = self.equipment_repository.list_by_player_id(profile.player.id)
        stats = resolve_player_stats(
            self.equipment_repository.session,
            profile,
            equipped,
            stats_service=self.stats_service,
        )
        max_hp = stats.max_hp
        health_state = self.health_repository.get_or_create(
            profile.player.id, default_current_hp=max_hp
        )
        hp_before = HealthRegenerationService().apply_out_of_combat_regeneration(
            current_hp=health_state.current_hp,
            max_hp=max_hp,
            hp_regeneration=stats.hp_regeneration,
            last_updated_at=health_state.updated_at,
            now=datetime.now(UTC),
        )

        # PV déjà pleins : on ne gâche pas la potion.
        if hp_before >= max_hp:
            return UseConsumableResult(
                success=False,
                message=(
                    f"💚 Tes PV sont déjà au maximum ({max_hp} / {max_hp}) : "
                    f"**{item.name}** n'a pas été utilisée."
                ),
                item_name=item.name,
                hp_before=hp_before,
                hp_after=hp_before,
                max_hp=max_hp,
            )

        # Décrément atomique : retire 1, refuse si pas en inventaire
        removed = self.inventory_repository.remove_item(
            player_id=profile.player.id, item_definition_id=item.id, quantity=1,
        )
        if not removed:
            return UseConsumableResult(
                success=False,
                message=f"❌ Vous n'avez pas de **{item.name}** en inventaire.",
                item_name=item.name,
            )

        # Application de l'effet
        percent = int(bonuses.get("value", 0))
        heal_amount = round(max_hp * percent / 100)
        hp_after = min(max_hp, hp_before + heal_amount)
        self.health_repository.update_current_hp(profile.player.id, hp_after)

        # NOTE: hook quête on_consumable_used retiré (V2).

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
