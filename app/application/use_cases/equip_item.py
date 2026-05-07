from dataclasses import dataclass, field

from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.shared.enums import EquipmentSlot


@dataclass
class EquipResult:
    success: bool
    message: str
    slots_equipped: list[str] = field(default_factory=list)
    unequipped_items: list[str] = field(default_factory=list)


# Pour les armes 1-main, on accepte main_droite OU main_gauche.
# Pour tous les autres équipements, le slot doit matcher exactement.
_HAND_SLOTS = {EquipmentSlot.MAIN_HAND.value, EquipmentSlot.OFF_HAND.value}


class EquipItemUseCase:
    """Équipe un item dans un slot, en gérant :
    - validation : item équipable + slot compatible
    - ambidextrie : armes 1-main équipables en main_droite ou main_gauche
    - 2-mains : occupe MAIN_HAND (logiquement les 2 slots), déséquipe l'autre main
    - remplacement : si un autre 2-mains était équipé, le déséquipe entièrement
    - blocage : ne peut pas équiper deux fois la même instance d'item dans les
      deux mains (il faudrait deux exemplaires distincts dans l'inventaire)
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

        inventory_items = self.inventory_repository.list_by_player_id(profile.player.id)
        matched_item = next(
            (item for item in inventory_items if item.item_definition.code == item_code),
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

        is_hand_weapon = (
            item_def.equipment_slot in _HAND_SLOTS
            and not item_def.requires_two_hands
        )

        # Auto-pick du slot pour les armes 1-main : on prend le slot libre,
        # main_droite en priorité, fallback main_gauche, sinon main_droite
        # (sera remplacée). L'utilisateur n'a plus besoin de spécifier.
        if is_hand_weapon and slot is None:
            md_occupied = self.equipment_repository.get_slot(
                profile.player.id, EquipmentSlot.MAIN_HAND.value,
            )
            mg_occupied = self.equipment_repository.get_slot(
                profile.player.id, EquipmentSlot.OFF_HAND.value,
            )
            if md_occupied is None:
                target_slot = EquipmentSlot.MAIN_HAND.value
            elif mg_occupied is None:
                target_slot = EquipmentSlot.OFF_HAND.value
            else:
                target_slot = EquipmentSlot.MAIN_HAND.value
        else:
            target_slot = slot or item_def.equipment_slot

        if is_hand_weapon:
            if target_slot not in _HAND_SLOTS:
                return EquipResult(
                    success=False,
                    message=(
                        f"❌ **{item_def.name}** s'équipe en main : "
                        f"choisissez `main_droite` ou `main_gauche`."
                    ),
                )
        else:
            if target_slot != item_def.equipment_slot:
                return EquipResult(
                    success=False,
                    message=(
                        f"❌ **{item_def.name}** s'équipe dans le slot "
                        f"`{item_def.equipment_slot}`, pas `{target_slot}`."
                    ),
                )

        unequipped: list[str] = []

        # Cas 2-mains : occupe MAIN_HAND seul (verrouille OFF_HAND par convention)
        if item_def.requires_two_hands:
            for hand in (EquipmentSlot.MAIN_HAND.value, EquipmentSlot.OFF_HAND.value):
                existing = self.equipment_repository.get_slot(profile.player.id, hand)
                if existing is not None:
                    unequipped.append(existing.item_definition.name)
                    self.equipment_repository.unequip_slot(profile.player.id, hand)

            self.equipment_repository.equip_item(
                player_id=profile.player.id,
                item_definition_id=item_def.id,
                slot=EquipmentSlot.MAIN_HAND.value,
            )
            return EquipResult(
                success=True,
                message=(
                    f"✅ **{item_def.name}** équipée à deux mains "
                    f"(main_droite + main_gauche)."
                ),
                slots_equipped=[
                    EquipmentSlot.MAIN_HAND.value,
                    EquipmentSlot.OFF_HAND.value,
                ],
                unequipped_items=unequipped,
            )

        # Si on équipe en main : vérifier qu'aucune arme 2-mains n'est déjà là
        if target_slot in _HAND_SLOTS:
            existing_main = self.equipment_repository.get_slot(
                profile.player.id, EquipmentSlot.MAIN_HAND.value
            )
            if (
                existing_main is not None
                and existing_main.item_definition.requires_two_hands
            ):
                unequipped.append(existing_main.item_definition.name)
                self.equipment_repository.unequip_slot(
                    profile.player.id, EquipmentSlot.MAIN_HAND.value
                )

            # Empêche d'équiper le même item dans les deux mains avec un seul
            # exemplaire (le joueur doit posséder 2 exemplaires).
            other_hand = (
                EquipmentSlot.OFF_HAND.value
                if target_slot == EquipmentSlot.MAIN_HAND.value
                else EquipmentSlot.MAIN_HAND.value
            )
            other = self.equipment_repository.get_slot(profile.player.id, other_hand)
            if other is not None and other.item_definition.id == item_def.id:
                if matched_item.quantity < 2:
                    return EquipResult(
                        success=False,
                        message=(
                            f"❌ Vous avez déjà équipé **{item_def.name}** "
                            f"dans `{other_hand}`. Pour l'équiper aussi en "
                            f"`{target_slot}`, il vous faut un second exemplaire."
                        ),
                    )

        # Remplace l'équipement existant dans le slot
        existing = self.equipment_repository.get_slot(profile.player.id, target_slot)
        if existing is not None:
            unequipped.append(existing.item_definition.name)

        self.equipment_repository.equip_item(
            player_id=profile.player.id,
            item_definition_id=item_def.id,
            slot=target_slot,
        )

        return EquipResult(
            success=True,
            message=f"✅ **{item_def.name}** équipée dans `{target_slot}`.",
            slots_equipped=[target_slot],
            unequipped_items=unequipped,
        )
