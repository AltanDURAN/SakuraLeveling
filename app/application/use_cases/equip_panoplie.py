"""Use case `/equip_panoplie <famille>` : équipe en un coup tous les
slots d'une panoplie complète.

Conditions :
- Le joueur possède (en inventaire ET/OU déjà équipé) au moins 12/12
  pièces de la famille demandée. Les armes 2-mains comptent pour 2.
- Pour chacun des 12 slots, il existe au moins un item de la famille
  qui s'y équipe.

Comportement :
- Pièces déjà équipées de la bonne famille → conservées telles quelles.
- Slots tenus par des items hors famille → ils sont déséquipés (l'item
  retourne en inventaire via le repository).
- Si une 2-mains de la famille est sélectionnée pour `main_droite`,
  `main_gauche` est laissée vide (verrouillage 2-mains automatique).

Idempotent : appeler la commande deux fois de suite ne change rien la
seconde fois (aucune ligne touchée).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.entities.player_equipment_item import PlayerEquipmentItem
from app.domain.entities.player_inventory_item import PlayerInventoryItem
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.sets.set_loader import (
    list_definitions as list_set_definitions,
)
from app.shared.enums import EquipmentSlot, PRIMARY_SLOTS, SECONDARY_SLOTS


_PANOPLIE_TOTAL_SLOTS = 12


def _piece_weight(item) -> int:
    """1 pour 1-main / armure / accessoire, 2 pour arme 2-mains."""
    return 2 if getattr(item, "requires_two_hands", False) else 1


@dataclass
class EquipPanoplieResult:
    success: bool
    message: str
    equipped_changes: list[tuple[str, str]] = field(default_factory=list)
    # Slots non couverts si échec (ex : ["collier", "boucle_oreille"])
    missing_slots: list[str] = field(default_factory=list)
    # Pièces déjà équipées et conservées (info pour le retour utilisateur)
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
            return EquipPanoplieResult(
                success=False, message="❌ Nom de panoplie invalide.",
            )

        sets_def = list_set_definitions()
        set_def = sets_def.get(family)
        if set_def is None:
            return EquipPanoplieResult(
                success=False,
                message=f"❌ Panoplie `{family}` introuvable.",
            )

        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )
        player_id = profile.player.id

        equipped = self.equipment_repository.list_by_player_id(player_id)
        inventory = self.inventory_repository.list_by_player_id(player_id)

        # ----- Comptage : 12/12 ? -----
        family_equipped = [
            e for e in equipped
            if (e.item_definition.family or "").strip() == family
        ]
        family_inventory = [
            i for i in inventory
            if (i.item_definition.family or "").strip() == family
        ]

        weighted_owned = sum(
            _piece_weight(e.item_definition) for e in family_equipped
        ) + sum(
            _piece_weight(i.item_definition) * i.quantity
            for i in family_inventory
        )

        if weighted_owned < _PANOPLIE_TOTAL_SLOTS:
            family_label = set_def.get("name", family)
            return EquipPanoplieResult(
                success=False,
                message=(
                    f"❌ Panoplie **{family_label}** incomplète : "
                    f"vous avez **{weighted_owned}/12** pièces "
                    "(les armes à 2 mains comptent pour 2)."
                ),
            )

        # ----- Plan slot par slot -----
        all_slots = [s.value for s in (PRIMARY_SLOTS + SECONDARY_SLOTS)]
        plan, missing = self._build_plan(
            all_slots, family_equipped, family_inventory,
        )
        if missing:
            family_label = set_def.get("name", family)
            return EquipPanoplieResult(
                success=False,
                message=(
                    f"❌ Panoplie **{family_label}** : il manque une pièce "
                    f"pour le(s) slot(s) `{', '.join(missing)}`."
                ),
                missing_slots=missing,
            )

        # ----- Exécution : déséquipe le hors-famille, équipe la famille -----
        changes: list[tuple[str, str]] = []
        kept = 0

        # 1. Identifie les slots déjà OK (item famille au bon slot)
        already_ok: dict[str, PlayerEquipmentItem] = {}
        for e in family_equipped:
            already_ok[e.slot] = e

        # 2. Pour chaque slot du plan, applique le changement si nécessaire
        for slot, target_def_id in plan.items():
            current = already_ok.get(slot)
            if current is not None and current.item_definition.id == target_def_id:
                kept += 1
                continue
            # Slot avait autre chose → déséquipe d'abord
            existing = self.equipment_repository.get_slot(player_id, slot)
            if existing is not None:
                self.equipment_repository.unequip_slot(player_id, slot)
            self.equipment_repository.equip_item(
                player_id=player_id,
                item_definition_id=target_def_id,
                slot=slot,
            )
            changes.append((slot, target_def_id))

        # 3. Si une 2-mains a été équipée en main_droite, vide main_gauche
        md_after = self.equipment_repository.get_slot(
            player_id, EquipmentSlot.MAIN_HAND.value,
        )
        if (
            md_after is not None
            and md_after.item_definition.requires_two_hands
        ):
            existing_off = self.equipment_repository.get_slot(
                player_id, EquipmentSlot.OFF_HAND.value,
            )
            if existing_off is not None:
                self.equipment_repository.unequip_slot(
                    player_id, EquipmentSlot.OFF_HAND.value,
                )

        family_label = set_def.get("name", family)
        family_icon = set_def.get("icon", "✨")
        if not changes:
            msg = (
                f"✨ Panoplie **{family_icon} {family_label}** déjà équipée — "
                f"aucun changement."
            )
        else:
            msg = (
                f"✅ Panoplie **{family_icon} {family_label}** équipée. "
                f"{len(changes)} pièce(s) changée(s), {kept} conservée(s)."
            )

        return EquipPanoplieResult(
            success=True,
            message=msg,
            equipped_changes=changes,
            kept_pieces=kept,
        )

    def _build_plan(
        self,
        all_slots: list[str],
        family_equipped: list[PlayerEquipmentItem],
        family_inventory: list[PlayerInventoryItem],
    ) -> tuple[dict[str, int], list[str]]:
        """Construit un plan {slot: item_definition_id} couvrant les 12 slots.

        Stratégie :
        1. Si une 2-mains de la famille est dispo (équipée ou en inventaire),
           on la prend pour main_droite → main_gauche reste vide.
        2. Sinon, on prend le 1er candidat famille de chaque slot canonique.

        Renvoie (plan, missing_slots).
        """
        # Index des candidats par slot (équipés + inventaire). Priorité aux
        # déjà-équipés pour minimiser les changements.
        by_slot: dict[str, list] = {}
        for e in family_equipped:
            slot = e.item_definition.equipment_slot or e.slot
            by_slot.setdefault(slot, []).append(e.item_definition)
        for i in family_inventory:
            slot = i.item_definition.equipment_slot
            if slot:
                by_slot.setdefault(slot, []).append(i.item_definition)

        plan: dict[str, int] = {}
        missing: list[str] = []

        # Détection 2-mains dispo
        md = EquipmentSlot.MAIN_HAND.value
        mg = EquipmentSlot.OFF_HAND.value
        two_handers = [
            it for it in by_slot.get(md, [])
            if getattr(it, "requires_two_hands", False)
        ]

        for slot in all_slots:
            if slot == md and two_handers:
                plan[md] = two_handers[0].id
                continue
            if slot == mg and two_handers:
                # Verrouillé par la 2-mains, ne planifie rien
                continue
            candidates = by_slot.get(slot, [])
            # On ignore les 2-mains pour le slot main_droite quand on les
            # a déjà choisies (ou pas) pour éviter doublon.
            if slot == md:
                candidates = [
                    c for c in candidates
                    if not getattr(c, "requires_two_hands", False)
                ]
            if not candidates:
                missing.append(slot)
                continue
            plan[slot] = candidates[0].id

        return plan, missing
