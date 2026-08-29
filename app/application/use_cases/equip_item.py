from dataclasses import dataclass, field

from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.shared.enums import (
    SLOTS_FOR_ITEM_TYPE,
    WEAPON_SLOTS,
    EquipmentSlot,
    ItemSlotType,
)


@dataclass
class EquipResult:
    success: bool
    message: str
    slots_equipped: list[str] = field(default_factory=list)
    unequipped_items: list[str] = field(default_factory=list)


class EquipItemUseCase:
    """Équipe un item — système SIMPLIFIÉ à 7 emplacements.

    Un item déclare un TYPE d'emplacement (`tete`, `corps`, `accessoire`,
    `arme`), pas un emplacement précis. Le joueur n'a donc rien à choisir :
    on pose la pièce dans le premier emplacement LIBRE de son type, et à
    défaut on remplace le premier.

    Armes et boucliers partagent les deux mains (`arme_1`, `arme_2`) :
      • 1 main  → un emplacement ; on peut donc en porter deux (deux armes,
        deux boucliers, ou un de chaque) ;
      • 2 mains → occupe `arme_1` et VERROUILLE `arme_2` (rien d'autre).
    """

    def __init__(
        self,
        player_repository: PlayerRepository,
        inventory_repository: InventoryRepository,
        equipment_repository: EquipmentRepository,
    ):
        self.player_repository = player_repository
        self.inventory_repository = inventory_repository
        self.equipment_repository = equipment_repository

    def _pick_slot(self, player_id: int, allowed: list[EquipmentSlot]) -> str:
        """Premier emplacement libre du type ; sinon le premier (remplacement)."""
        for slot in allowed:
            if self.equipment_repository.get_slot(player_id, slot.value) is None:
                return slot.value
        return allowed[0].value

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
        item_code: str,
        slot: str | None = None,
    ) -> EquipResult:
        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )
        player_id = profile.player.id

        inventory_items = self.inventory_repository.list_by_player_id(player_id)
        matched_item = next(
            (i for i in inventory_items if i.item_definition.code == item_code),
            None,
        )
        if matched_item is None:
            return EquipResult(
                success=False,
                message=f"❌ L'item `{item_code}` n'est pas dans votre inventaire.",
            )

        item_def = matched_item.item_definition
        if not item_def.is_equipable:
            return EquipResult(
                success=False,
                message=f"❌ **{item_def.name}** n'est pas équipable.",
            )

        item_type = item_def.equipment_slot or ""
        allowed = SLOTS_FOR_ITEM_TYPE.get(item_type)
        if not allowed:
            return EquipResult(
                success=False,
                message=(
                    f"❌ **{item_def.name}** n'a pas d'emplacement valide "
                    f"(`{item_type or 'aucun'}`)."
                ),
            )

        # Emplacement demandé explicitement : il doit appartenir au bon type.
        if slot is not None:
            if slot not in {s.value for s in allowed}:
                choices = ", ".join(f"`{s.value}`" for s in allowed)
                return EquipResult(
                    success=False,
                    message=(
                        f"❌ **{item_def.name}** ne peut pas aller dans `{slot}`. "
                        f"Emplacements possibles : {choices}."
                    ),
                )
            target_slot = slot
        else:
            target_slot = self._pick_slot(player_id, allowed)

        unequipped: list[str] = []

        # ---- Armes / boucliers à DEUX MAINS : occupent la paire entière ----
        if item_def.requires_two_hands:
            for hand in WEAPON_SLOTS:
                existing = self.equipment_repository.get_slot(player_id, hand.value)
                if existing is not None:
                    unequipped.append(existing.item_definition.name)
                    self.equipment_repository.unequip_slot(player_id, hand.value)
            self.equipment_repository.equip_item(
                player_id=player_id,
                item_definition_id=item_def.id,
                slot=EquipmentSlot.ARME_1.value,
            )
            return EquipResult(
                success=True,
                message=(
                    f"✅ **{item_def.name}** équipée à **deux mains** — elle "
                    f"occupe vos deux emplacements d'arme."
                ),
                slots_equipped=[s.value for s in WEAPON_SLOTS],
                unequipped_items=unequipped,
            )

        # ---- Une main : libérer une éventuelle 2-mains déjà portée ----
        if item_type == ItemSlotType.ARME.value:
            held = self.equipment_repository.get_slot(
                player_id, EquipmentSlot.ARME_1.value,
            )
            if held is not None and held.item_definition.requires_two_hands:
                unequipped.append(held.item_definition.name)
                self.equipment_repository.unequip_slot(
                    player_id, EquipmentSlot.ARME_1.value,
                )
                target_slot = EquipmentSlot.ARME_1.value

        # Même item dans deux emplacements : il faut deux exemplaires.
        others = [
            s.value for s in allowed
            if s.value != target_slot
        ]
        for other in others:
            worn = self.equipment_repository.get_slot(player_id, other)
            if worn is not None and worn.item_definition.id == item_def.id:
                if matched_item.quantity < 2:
                    return EquipResult(
                        success=False,
                        message=(
                            f"❌ **{item_def.name}** est déjà équipé. Pour en "
                            f"porter deux, il vous faut un second exemplaire."
                        ),
                    )
                break

        existing = self.equipment_repository.get_slot(player_id, target_slot)
        if existing is not None:
            unequipped.append(existing.item_definition.name)

        self.equipment_repository.equip_item(
            player_id=player_id,
            item_definition_id=item_def.id,
            slot=target_slot,
        )
        return EquipResult(
            success=True,
            message=f"✅ **{item_def.name}** équipé — emplacement `{target_slot}`.",
            slots_equipped=[target_slot],
            unequipped_items=unequipped,
        )
