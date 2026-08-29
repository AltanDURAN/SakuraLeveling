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


@dataclass(frozen=True)
class EquipPlan:
    """Où une pièce atterrit, et quels emplacements l'opération libère.

    Fonction PURE : le use case l'applique en base, le preview de `/equiper`
    s'en sert pour simuler le diff de stats. Avant, chacun refaisait le calcul
    dans son coin — et le preview ignorait la règle des 2-mains, donc il
    surestimait les stats quand les deux mains étaient occupées.
    """

    target_slot: str
    freed_slots: tuple[str, ...] = ()


def plan_equip(item_def, occupied: dict) -> EquipPlan | None:
    """Décide l'emplacement cible. `occupied` : slot → ItemDefinition portée.

    Renvoie None si l'item n'a pas de type d'emplacement exploitable.
    """
    allowed = SLOTS_FOR_ITEM_TYPE.get(item_def.equipment_slot or "")
    if not allowed:
        return None

    # 2 mains : toujours arme_1, et les DEUX mains sont libérées.
    if item_def.requires_two_hands:
        return EquipPlan(
            EquipmentSlot.ARME_1.value,
            tuple(s.value for s in WEAPON_SLOTS if s.value in occupied),
        )

    # 1 main posée alors qu'une 2-mains est portée : elle prend sa place.
    if item_def.equipment_slot == ItemSlotType.ARME.value:
        held = occupied.get(EquipmentSlot.ARME_1.value)
        if held is not None and held.requires_two_hands:
            return EquipPlan(EquipmentSlot.ARME_1.value)

    # Sinon : premier emplacement LIBRE du type, à défaut le premier.
    target = next(
        (s.value for s in allowed if s.value not in occupied),
        allowed[0].value,
    )
    return EquipPlan(target)


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

    def _occupied(self, player_id: int) -> dict:
        """slot → ItemDefinition portée (entrée de `plan_equip`)."""
        return {
            e.slot: e.item_definition
            for e in self.equipment_repository.list_by_player_id(player_id)
        }

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
            plan = plan_equip(item_def, self._occupied(player_id))
            target_slot = plan.target_slot if plan else allowed[0].value

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
