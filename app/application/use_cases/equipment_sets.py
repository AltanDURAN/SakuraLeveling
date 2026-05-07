"""Use cases pour les sets d'équipement nommés (loadouts).

Trois opérations :
- `CreateEquipmentSetUseCase(name)` : sauvegarde l'équipement courant
  sous le nom donné. Refus si nom déjà pris ou équipement vide.
- `DeleteEquipmentSetUseCase(name)` : supprime un set existant.
- `EquipSavedSetUseCase(name)` : applique un set sauvegardé. Vérifie
  que le joueur possède toujours les items (en inventaire ou déjà
  équipés). Si une pièce a disparu, échec avec liste explicite.

Ces use cases NE supposent PAS qu'un set représente une panoplie : c'est
juste un mapping libre (slot → item_definition_id) que le joueur a
choisi de sauvegarder.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.equipment_set_repository import (
    EquipmentSet,
    EquipmentSetRepository,
)
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.shared.enums import EquipmentSlot


_MAX_SET_NAME_LEN = 50


@dataclass
class CreateSetResult:
    success: bool
    message: str
    set_name: str = ""
    pieces_saved: int = 0


@dataclass
class DeleteSetResult:
    success: bool
    message: str


@dataclass
class EquipSetResult:
    success: bool
    message: str
    equipped_changes: list[tuple[str, int]] = field(default_factory=list)
    kept_pieces: int = 0
    missing_items: list[str] = field(default_factory=list)


def _validate_name(name: str) -> tuple[str | None, str | None]:
    """Renvoie (cleaned_name, error)."""
    name = (name or "").strip()
    if not name:
        return None, "❌ Nom de set vide."
    if len(name) > _MAX_SET_NAME_LEN:
        return None, f"❌ Nom trop long (max {_MAX_SET_NAME_LEN} caractères)."
    return name, None


class CreateEquipmentSetUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        equipment_repository: EquipmentRepository,
        equipment_set_repository: EquipmentSetRepository,
    ) -> None:
        self.player_repository = player_repository
        self.equipment_repository = equipment_repository
        self.equipment_set_repository = equipment_set_repository

    def execute(
        self, discord_id: int, username: str, display_name: str, name: str,
    ) -> CreateSetResult:
        cleaned, err = _validate_name(name)
        if cleaned is None:
            return CreateSetResult(success=False, message=err)

        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id, username=username, display_name=display_name,
        )
        player_id = profile.player.id

        existing = self.equipment_set_repository.get_by_name(player_id, cleaned)
        if existing is not None:
            return CreateSetResult(
                success=False,
                message=(
                    f"❌ Vous avez déjà un set nommé `{cleaned}`. "
                    f"Supprimez-le d'abord avec `/delete_set` ou choisissez "
                    f"un autre nom."
                ),
            )

        equipped = self.equipment_repository.list_by_player_id(player_id)
        if not equipped:
            return CreateSetResult(
                success=False,
                message=(
                    "❌ Aucun équipement à sauvegarder — équipez au moins "
                    "une pièce avant de créer un set."
                ),
            )

        items = [(e.slot, e.item_definition.id) for e in equipped]
        self.equipment_set_repository.create(
            player_id=player_id, name=cleaned, items=items,
        )
        return CreateSetResult(
            success=True,
            message=(
                f"✅ Set **{cleaned}** créé avec **{len(items)}** pièce(s) "
                "enregistrée(s)."
            ),
            set_name=cleaned,
            pieces_saved=len(items),
        )


class DeleteEquipmentSetUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        equipment_set_repository: EquipmentSetRepository,
    ) -> None:
        self.player_repository = player_repository
        self.equipment_set_repository = equipment_set_repository

    def execute(
        self, discord_id: int, username: str, display_name: str, name: str,
    ) -> DeleteSetResult:
        cleaned, err = _validate_name(name)
        if cleaned is None:
            return DeleteSetResult(success=False, message=err)

        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id, username=username, display_name=display_name,
        )
        deleted = self.equipment_set_repository.delete(
            player_id=profile.player.id, name=cleaned,
        )
        if not deleted:
            return DeleteSetResult(
                success=False,
                message=f"❌ Aucun set nommé `{cleaned}` à supprimer.",
            )
        return DeleteSetResult(
            success=True,
            message=f"🗑️ Set **{cleaned}** supprimé.",
        )


class EquipSavedSetUseCase:
    """Applique un set sauvegardé. Comportement aligné sur EquipPanoplie :
    - conserve les pièces déjà équipées (même item_def + même slot)
    - déséquipe les slots tenus par autre chose, équipe la cible
    - si une 2-mains est sélectionnée pour main_droite, main_gauche est vidé
    - refuse si un item du set n'est plus possédé (inventaire ∪ équipé)
    """

    def __init__(
        self,
        player_repository: PlayerRepository,
        equipment_repository: EquipmentRepository,
        equipment_set_repository: EquipmentSetRepository,
        inventory_repository: InventoryRepository,
    ) -> None:
        self.player_repository = player_repository
        self.equipment_repository = equipment_repository
        self.equipment_set_repository = equipment_set_repository
        self.inventory_repository = inventory_repository

    def execute(
        self, discord_id: int, username: str, display_name: str, name: str,
    ) -> EquipSetResult:
        cleaned, err = _validate_name(name)
        if cleaned is None:
            return EquipSetResult(success=False, message=err)

        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id, username=username, display_name=display_name,
        )
        player_id = profile.player.id

        saved_set = self.equipment_set_repository.get_by_name(player_id, cleaned)
        if saved_set is None:
            return EquipSetResult(
                success=False,
                message=f"❌ Aucun set nommé `{cleaned}`.",
            )
        if not saved_set.items:
            return EquipSetResult(
                success=False,
                message=f"❌ Le set `{cleaned}` est vide.",
            )

        equipped = self.equipment_repository.list_by_player_id(player_id)
        inventory = self.inventory_repository.list_by_player_id(player_id)
        owned_def_ids = (
            {e.item_definition.id for e in equipped}
            | {i.item_definition.id for i in inventory}
        )

        # Vérification : tous les items du set sont-ils possédés ?
        missing: list[str] = []
        for it in saved_set.items:
            if it.item_definition.id not in owned_def_ids:
                missing.append(f"`{it.slot}` → **{it.item_definition.name}**")

        if missing:
            details = "\n".join(f"• {m}" for m in missing[:10])
            suffix = (
                f"\n_… et {len(missing) - 10} autres_"
                if len(missing) > 10 else ""
            )
            return EquipSetResult(
                success=False,
                message=(
                    f"❌ Pièces manquantes pour le set **{cleaned}** "
                    f"(vendues / tradées / cassées ?) :\n{details}{suffix}"
                ),
                missing_items=missing,
            )

        # Plan : map slot → item_def_id à équiper
        plan = {it.slot: it.item_definition.id for it in saved_set.items}

        # 2-mains : si une pièce 2-mains est dans main_droite, on doit
        # vider main_gauche. On le détecte via l'item_definition de la
        # cible main_droite.
        md = EquipmentSlot.MAIN_HAND.value
        mg = EquipmentSlot.OFF_HAND.value
        target_md = next(
            (it for it in saved_set.items if it.slot == md), None,
        )
        is_target_md_two_handed = bool(
            target_md and target_md.item_definition.requires_two_hands
        )
        if is_target_md_two_handed:
            # Si jamais le set a aussi un main_gauche, on l'ignore (bug?)
            plan.pop(mg, None)

        already_ok: dict[str, int] = {e.slot: e.item_definition.id for e in equipped}

        changes: list[tuple[str, int]] = []
        kept = 0
        for slot, target_id in plan.items():
            current_id = already_ok.get(slot)
            if current_id == target_id:
                kept += 1
                continue
            self.equipment_repository.unequip_slot(player_id, slot)
            self.equipment_repository.equip_item(
                player_id=player_id,
                item_definition_id=target_id,
                slot=slot,
            )
            changes.append((slot, target_id))

        # Si target_md est 2-mains : vide main_gauche au cas où il y avait
        # une pièce hors-set qui traînait
        if is_target_md_two_handed:
            self.equipment_repository.unequip_slot(player_id, mg)

        if not changes:
            msg = f"✨ Set **{cleaned}** déjà équipé — aucun changement."
        else:
            msg = (
                f"✅ Set **{cleaned}** équipé : "
                f"{len(changes)} pièce(s) changée(s), {kept} conservée(s)."
            )

        return EquipSetResult(
            success=True, message=msg,
            equipped_changes=changes, kept_pieces=kept,
        )


@dataclass
class UnequipAllResult:
    success: bool
    message: str
    slots_cleared: list[str] = field(default_factory=list)


class UnequipAllUseCase:
    """Vide tous les slots d'équipement du joueur."""

    def __init__(
        self,
        player_repository: PlayerRepository,
        equipment_repository: EquipmentRepository,
    ) -> None:
        self.player_repository = player_repository
        self.equipment_repository = equipment_repository

    def execute(
        self, discord_id: int, username: str, display_name: str,
    ) -> UnequipAllResult:
        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id, username=username, display_name=display_name,
        )
        equipped = self.equipment_repository.list_by_player_id(profile.player.id)
        if not equipped:
            return UnequipAllResult(
                success=False,
                message="❌ Aucun équipement à retirer (tous les slots sont déjà vides).",
            )
        cleared: list[str] = []
        for e in equipped:
            self.equipment_repository.unequip_slot(profile.player.id, e.slot)
            cleared.append(e.slot)
        return UnequipAllResult(
            success=True,
            message=f"🧹 {len(cleared)} pièce(s) retirée(s) (tous slots vidés).",
            slots_cleared=cleared,
        )
