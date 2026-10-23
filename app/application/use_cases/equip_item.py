from dataclasses import dataclass, field

from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.shared.enums import (
    SLOT_LABELS,
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
    """Équipe une pièce — 7 emplacements, placement automatique.

    Équipement v2 : on porte un EXEMPLAIRE (`gear_id`), ou à défaut la
    meilleure copie libre de la pièce demandée (`item_code` : rareté, puis
    forge sacrée). Règles :
      • une même pièce ne se porte qu'UNE fois (armes et accessoires compris) ;
        demander une meilleure copie d'une pièce déjà portée la remplace dans
        son emplacement ;
      • armes et boucliers partagent les deux mains ; une 2 mains occupe
        `arme_1` et verrouille `arme_2` ;
      • aucun niveau requis (tout est en % du socle du joueur).
    """

    def __init__(
        self,
        player_repository: PlayerRepository,
        inventory_repository: InventoryRepository,
        equipment_repository: EquipmentRepository,
        gear_repository=None,
    ):
        from app.infrastructure.db.repositories.gear_repository import GearRepository

        self.player_repository = player_repository
        self.inventory_repository = inventory_repository
        self.equipment_repository = equipment_repository
        self.gear_repository = gear_repository or GearRepository(equipment_repository.session)

    def _occupied(self, player_id: int) -> dict:
        """slot → ItemDefinition portée (entrée de `plan_equip`)."""
        return {
            e.slot: e.item_definition
            for e in self.equipment_repository.list_by_player_id(player_id)
        }

    def _pick_copy(self, player_id: int, item_code: str | None, gear_id: int | None):
        owned = self.gear_repository.list_owned(player_id)  # les plus rares d'abord
        if gear_id is not None:
            return next((g for g in owned if g.id == gear_id), None)
        copies = [g for g in owned if g.item_definition.code == item_code]
        free = [g for g in copies if not g.equipped]
        return free[0] if free else (copies[0] if copies else None)

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
        item_code: str | None = None,
        slot: str | None = None,
        gear_id: int | None = None,
    ) -> EquipResult:
        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )
        player_id = profile.player.id

        gear = self._pick_copy(player_id, item_code, gear_id)
        if gear is None:
            return EquipResult(
                success=False,
                message=f"❌ Tu ne possèdes pas cette pièce (`{item_code or gear_id}`).",
            )
        item_def = gear.item_definition
        if not item_def.is_equipable:
            return EquipResult(success=False, message=f"❌ **{item_def.name}** n'est pas équipable.")
        if gear.equipped:
            return EquipResult(
                success=False,
                message=f"ℹ️ **{item_def.name}** est déjà portée "
                        f"({SLOT_LABELS.get(gear.equipped_slot, gear.equipped_slot)}).",
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

        worn = self.equipment_repository.list_by_player_id(player_id)

        # Une pièce, une fois : une copie déjà portée est REMPLACÉE sur place.
        same = next((e for e in worn if e.item_definition.id == item_def.id), None)
        if same is not None and gear_id is None and (
            (rarity_index(same.rarity), same.forge_level)
            >= (rarity_index(gear.rarity), gear.forge_level)
        ):
            return EquipResult(
                success=False,
                message=(
                    f"ℹ️ Tu portes déjà **{item_def.name}** "
                    f"({rarity_label(same.rarity)}) : une pièce ne se porte "
                    f"qu'une fois, et tu n'en as pas de meilleure copie."
                ),
            )
        if same is not None:
            self.equipment_repository.equip_gear(player_id, gear.id, same.slot)
            return EquipResult(
                success=True,
                message=(
                    f"✅ **{item_def.name}** : ta copie {rarity_label(gear.rarity)} "
                    f"remplace celle que tu portais "
                    f"({SLOT_LABELS.get(same.slot, same.slot)})."
                ),
                slots_equipped=[same.slot],
                unequipped_items=[f"{item_def.name} ({rarity_label(same.rarity)})"],
            )

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
            plan = plan_equip(item_def, {e.slot: e.item_definition for e in worn})
            target_slot = plan.target_slot if plan else allowed[0].value

        unequipped: list[str] = []

        # ---- Deux mains : la paire entière ----
        if item_def.requires_two_hands:
            for hand in WEAPON_SLOTS:
                existing = self.equipment_repository.get_slot(player_id, hand.value)
                if existing is not None:
                    unequipped.append(existing.item_definition.name)
                    self.equipment_repository.unequip_slot(player_id, hand.value)
            self.equipment_repository.equip_gear(player_id, gear.id, EquipmentSlot.ARME_1.value)
            return EquipResult(
                success=True,
                message=(
                    f"✅ **{item_def.name}** équipée à **deux mains** — elle "
                    f"occupe vos deux emplacements d'arme."
                ),
                slots_equipped=[s.value for s in WEAPON_SLOTS],
                unequipped_items=unequipped,
            )

        # ---- Une main : libérer une éventuelle 2 mains déjà portée ----
        if item_type == ItemSlotType.ARME.value:
            held = self.equipment_repository.get_slot(player_id, EquipmentSlot.ARME_1.value)
            if held is not None and held.item_definition.requires_two_hands:
                unequipped.append(held.item_definition.name)
                self.equipment_repository.unequip_slot(player_id, EquipmentSlot.ARME_1.value)
                target_slot = EquipmentSlot.ARME_1.value

        existing = self.equipment_repository.get_slot(player_id, target_slot)
        if existing is not None:
            unequipped.append(existing.item_definition.name)

        self.equipment_repository.equip_gear(player_id, gear.id, target_slot)
        return EquipResult(
            success=True,
            message=(
                f"✅ **{item_def.name}** ({rarity_label(gear.rarity)}) équipé — "
                f"{SLOT_LABELS.get(target_slot, target_slot)}."
            ),
            slots_equipped=[target_slot],
            unequipped_items=unequipped,
        )


def rarity_index(rarity: str) -> int:
    from app.domain.services.gear_service import rarity_index as _index

    return _index(rarity)


def rarity_label(rarity: str) -> str:
    from app.domain.services.gear_service import RARITY_LABELS

    return RARITY_LABELS.get(rarity, rarity).lower()
