"""Use case `/equiper_panoplie <famille>` : équipe d'un coup la panoplie.

Système SIMPLIFIÉ : une panoplie ne concerne que **4 emplacements** — tête,
corps et les deux mains (les accessoires n'en font pas partie). Les paliers de
bonus sont donc à 2 et 4 pièces.

Deux mains : soit deux pièces à 1 main (armes et/ou boucliers), soit une seule
pièce à 2 mains qui occupe les deux emplacements. On privilégie ce que le
joueur possède, en gardant les pièces de la bonne famille déjà portées.
"""

from dataclasses import dataclass, field

from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.sets.set_loader import get_definition as get_set_definition
from app.shared.enums import PANOPLIE_SLOTS, EquipmentSlot, ItemSlotType


@dataclass
class EquipPanoplieResult:
    success: bool
    message: str
    equipped_changes: list[tuple[str, str]] = field(default_factory=list)
    missing_slots: list[str] = field(default_factory=list)
    kept_pieces: int = 0


class EquipPanoplieUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        inventory_repository: InventoryRepository,
        equipment_repository: EquipmentRepository,
    ) -> None:
        self.player_repository = player_repository
        self.inventory_repository = inventory_repository
        self.equipment_repository = equipment_repository

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
        family: str,
    ) -> EquipPanoplieResult:
        family = (family or "").strip()
        if not family:
            return EquipPanoplieResult(False, "❌ Nom de panoplie invalide.")
        if get_set_definition(family) is None:
            return EquipPanoplieResult(
                False, f"❌ Panoplie `{family}` introuvable.",
            )

        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id, username=username, display_name=display_name,
        )
        player_id = profile.player.id

        # Pièces de la famille disponibles : inventaire + déjà équipées.
        owned = [
            inv.item_definition
            for inv in self.inventory_repository.list_by_player_id(player_id)
            if (inv.item_definition.family or "").strip() == family
            and inv.item_definition.is_equipable
        ]
        worn = {
            eq.slot: eq.item_definition
            for eq in self.equipment_repository.list_by_player_id(player_id)
        }
        for slot, item in worn.items():
            if (item.family or "").strip() == family:
                owned.append(item)

        by_type: dict[str, list] = {}
        for item in owned:
            by_type.setdefault(item.equipment_slot or "", []).append(item)

        changes: list[tuple[str, str]] = []
        missing: list[str] = []
        kept = 0

        def _equip(slot: EquipmentSlot, item) -> None:
            current = worn.get(slot.value)
            if current is not None and current.id == item.id:
                nonlocal kept
                kept += 1
                return
            self.equipment_repository.equip_item(
                player_id=player_id, item_definition_id=item.id, slot=slot.value,
            )
            changes.append((slot.value, item.name))

        # ---- Tête et corps : une pièce chacun ----
        for slot, item_type in (
            (EquipmentSlot.TETE, ItemSlotType.TETE.value),
            (EquipmentSlot.CORPS, ItemSlotType.CORPS.value),
        ):
            candidates = by_type.get(item_type, [])
            if candidates:
                _equip(slot, candidates[0])
            else:
                missing.append(slot.value)

        # ---- Les deux mains ----
        weapons = by_type.get(ItemSlotType.ARME.value, [])
        two_handed = [w for w in weapons if w.requires_two_hands]
        one_handed = [w for w in weapons if not w.requires_two_hands]

        if len(one_handed) >= 2:
            # Deux pièces à 1 main : le plus de bonus de panoplie.
            self.equipment_repository.unequip_slot(
                player_id, EquipmentSlot.ARME_2.value,
            )
            _equip(EquipmentSlot.ARME_1, one_handed[0])
            _equip(EquipmentSlot.ARME_2, one_handed[1])
        elif two_handed:
            # Une 2-mains occupe les deux emplacements → compte pour 2 pièces.
            self.equipment_repository.unequip_slot(
                player_id, EquipmentSlot.ARME_2.value,
            )
            _equip(EquipmentSlot.ARME_1, two_handed[0])
        elif one_handed:
            _equip(EquipmentSlot.ARME_1, one_handed[0])
            missing.append(EquipmentSlot.ARME_2.value)
        else:
            missing.extend(
                [EquipmentSlot.ARME_1.value, EquipmentSlot.ARME_2.value],
            )

        equipped_count = len(PANOPLIE_SLOTS) - len(missing)
        if equipped_count == 0:
            return EquipPanoplieResult(
                success=False,
                message=(
                    f"❌ Vous ne possédez aucune pièce de la panoplie "
                    f"**{family}** (tête, corps ou arme/bouclier)."
                ),
                missing_slots=missing,
            )

        lines = [f"✅ Panoplie **{family}** équipée — "
                 f"**{equipped_count}/{len(PANOPLIE_SLOTS)}** pièces."]
        if changes:
            lines.append(
                "Équipé : " + ", ".join(f"{name}" for _, name in changes) + "."
            )
        if kept:
            lines.append(f"{kept} pièce(s) déjà en place conservée(s).")
        if missing:
            lines.append("Manque : " + ", ".join(f"`{s}`" for s in missing) + ".")

        return EquipPanoplieResult(
            success=True,
            message="\n".join(lines),
            equipped_changes=changes,
            missing_slots=missing,
            kept_pieces=kept,
        )
