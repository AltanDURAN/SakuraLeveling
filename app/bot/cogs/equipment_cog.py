"""Inventaire, équipement et consommables : `/inventaire`, `/equipement`,
`/equipement_liste`, `/equiper`, `/desequiper`, les tenues (`/creer_set`,
`/equiper_set`, `/supprimer_set`) et `/utiliser`.

Découpé de `player_cog.py` le 26/10/2026 (roadmap N6). La fusion passe par
les PNJ (`/forgeron`), les potions par `/alchimiste` — cf. artisan_cog.
"""

import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from app.application.services.set_bonus_resolver import resolve_set_bonuses
from app.application.services.player_stats_resolver import resolve_player_stats
from app.application.use_cases.use_consumable import UseConsumableUseCase
from app.application.use_cases.equip_item import EquipItemUseCase, plan_equip
from app.bot.views.equipment_view import EquipmentView
from app.bot.views.inventory_view import InventoryView
from app.domain.services.stats_service import StatsService
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session
from app.shared.enums import EQUIPMENT_SLOT_LABELS, SLOT_LABELS
from app.infrastructure.db.repositories.player_health_repository import PlayerHealthRepository
from app.bot.cogs._mixins import BetaChannelOnlyMixin, PlayerLookupMixin


class EquipmentCog(PlayerLookupMixin, BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="inventaire", description="Afficher un inventaire")
    @app_commands.describe(target="Joueur dont afficher l'inventaire (par défaut : vous)")
    async def inventory(
        self,
        interaction: discord.Interaction,
        target: discord.Member | None = None,
    ) -> None:
        with get_db_session() as session:
            profile, target_member = self._resolve_profile(interaction, target, session)
            if profile is None:
                await self._send_no_profile_error(interaction, target_member)
                return

            inventory_repository = InventoryRepository(session)
            items = inventory_repository.list_by_player_id(profile.player.id)

        view = InventoryView(target_member.display_name, items)
        await interaction.response.send_message(embed=view._build_embed(), view=view)

    @app_commands.command(
        name="equipement",
        description="Afficher l'équipement en image (2 pages : emplacements / résumé)",
    )
    @app_commands.describe(target="Joueur dont afficher l'équipement (par défaut : vous)")
    async def equipment(
        self,
        interaction: discord.Interaction,
        target: discord.Member | None = None,
    ) -> None:
        await interaction.response.defer()
        from app.bot.views.equipment_image_view import EquipmentImageView

        with get_db_session() as session:
            profile, target_member = self._resolve_profile(interaction, target, session)
            if profile is None:
                await self._send_no_profile_error(interaction, target_member)
                return

            equipment_repository = EquipmentRepository(session)
            equipment_items = equipment_repository.list_by_player_id(profile.player.id)
            set_bonuses = resolve_set_bonuses(equipment_items, profile.player.panoplie_bonus)

        try:
            view = EquipmentImageView(
                player_id=profile.player.id,
                player_name=target_member.display_name,
                equipped_items=equipment_items,
                set_bonuses=set_bonuses,
                timeout=600.0,
            )
            embed, file = await asyncio.to_thread(view.render_current_page)
            await interaction.followup.send(embed=embed, file=file, view=view)
        except Exception as _e:
            # Fallback historique : embed texte 2 pages si Pillow plante
            import logging
            logging.getLogger(__name__).warning(
                "Equipment image render failed, falling back to text embed: %s",
                _e, exc_info=True,
            )
            fallback = EquipmentView(
                target_name=target_member.display_name,
                equipped_items=equipment_items,
                timeout=600.0,
            )
            await interaction.followup.send(
                embed=fallback.current_embed, view=fallback,
            )

    @app_commands.command(
        name="equipement_liste",
        description="Liste les équipements possédés par catégorie (équipés ou non)",
    )
    @app_commands.describe(target="Joueur ciblé (par défaut : vous)")
    async def equipement_list(
        self,
        interaction: discord.Interaction,
        target: discord.Member | None = None,
    ) -> None:
        from app.bot.views.equipment_list_view import EquipmentListView

        await interaction.response.defer()
        with get_db_session() as session:
            profile, target_member = self._resolve_profile(interaction, target, session)
            if profile is None:
                await self._send_no_profile_error(interaction, target_member)
                return

            from app.infrastructure.db.repositories.gear_repository import GearRepository

            items = GearRepository(session).list_owned(profile.player.id)
            equipped = EquipmentRepository(session).list_by_player_id(profile.player.id)

        view = EquipmentListView(
            player_id=profile.player.id,
            display_name=target_member.display_name,
            items=items,
            equipped=equipped,
        )
        embed, file, _, _ = await asyncio.to_thread(view.render_current)
        await interaction.followup.send(embed=embed, file=file, view=view)

    @app_commands.command(name="equiper", description="Équiper une de tes pièces d'équipement")
    @app_commands.describe(piece="La pièce à porter (autocomplétion : tes copies libres, les plus rares d'abord)")
    async def equip(
        self,
        interaction: discord.Interaction,
        piece: str,
    ) -> None:
        from app.application.use_cases.equip_item import rarity_label
        from app.bot.views.equip_confirm_view import (
            EquipConfirmView,
            build_equip_confirm_embed,
            compute_stats_diff,
        )
        from app.domain.entities.player_equipment_item import PlayerEquipmentItem
        from app.infrastructure.db.repositories.gear_repository import GearRepository

        # defer() AVANT le travail lourd (jusqu'à 2 calculs de stats complets) :
        # évite "Unknown interaction" si la DB est chargée.
        await interaction.response.defer()

        with get_db_session() as session:
            profile = PlayerRepository(session).get_or_create_by_discord_id(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )
            equipment_repository = EquipmentRepository(session)
            owned = GearRepository(session).list_owned(profile.player.id)

            # Valeur d'autocomplétion « gear:<id> », sinon un code ou un nom
            # tapé à la main : on prend alors la meilleure copie libre.
            gear = None
            if piece.startswith("gear:") and piece[5:].isdigit():
                gear = next((g for g in owned if g.id == int(piece[5:])), None)
            else:
                wanted = piece.strip().lower()
                gear = next((g for g in owned if not g.equipped and wanted in (
                    g.item_definition.code.lower(), g.item_definition.name.lower())), None)
            if gear is None:
                await interaction.followup.send(
                    "❌ Tu ne possèdes pas cette pièce (ou toutes ses copies sont déjà portées).",
                    ephemeral=True,
                )
                return

            item_def = gear.item_definition
            current_equipment = equipment_repository.list_by_player_id(profile.player.id)
            same = next((e for e in current_equipment if e.item_definition.id == item_def.id), None)
            if same is not None:
                target_slot, freed = same.slot, ()
            else:
                # Même décision que le use case, via la fonction pure partagée.
                plan = plan_equip(item_def, {e.slot: e.item_definition for e in current_equipment})
                if plan is None:
                    await interaction.followup.send(
                        f"❌ **{item_def.name}** n'a pas d'emplacement valide.", ephemeral=True,
                    )
                    return
                target_slot, freed = plan.target_slot, plan.freed_slots

            current_in_slot = next((e for e in current_equipment if e.slot == target_slot), None)

            # Emplacement libre : on équipe directement.
            if current_in_slot is None:
                result = EquipItemUseCase(
                    player_repository=PlayerRepository(session),
                    inventory_repository=InventoryRepository(session),
                    equipment_repository=equipment_repository,
                ).execute(
                    discord_id=interaction.user.id,
                    username=interaction.user.name,
                    display_name=interaction.user.display_name,
                    gear_id=gear.id,
                )
                if not result.success:
                    await interaction.followup.send(result.message, ephemeral=True)
                    return
                msg = result.message
                if result.unequipped_items:
                    msg += f"\n_Déséquipé : {', '.join(result.unequipped_items)}._"
                await interaction.followup.send(msg)
                return

            # Sinon : diff de stats avant / après (chaîne complète, titres compris).
            current_stats = resolve_player_stats(session, profile, current_equipment)
            simulated_new = PlayerEquipmentItem(
                id=-1, player_id=profile.player.id, slot=target_slot,
                item_definition=item_def, created_at=current_in_slot.created_at,
                updated_at=current_in_slot.updated_at, rarity=gear.rarity,
                forge_level=gear.forge_level, gear_id=gear.id,
            )
            dropped = {target_slot, *freed}
            simulated = [e for e in current_equipment if e.slot not in dropped] + [simulated_new]
            new_stats = resolve_player_stats(session, profile, simulated)
            replacing = (f"{current_in_slot.item_definition.name} "
                         f"({rarity_label(current_in_slot.rarity)})")
            label = f"{item_def.name} ({rarity_label(gear.rarity)})"

        embed = build_equip_confirm_embed(
            item_name=label, slot=target_slot, replacing_name=replacing,
            diffs=compute_stats_diff(current_stats, new_stats),
        )
        view = EquipConfirmView(
            author_id=interaction.user.id,
            discord_id=interaction.user.id,
            username=interaction.user.name,
            display_name=interaction.user.display_name,
            gear_id=gear.id,
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @equip.autocomplete("piece")
    async def equip_item_code_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Tes copies LIBRES, les plus rares d'abord : une entrée par (pièce,
        rareté), avec le niveau de forge sacrée le plus haut de ces copies."""
        from app.domain.services.gear_service import RARITY_EMOJIS, RARITY_LABELS
        from app.infrastructure.db.repositories.gear_repository import GearRepository

        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(interaction.user.id)
            if profile is None:
                return []
            owned = GearRepository(session).list_owned(profile.player.id)

        current_lower = current.lower()
        seen: set[tuple[int, str]] = set()
        choices: list[app_commands.Choice[str]] = []
        for g in owned:  # déjà triées : rareté puis forge décroissantes
            d = g.item_definition
            key = (d.id, g.rarity)
            if g.equipped or key in seen:
                continue
            if current_lower not in d.name.lower() and current_lower not in d.code.lower():
                continue
            seen.add(key)
            forge = f" +{g.forge_level}" if g.forge_level else ""
            slot = EQUIPMENT_SLOT_LABELS.get(d.equipment_slot, d.equipment_slot)
            choices.append(app_commands.Choice(
                name=f"{RARITY_EMOJIS.get(g.rarity, '')} {d.name} — "
                     f"{RARITY_LABELS.get(g.rarity, g.rarity).lower()}{forge} ({slot})"[:100],
                value=f"gear:{g.id}",
            ))
            if len(choices) >= 25:
                break
        return choices

    @app_commands.command(
        name="desequiper",
        description="Déséquiper un emplacement (ou tout, avec slot=all)",
    )
    @app_commands.describe(slot="`all` pour tout retirer, sinon le slot ciblé (autocomplete)")
    async def unequip(
        self,
        interaction: discord.Interaction,
        slot: str,
    ) -> None:
        # Cas spécial : slot="all" → vide tous les emplacements
        if slot.strip().lower() == "all":
            from app.application.use_cases.equipment_sets import (
                UnequipAllUseCase,
            )

            with get_db_session() as session:
                use_case = UnequipAllUseCase(
                    player_repository=PlayerRepository(session),
                    equipment_repository=EquipmentRepository(session),
                )
                result = use_case.execute(
                    discord_id=interaction.user.id,
                    username=interaction.user.name,
                    display_name=interaction.user.display_name,
                )
            await interaction.response.send_message(
                result.message, ephemeral=not result.success,
            )
            return

        with get_db_session() as session:
            profile = PlayerRepository(session).get_or_create_by_discord_id(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )
            equipment_repository = EquipmentRepository(session)
            current = equipment_repository.get_slot(profile.player.id, slot)
            if current is None:
                await interaction.response.send_message(
                    f"❌ Aucun équipement dans **{SLOT_LABELS.get(slot, slot)}**.",
                    ephemeral=True,
                )
                return

            item_name = current.item_definition.name
            was_two_hands = bool(current.item_definition.requires_two_hands)
            equipment_repository.unequip_slot(profile.player.id, slot)

        msg = f"✅ **{item_name}** déséquipé de **{SLOT_LABELS.get(slot, slot)}**."
        if was_two_hands:
            msg += "\n_(Pièce à 2 mains : vos deux emplacements d'arme sont de nouveau libres.)_"
        await interaction.response.send_message(msg)

    @unequip.autocomplete("slot")
    async def unequip_slot_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Liste les slots actuellement occupés + l'option spéciale 'all'."""
        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(interaction.user.id)
            if profile is None:
                return []

            equipped = EquipmentRepository(session).list_by_player_id(profile.player.id)

        current_lower = current.lower()
        choices: list[app_commands.Choice[str]] = []

        # Option spéciale : tout déséquiper d'un coup (en tête de liste)
        all_label = f"all — Tout retirer ({len(equipped)} pièce(s))"
        if not current_lower or current_lower in "all":
            choices.append(app_commands.Choice(name=all_label[:100], value="all"))

        for entry in equipped:
            slot_label = SLOT_LABELS.get(entry.slot, entry.slot)
            label = f"{slot_label} — {entry.item_definition.name}"[:100]
            if current_lower and current_lower not in entry.slot.lower():
                continue
            choices.append(app_commands.Choice(name=label, value=entry.slot))
            if len(choices) >= 25:
                break
        return choices

    @app_commands.command(
        name="creer_set",
        description="Sauvegarde l'équipement actuel sous un nom (loadout réutilisable)",
    )
    @app_commands.describe(nom="Nom du set (max 50 caractères, libre)")
    async def create_set(
        self, interaction: discord.Interaction, nom: str,
    ) -> None:
        from app.application.use_cases.equipment_sets import (
            CreateEquipmentSetUseCase,
        )
        from app.infrastructure.db.repositories.equipment_set_repository import (
            EquipmentSetRepository,
        )

        with get_db_session() as session:
            use_case = CreateEquipmentSetUseCase(
                player_repository=PlayerRepository(session),
                equipment_repository=EquipmentRepository(session),
                equipment_set_repository=EquipmentSetRepository(session),
            )
            result = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
                name=nom,
            )
        await interaction.response.send_message(
            result.message, ephemeral=not result.success,
        )

    @app_commands.command(
        name="supprimer_set",
        description="Supprime un set d'équipement sauvegardé",
    )
    @app_commands.describe(nom="Nom du set à supprimer (autocomplete)")
    async def delete_set(
        self, interaction: discord.Interaction, nom: str,
    ) -> None:
        from app.application.use_cases.equipment_sets import (
            DeleteEquipmentSetUseCase,
        )
        from app.infrastructure.db.repositories.equipment_set_repository import (
            EquipmentSetRepository,
        )

        with get_db_session() as session:
            use_case = DeleteEquipmentSetUseCase(
                player_repository=PlayerRepository(session),
                equipment_set_repository=EquipmentSetRepository(session),
            )
            result = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
                name=nom,
            )
        await interaction.response.send_message(
            result.message, ephemeral=not result.success,
        )

    @app_commands.command(
        name="equiper_set",
        description="Applique un set d'équipement sauvegardé",
    )
    @app_commands.describe(nom="Nom du set à équiper (autocomplete)")
    async def equip_set(
        self, interaction: discord.Interaction, nom: str,
    ) -> None:
        from app.application.use_cases.equipment_sets import (
            EquipSavedSetUseCase,
        )
        from app.infrastructure.db.repositories.equipment_set_repository import (
            EquipmentSetRepository,
        )

        await interaction.response.defer()
        with get_db_session() as session:
            use_case = EquipSavedSetUseCase(
                player_repository=PlayerRepository(session),
                equipment_repository=EquipmentRepository(session),
                equipment_set_repository=EquipmentSetRepository(session),
                inventory_repository=InventoryRepository(session),
            )
            result = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
                name=nom,
            )
        await interaction.followup.send(
            result.message, ephemeral=not result.success,
        )

    @delete_set.autocomplete("nom")
    @equip_set.autocomplete("nom")
    async def _set_name_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        from app.infrastructure.db.repositories.equipment_set_repository import (
            EquipmentSetRepository,
        )

        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(
                interaction.user.id,
            )
            if profile is None:
                return []
            sets = EquipmentSetRepository(session).list_for_player(
                profile.player.id,
            )

        current_lower = current.lower()
        choices: list[app_commands.Choice[str]] = []
        for s in sets:
            if current_lower and current_lower not in s.name.lower():
                continue
            label = f"{s.name} ({len(s.items)} pièces)"[:100]
            choices.append(app_commands.Choice(name=label, value=s.name))
            if len(choices) >= 25:
                break
        return choices

    @app_commands.command(
        name="utiliser",
        description="Utiliser un consommable de votre inventaire (potion, etc.)",
    )
    @app_commands.describe(item_code="Code du consommable (autocomplete sur votre inventaire)")
    async def use(self, interaction: discord.Interaction, item_code: str) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.application.use_cases.use_consumable import UseContext
        from app.bot.rank_roles import current_rank

        encounter_cog = self.bot.get_cog("EncounterCog")
        context = UseContext(
            player_rank=current_rank(interaction.user) if isinstance(interaction.user, discord.Member) else None,
            summon_elite=encounter_cog.queue_summoned_elite if encounter_cog is not None else None,
        )
        with get_db_session() as session:
            use_case = UseConsumableUseCase(
                player_repository=PlayerRepository(session),
                item_repository=ItemRepository(session),
                inventory_repository=InventoryRepository(session),
                equipment_repository=EquipmentRepository(session),
                skill_allocation_repository=PlayerSkillAllocationRepository(session),
                health_repository=PlayerHealthRepository(session),
                stats_service=StatsService(),
            )
            result = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
                item_code=item_code,
                context=context,
            )
        await interaction.followup.send(result.message, ephemeral=True)
        if result.announce and result.announce_channel_id:
            channel = self.bot.get_channel(result.announce_channel_id)
            if channel is not None:
                try:
                    await channel.send(result.announce)
                except discord.HTTPException:
                    pass

    @use.autocomplete("item_code")
    async def use_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete sur les consommables actuellement en inventaire."""
        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(interaction.user.id)
            if profile is None:
                return []
            inventory = InventoryRepository(session).list_by_player_id(profile.player.id)
        current_lower = current.lower()
        choices: list[app_commands.Choice[str]] = []
        for inv_item in inventory:
            item = inv_item.item_definition
            if item.category != "consumable":
                continue
            if (
                current_lower in item.code.lower()
                or current_lower in item.name.lower()
            ):
                choices.append(
                    app_commands.Choice(
                        name=f"{item.name} (×{inv_item.quantity})",
                        value=item.code,
                    )
                )
            if len(choices) >= 25:
                break
        return choices


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EquipmentCog(bot))
