"""Fusion de rareté chez l'artisan (équipement v2).

2 copies de la MÊME pièce, de la MÊME rareté + or + matériaux de la famille du
monstre qui la lâche → 1 copie de la rareté suivante. Borak fusionne les armes,
boucliers, têtes, corps et accessoires (`categories` d'artisans.json) ; Elna
est devenue alchimiste le 26/10/2026.

  • la nouvelle copie garde le niveau de FORGE SACRÉE le plus haut des deux ;
  • si l'une des copies était portée, la nouvelle prend sa place ;
  • légendaire et mythique ne se fusionnent pas ;
  • chaque fusion compte comme un travail terminé pour la MAÎTRISE de
    l'artisan (sa remise s'applique à l'or, pas aux matériaux).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.entities.artisan import ArtisanDefinition
from app.domain.services.artisan_service import ArtisanService
from app.domain.services.gear_service import (
    RARITY_LABELS,
    fusion_cost,
    gear_stats,
    next_rarity,
    rarity_index,
)
from app.infrastructure.db.repositories.gear_repository import GearRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.work_order_repository import WorkOrderRepository


@dataclass(frozen=True)
class FusionCandidate:
    """Une pièce (et une rareté) que cet artisan peut fusionner."""
    item_code: str
    item_name: str
    category: str
    rarity: str
    copies: int


@dataclass
class FusionPreview:
    item_code: str
    item_name: str
    item_category: str
    rarity: str
    target_rarity: str | None
    copies: int
    stats_now: dict
    stats_next: dict
    gold_cost: int
    player_gold: int
    material_code: str
    material_name: str
    material_needed: int
    material_owned: int

    @property
    def can_fuse(self) -> bool:
        return not self.blocking_reason

    @property
    def blocking_reason(self) -> str:
        if self.target_rarity is None:
            return f"Une pièce {RARITY_LABELS.get(self.rarity, self.rarity).lower()} ne se fusionne plus."
        if self.copies < 2:
            return (f"Il faut 2 copies {RARITY_LABELS[self.rarity].lower()} de cette pièce "
                    f"— tu en as {self.copies}.")
        if self.material_needed and self.material_owned < self.material_needed:
            return (f"Il te manque {self.material_needed - self.material_owned} "
                    f"× {self.material_name}.")
        if self.player_gold < self.gold_cost:
            return f"Il te manque {self.gold_cost - self.player_gold} or."
        return ""


@dataclass
class FusionResult:
    success: bool
    message: str
    new_rarity: str | None = None


class FuseGearUseCase:
    def __init__(self, session, artisan_service: ArtisanService) -> None:
        self.session = session
        self.players = PlayerRepository(session)
        self.gear = GearRepository(session)
        self.inventory = InventoryRepository(session)
        self.items = ItemRepository(session)
        self.orders = WorkOrderRepository(session)
        self.artisans = artisan_service

    # ---------------------------------------------------------- lecture --
    def candidates(self, definition: ArtisanDefinition, player_id: int) -> list[FusionCandidate]:
        groups: dict[tuple[str, str], list] = {}
        for g in self.gear.list_owned(player_id):
            if g.item_definition.category in definition.categories:
                groups.setdefault((g.item_definition.code, g.rarity), []).append(g)
        out = [
            FusionCandidate(code, copies[0].item_definition.name,
                            copies[0].item_definition.category, rarity, len(copies))
            for (code, rarity), copies in groups.items()
        ]
        out.sort(key=lambda c: (c.category, c.item_name.lower(), -rarity_index(c.rarity)))
        return out

    def _material_for(self, item_code: str) -> tuple[str, str]:
        """Matériau de la famille du monstre qui lâche cette pièce."""
        from app.infrastructure.db.repositories.mob_repository import MobRepository
        from app.infrastructure.loot.family_drop_loader import get_family_drops

        mob = next((m for m in MobRepository(self.session).list_all()
                    if m.gear_item_code == item_code), None)
        if mob is None:
            return "", ""
        code = (get_family_drops().get(mob.family) or {}).get("item_code", "")
        item = self.items.get_by_code(code) if code else None
        return (code, item.name) if item else ("", "")

    def _discounted_gold(self, definition: ArtisanDefinition, player_id: int, gold: int) -> int:
        tier = self.artisans.tier_for(definition, self.orders.orders_completed(player_id, definition.code))
        return round(gold * (1 - tier.gold_discount_pct / 100))

    def preview(self, definition: ArtisanDefinition, player_id: int,
                item_code: str, rarity: str) -> FusionPreview | None:
        copies = [g for g in self.gear.list_owned(player_id)
                  if g.item_definition.code == item_code and g.rarity == rarity]
        if not copies or copies[0].item_definition.category not in definition.categories:
            return None
        item = copies[0].item_definition
        target = next_rarity(rarity)
        cost = fusion_cost(rarity) or (0, 0)
        material_code, material_name = self._material_for(item_code)
        owned_material = 0
        if material_code:
            owned_material = sum(i.quantity for i in self.inventory.list_by_player_id(player_id)
                                 if i.item_definition.code == material_code)
        profile = self.players.get_profile_by_player_id(player_id)
        forge = max(g.forge_level for g in copies[:2])
        return FusionPreview(
            item_code=item.code, item_name=item.name, item_category=item.category,
            rarity=rarity, target_rarity=target.value if target else None,
            copies=len(copies),
            stats_now=gear_stats(item.stat_bonuses, rarity, forge),
            stats_next=gear_stats(item.stat_bonuses, target.value, forge) if target else {},
            gold_cost=self._discounted_gold(definition, player_id, cost[0]),
            player_gold=profile.resources.gold if profile else 0,
            material_code=material_code, material_name=material_name,
            material_needed=cost[1] if material_code else 0,
            material_owned=owned_material,
        )

    # --------------------------------------------------------- écriture --
    def fuse(self, definition: ArtisanDefinition, player_id: int,
             item_code: str, rarity: str) -> FusionResult:
        # Tout est revérifié ici : l'aperçu a pu être affiché il y a des minutes.
        preview = self.preview(definition, player_id, item_code, rarity)
        if preview is None:
            return FusionResult(False, f"❌ {definition.name} ne travaille pas cette pièce, ou tu ne l'as plus.")
        if not preview.can_fuse:
            return FusionResult(False, f"❌ {preview.blocking_reason}")

        copies = [g for g in self.gear.list_owned(player_id)
                  if g.item_definition.code == item_code and g.rarity == rarity]
        # On consomme d'abord une copie PORTÉE s'il y en a une : la nouvelle
        # reprend son emplacement, le joueur n'a rien à rééquiper.
        copies.sort(key=lambda g: (not g.equipped, -g.forge_level))
        a, b = copies[0], copies[1]
        slot = a.equipped_slot or b.equipped_slot
        forge = max(a.forge_level, b.forge_level)

        # Atomique : les pièces d'abord (non validées), puis les matériaux dont
        # la validation emporte tout ; s'ils manquent, on annule le tout.
        self.gear.remove(a.id, commit=False)
        self.gear.remove(b.id, commit=False)
        self.session.flush()
        new = self.gear.add(player_id, a.item_definition.id, preview.target_rarity,
                            forge_level=forge, source="fusion", commit=False)
        if slot:
            self.gear.set_slot(new.id, slot, commit=False)
        if preview.material_needed:
            material = self.items.get_by_code(preview.material_code)
            if material is None or not self.inventory.remove_item(
                player_id, material.id, preview.material_needed,
            ):
                self.session.rollback()
                return FusionResult(False, f"❌ Il te manque des {preview.material_name}.")
        if preview.gold_cost:
            self.players.add_gold(player_id, -preview.gold_cost)
        self.orders.increment_mastery(player_id, definition.code)
        self.session.commit()
        label = RARITY_LABELS[preview.target_rarity].lower()
        return FusionResult(
            True,
            f"✨ **{preview.item_name}** devient **{label}** "
            f"({preview.gold_cost} or, {preview.material_needed} × {preview.material_name})."
            + (" Elle reprend sa place sur toi." if slot else ""),
            new_rarity=preview.target_rarity,
        )
