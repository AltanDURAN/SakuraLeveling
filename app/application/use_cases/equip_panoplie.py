"""Use case `/equip_panoplie <famille> [option]` : équipe en un coup
tous les slots d'une panoplie complète.

Layout d'une panoplie (16 items au total) :
- 10 slots non-main : casque, plastron, jambières, bottes, collier,
  bracelet, bague, ceinture, cape, boucle d'oreille
- 2 slots main : peuvent contenir, selon l'option :
  - `defaut`           : 1 arme légère (1H) + 1 bouclier léger (1H)
  - `double_armes`     : 2 armes légères différentes (1H)
  - `double_boucliers` : 2 boucliers légers différents (1H)
  - `arme_lourde`      : 1 arme 2-mains (occupe main_droite, verrouille
    main_gauche)
  - `bouclier_lourd`   : 1 bouclier 2-mains (idem)

Conditions :
- Le joueur possède (en inventaire ET/OU déjà équipé) au moins 12/12
  pièces de la famille (les 2-mains comptent pour 2).
- Au moins une pièce existe pour CHAQUE slot non-main.
- Pour les slots main : les items requis par l'option sont disponibles
  (ex : `arme_lourde` exige une arme 2-mains de la famille).

Comportement :
- Pièces de la bonne famille déjà équipées au bon slot/item → conservées.
- Slots tenus par autre chose → déséquipés puis remplacés.
- 2-mains : main_gauche est forcée vide après équipement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.domain.entities.player_equipment_item import PlayerEquipmentItem
from app.domain.entities.player_inventory_item import PlayerInventoryItem
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.sets.set_loader import (
    list_definitions as list_set_definitions,
)
from app.shared.enums import EquipmentSlot, PRIMARY_SLOTS, SECONDARY_SLOTS


# Options de configuration des mains.
EquipPanoplieOption = Literal[
    "defaut", "double_armes", "double_boucliers",
    "arme_lourde", "bouclier_lourd",
]
_VALID_OPTIONS = {
    "defaut", "double_armes", "double_boucliers",
    "arme_lourde", "bouclier_lourd",
}

_PANOPLIE_TOTAL_SLOTS = 12
_MD = EquipmentSlot.MAIN_HAND.value
_MG = EquipmentSlot.OFF_HAND.value


def _piece_weight(item) -> int:
    """1 pour 1-main / armure / accessoire, 2 pour 2-mains."""
    return 2 if getattr(item, "requires_two_hands", False) else 1


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
        option: str | None = None,
    ) -> EquipPanoplieResult:
        family = (family or "").strip()
        option = (option or "defaut").strip().lower()
        if option not in _VALID_OPTIONS:
            return EquipPanoplieResult(
                success=False,
                message=(
                    f"❌ Option `{option}` invalide. "
                    f"Choisissez parmi : {', '.join(sorted(_VALID_OPTIONS))}."
                ),
            )
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

        family_equipped = [
            e for e in equipped
            if (e.item_definition.family or "").strip() == family
        ]
        family_inventory = [
            i for i in inventory
            if (i.item_definition.family or "").strip() == family
        ]

        # ----- Comptage : 12/12 pondéré ? -----
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
                    "(les armes/boucliers à 2 mains comptent pour 2)."
                ),
            )

        # ----- Plan slot par slot -----
        all_slots = [s.value for s in (PRIMARY_SLOTS + SECONDARY_SLOTS)]
        plan, missing, error = self._build_plan(
            all_slots, family_equipped, family_inventory, option,
        )
        if error:
            return EquipPanoplieResult(
                success=False, message=error, missing_slots=missing,
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

        # ----- Exécution -----
        changes: list[tuple[str, str]] = []
        kept = 0

        already_ok: dict[str, PlayerEquipmentItem] = {}
        for e in family_equipped:
            already_ok[e.slot] = e

        # Détecte si une 2-mains est dans le plan pour main_droite
        md_target_id = plan.get(_MD)
        md_target_is_2h = False
        if md_target_id is not None:
            for source in (family_equipped, family_inventory):
                for entry in source:
                    if entry.item_definition.id == md_target_id:
                        md_target_is_2h = entry.item_definition.requires_two_hands
                        break

        for slot, target_def_id in plan.items():
            current = already_ok.get(slot)
            if current is not None and current.item_definition.id == target_def_id:
                kept += 1
                continue
            existing = self.equipment_repository.get_slot(player_id, slot)
            if existing is not None:
                self.equipment_repository.unequip_slot(player_id, slot)
            self.equipment_repository.equip_item(
                player_id=player_id,
                item_definition_id=target_def_id,
                slot=slot,
            )
            changes.append((slot, target_def_id))

        # Si la pièce de main_droite est 2-mains : vide main_gauche
        if md_target_is_2h:
            existing_off = self.equipment_repository.get_slot(
                player_id, _MG,
            )
            if existing_off is not None:
                self.equipment_repository.unequip_slot(player_id, _MG)

        family_label = set_def.get("name", family)
        family_icon = set_def.get("icon", "✨")
        suffix = "" if option == "defaut" else f" — option `{option}`"
        if not changes:
            msg = (
                f"✨ Panoplie **{family_icon} {family_label}**{suffix} "
                "déjà équipée — aucun changement."
            )
        else:
            msg = (
                f"✅ Panoplie **{family_icon} {family_label}**{suffix} "
                f"équipée. {len(changes)} pièce(s) changée(s), "
                f"{kept} conservée(s)."
            )

        return EquipPanoplieResult(
            success=True,
            message=msg,
            equipped_changes=changes,
            kept_pieces=kept,
        )

    # ------------------------------------------------------------------
    # Plan
    # ------------------------------------------------------------------
    def _build_plan(
        self,
        all_slots: list[str],
        family_equipped: list[PlayerEquipmentItem],
        family_inventory: list[PlayerInventoryItem],
        option: str,
    ) -> tuple[dict[str, int], list[str], str | None]:
        """Construit un plan {slot: item_definition_id}.

        Retourne (plan, missing_slots, error_message).
        Si error_message est non-None, le caller doit retourner un échec
        sans tenter d'équiper (option non satisfaite par les items dispo).
        """
        # Index des candidats par slot. Priorité aux items déjà équipés
        # (minimise les écritures DB) puis aux items en inventaire.
        by_slot: dict[str, list] = {}
        for e in family_equipped:
            canonical = e.item_definition.equipment_slot or e.slot
            by_slot.setdefault(canonical, []).append(e.item_definition)
        for i in family_inventory:
            slot = i.item_definition.equipment_slot
            if slot:
                by_slot.setdefault(slot, []).append(i.item_definition)

        # Candidats main : tous les items dont equipement_slot ∈ {md, mg}.
        # (Avec la nouvelle convention, tous les items main ont slot=md.)
        main_candidates = list(by_slot.get(_MD, [])) + [
            it for it in by_slot.get(_MG, [])
            if it not in by_slot.get(_MD, [])
        ]

        weapons_1h = [
            it for it in main_candidates
            if it.category == "weapon" and not it.requires_two_hands
        ]
        shields_1h = [
            it for it in main_candidates
            if it.category == "shield" and not it.requires_two_hands
        ]
        weapons_2h = [
            it for it in main_candidates
            if it.category == "weapon" and it.requires_two_hands
        ]
        shields_2h = [
            it for it in main_candidates
            if it.category == "shield" and it.requires_two_hands
        ]

        plan: dict[str, int] = {}
        missing: list[str] = []
        error: str | None = None

        # ---- Slots main selon l'option ----
        if option == "defaut":
            if not weapons_1h or not shields_1h:
                error = (
                    f"❌ Option `defaut` : il faut au moins 1 arme légère "
                    f"+ 1 bouclier léger de la famille (vous avez "
                    f"{len(weapons_1h)} arme(s) 1H, {len(shields_1h)} "
                    f"bouclier(s) 1H)."
                )
            else:
                plan[_MD] = weapons_1h[0].id
                plan[_MG] = shields_1h[0].id
        elif option == "double_armes":
            distinct_w = self._distinct_by_id(weapons_1h)
            if len(distinct_w) < 2:
                error = (
                    f"❌ Option `double_armes` : il faut 2 armes légères "
                    f"DIFFÉRENTES de la famille (vous avez "
                    f"{len(distinct_w)} arme(s) légère(s) unique(s))."
                )
            else:
                plan[_MD] = distinct_w[0].id
                plan[_MG] = distinct_w[1].id
        elif option == "double_boucliers":
            distinct_s = self._distinct_by_id(shields_1h)
            if len(distinct_s) < 2:
                error = (
                    f"❌ Option `double_boucliers` : il faut 2 boucliers "
                    f"légers DIFFÉRENTS de la famille (vous avez "
                    f"{len(distinct_s)} bouclier(s) léger(s) unique(s))."
                )
            else:
                plan[_MD] = distinct_s[0].id
                plan[_MG] = distinct_s[1].id
        elif option == "arme_lourde":
            if not weapons_2h:
                error = (
                    "❌ Option `arme_lourde` : aucune arme 2-mains "
                    "de la famille en votre possession."
                )
            else:
                plan[_MD] = weapons_2h[0].id
                # main_gauche reste vide (verrouillée par la 2-mains)
        elif option == "bouclier_lourd":
            if not shields_2h:
                error = (
                    "❌ Option `bouclier_lourd` : aucun bouclier 2-mains "
                    "de la famille en votre possession."
                )
            else:
                plan[_MD] = shields_2h[0].id

        if error:
            return plan, missing, error

        # ---- Slots non-main : 1 item de la famille par slot ----
        for slot in all_slots:
            if slot in (_MD, _MG):
                continue
            candidates = by_slot.get(slot, [])
            if not candidates:
                missing.append(slot)
                continue
            plan[slot] = candidates[0].id

        return plan, missing, None

    @staticmethod
    def _distinct_by_id(items: list) -> list:
        seen: set[int] = set()
        out: list = []
        for it in items:
            if it.id in seen:
                continue
            seen.add(it.id)
            out.append(it)
        return out
