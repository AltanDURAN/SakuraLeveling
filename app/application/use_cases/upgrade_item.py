"""Fusion d'équipement chez l'artisan : sacrifier une copie pour gagner un niveau.

Chaque artisan améliore ce qu'il fabrique (Borak : armes, boucliers, tête,
corps ; Elna : accessoires). La fusion est IMMÉDIATE — pas de commande à
récupérer — et ne fait pas monter la maîtrise : la maîtrise récompense le
travail de fabrication, pas l'or dépensé.

Le prix dérive du prix de FABRICATION de la pièce chez ce même artisan, remise
de maîtrise comprise : une pièce chère à fabriquer est chère à améliorer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.entities.artisan import ArtisanDefinition
from app.domain.services.artisan_service import ArtisanService
from app.domain.services.item_power_service import ItemPowerService
from app.domain.services.item_upgrade_service import (
    MAX_ITEM_LEVEL,
    copies_required,
    fusion_gold_cost,
    scaled_bonuses,
)
from app.infrastructure.db.repositories.equipment_repository import (
    EquipmentRepository,
)
from app.infrastructure.db.repositories.inventory_repository import (
    InventoryRepository,
)
from app.infrastructure.db.repositories.player_item_level_repository import (
    PlayerItemLevelRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.work_order_repository import (
    WorkOrderRepository,
)


@dataclass(frozen=True)
class UpgradeCandidate:
    """Une pièce possédée que cet artisan sait améliorer."""

    item_code: str
    item_name: str
    category: str
    level: int
    owned: int


@dataclass
class UpgradePreview:
    item_code: str
    item_name: str
    item_category: str
    level: int
    bonuses_now: dict
    bonuses_next: dict
    owned: int
    required: int
    equipped_count: int
    gold_cost: int
    player_gold: int
    item_power: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def maxed(self) -> bool:
        return self.level >= MAX_ITEM_LEVEL

    @property
    def has_copies(self) -> bool:
        return self.owned >= self.required

    @property
    def can_afford(self) -> bool:
        return self.player_gold >= self.gold_cost

    @property
    def can_upgrade(self) -> bool:
        return not self.maxed and self.has_copies and self.can_afford

    @property
    def blocking_reason(self) -> str:
        if self.maxed:
            return f"Déjà au niveau maximum (+{MAX_ITEM_LEVEL})."
        if not self.has_copies:
            worn = (
                f" (tu en portes {self.equipped_count})" if self.equipped_count else ""
            )
            return (
                f"Il faut {self.required} exemplaires pour en fusionner un "
                f"— tu en as {self.owned}{worn}."
            )
        if not self.can_afford:
            return f"Il te manque {self.gold_cost - self.player_gold} or."
        return ""


@dataclass
class UpgradeResult:
    success: bool
    message: str
    new_level: int = 0


class UpgradeItemUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        inventory_repository: InventoryRepository,
        equipment_repository: EquipmentRepository,
        item_level_repository: PlayerItemLevelRepository,
        work_order_repository: WorkOrderRepository,
        artisan_service: ArtisanService,
        power_service: ItemPowerService | None = None,
    ) -> None:
        self.players = player_repository
        self.inventory = inventory_repository
        self.equipment = equipment_repository
        self.levels = item_level_repository
        self.orders = work_order_repository
        self.artisans = artisan_service
        self.power = power_service or ItemPowerService()

    # ---------------------------------------------------------- lecture --
    def candidates(
        self, definition: ArtisanDefinition, player_id: int,
    ) -> list[UpgradeCandidate]:
        levels = self.levels.get_levels_for_player(player_id)
        out = []
        for inv in self.inventory.list_by_player_id(player_id):
            item = inv.item_definition
            if item.category not in definition.categories or inv.quantity <= 0:
                continue
            out.append(
                UpgradeCandidate(
                    item_code=item.code,
                    item_name=item.name,
                    category=item.category,
                    level=levels.get(item.id, 0),
                    owned=inv.quantity,
                )
            )
        out.sort(key=lambda c: (c.category, c.item_name.lower()))
        return out

    def preview(
        self, definition: ArtisanDefinition, player_id: int, item_code: str,
    ) -> UpgradePreview | None:
        inv = next(
            (
                i for i in self.inventory.list_by_player_id(player_id)
                if i.item_definition.code == item_code
            ),
            None,
        )
        if inv is None or inv.item_definition.category not in definition.categories:
            return None
        item = inv.item_definition
        level = self.levels.get_level(player_id, item.id)
        equipped = sum(
            1 for e in self.equipment.list_by_player_id(player_id)
            if e.item_definition.id == item.id
        )
        power = self.power.marginal_power(
            item.stat_bonuses, getattr(item, "level_requirement", 1),
        )
        completed = self.orders.orders_completed(player_id, definition.code)
        craft_gold = self.artisans.gold_cost(
            power, self.artisans.tier_for(definition, completed),
        )
        profile = self.players.get_profile_by_player_id(player_id)
        return UpgradePreview(
            item_code=item.code,
            item_name=item.name,
            item_category=item.category,
            level=level,
            bonuses_now=scaled_bonuses(item.stat_bonuses, level),
            bonuses_next=scaled_bonuses(item.stat_bonuses, min(MAX_ITEM_LEVEL, level + 1)),
            owned=inv.quantity,
            required=copies_required(equipped),
            equipped_count=equipped,
            gold_cost=fusion_gold_cost(
                craft_gold, level, self.artisans.pricing.upgrade_gold_pct_per_level,
            ),
            player_gold=profile.resources.gold if profile else 0,
            item_power=power,
        )

    # --------------------------------------------------------- écriture --
    def upgrade(
        self, definition: ArtisanDefinition, player_id: int, item_code: str,
    ) -> UpgradeResult:
        # Tout est revérifié ici : l'aperçu a pu être affiché il y a des minutes.
        preview = self.preview(definition, player_id, item_code)
        if preview is None:
            return UpgradeResult(
                success=False,
                message=f"❌ {definition.name} ne travaille pas cette pièce, ou tu ne l'as plus.",
            )
        if not preview.can_upgrade:
            return UpgradeResult(success=False, message=f"❌ {preview.blocking_reason}")

        inv = next(
            i for i in self.inventory.list_by_player_id(player_id)
            if i.item_definition.code == item_code
        )
        item_id = inv.item_definition.id
        if not self.inventory.remove_item(player_id, item_id, 1):
            return UpgradeResult(success=False, message="❌ La copie à fusionner a disparu.")
        self.players.add_gold(player_id, -preview.gold_cost)
        new_level = self.levels.increment(player_id, item_id, MAX_ITEM_LEVEL)
        if new_level == -1:  # course improbable : déjà monté entre-temps
            return UpgradeResult(success=False, message="❌ Déjà au niveau maximum.")
        return UpgradeResult(
            success=True,
            message=(
                f"✨ **{preview.item_name}** passe à **+{new_level}** "
                f"({preview.gold_cost} or et une copie fusionnée)."
            ),
            new_level=new_level,
        )
