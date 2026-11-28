"""Commandes `/admin` sur les objets et l'équipement d'un joueur (donner,
retirer, équiper, déséquiper) et leurs autocomplétions. Mixin d'`AdminCog`,
sorti d'`admin_cog.py` le 28/11/2026 (audit) : texte inchangé."""

import discord
from discord import app_commands
from app.application.services.admin_gear import give_gear, is_gear, take_gear
from app.application.use_cases.equip_item import EquipItemUseCase
from app.bot.checks.admin_check import admin_only
from app.shared.enums import EquipmentSlot
from app.domain.services.gear_service import gear_label
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.gear_repository import GearRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session
from app.bot.cogs.admin_group import _RARITY_CHOICES, admin


class AdminItemsMixin:
    @admin.command(name="give_item", description="Ajoute un objet à l'inventaire d'un joueur")
    @app_commands.describe(
        target="Joueur ciblé",
        item_code="Code de l'objet (ex : slime_gel)",
        quantity="Quantité à ajouter",
        rarity="Équipement : rareté des copies (commun par défaut)",
        forge="Équipement : niveau de forge sacrée (0-10)",
    )
    @app_commands.choices(rarity=_RARITY_CHOICES)
    @admin_only
    async def give_item(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        item_code: str,
        quantity: app_commands.Range[int, 1, 9999],
        rarity: str = "common",
        forge: app_commands.Range[int, 0, 10] = 0,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            item_repository = ItemRepository(session)
            inventory_repository = InventoryRepository(session)

            profile = player_repository.get_by_discord_id(target.id)
            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.",
                    ephemeral=True,
                )
                return

            item = item_repository.get_by_code(item_code)
            if item is None:
                await interaction.followup.send(
                    f"❌ Objet `{item_code}` introuvable.",
                    ephemeral=True,
                )
                return

            if is_gear(item):
                quantity = give_gear(session, profile.player.id, item, quantity, rarity, forge)
                await interaction.followup.send(
                    f"✅ {quantity}× **{gear_label(item.name, rarity, forge)}** "
                    f"donné à {target.mention}.",
                    ephemeral=True,
                )
                return

            inventory_repository.add_item(
                player_id=profile.player.id,
                item_definition_id=item.id,
                quantity=quantity,
            )

        await interaction.followup.send(
            f"✅ {quantity}× **{item.name}** ajouté à l'inventaire de {target.mention}.",
            ephemeral=True,
        )

    @admin.command(name="remove_item", description="Retire un objet de l'inventaire d'un joueur")
    @app_commands.describe(
        target="Joueur ciblé",
        item_code="Code de l'objet",
        quantity="Quantité à retirer",
    )
    @admin_only
    async def remove_item(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        item_code: str,
        quantity: app_commands.Range[int, 1, 9999],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            item_repository = ItemRepository(session)
            inventory_repository = InventoryRepository(session)

            profile = player_repository.get_by_discord_id(target.id)
            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.",
                    ephemeral=True,
                )
                return

            item = item_repository.get_by_code(item_code)
            if item is None:
                await interaction.followup.send(
                    f"❌ Objet `{item_code}` introuvable.",
                    ephemeral=True,
                )
                return

            if is_gear(item):
                # Les copies les moins précieuses d'abord, les portées en
                # dernier ; une pièce en vente n'est pas touchée.
                removed = take_gear(session, profile.player.id, item, quantity)
                if removed < quantity:
                    await interaction.followup.send(
                        f"⚠️ {removed} copie(s) seulement retirée(s) à {target.display_name} "
                        f"(les pièces en vente ne sont pas touchées).",
                        ephemeral=True,
                    )
                    return
                await interaction.followup.send(
                    f"✅ {quantity}× **{item.name}** retiré à {target.mention} "
                    "(copies les moins rares d'abord).",
                    ephemeral=True,
                )
                return

            removed = inventory_repository.remove_item(
                player_id=profile.player.id,
                item_definition_id=item.id,
                quantity=quantity,
            )

            if not removed:
                await interaction.followup.send(
                    f"❌ {target.display_name} ne possède pas {quantity}× **{item.name}**.",
                    ephemeral=True,
                )
                return

        await interaction.followup.send(
            f"✅ {quantity}× **{item.name}** retiré de l'inventaire de {target.mention}.",
            ephemeral=True,
        )

    @admin.command(
        name="force_equip",
        description="Équipe une pièce sur un joueur (crée une copie s'il n'en a pas)",
    )
    @app_commands.describe(
        target="Joueur ciblé",
        item_code="Code de la pièce à équiper",
        rarity="Rareté de la copie créée si le joueur n'en possède aucune (commun par défaut)",
    )
    @app_commands.choices(rarity=_RARITY_CHOICES)
    @admin_only
    async def force_equip(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        item_code: str,
        rarity: str = "common",
    ) -> None:
        """Équipement v2 : on porte une COPIE, placée selon les règles du jeu
        (emplacement automatique, deux mains, une pièce une fois)."""
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(target.id)
            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.", ephemeral=True
                )
                return
            item = ItemRepository(session).get_by_code(item_code)
            if item is None or not is_gear(item):
                await interaction.followup.send(
                    f"❌ `{item_code}` n'est pas une pièce d'équipement.", ephemeral=True
                )
                return
            owned = [g for g in GearRepository(session).list_owned(profile.player.id)
                     if g.item_definition.id == item.id and not g.equipped]
            if owned:
                gear_id = owned[0].id
            else:
                give_gear(session, profile.player.id, item, 1, rarity)
                gear_id = next(g.id for g in GearRepository(session).list_owned(profile.player.id)
                               if g.item_definition.id == item.id and not g.equipped)
            result = EquipItemUseCase(
                PlayerRepository(session), InventoryRepository(session),
                EquipmentRepository(session),
            ).execute(target.id, target.name, target.display_name, gear_id=gear_id)
        await interaction.followup.send(result.message, ephemeral=True)

    @admin.command(
        name="force_unequip",
        description="Retire l'équipement d'un slot d'un joueur",
    )
    @app_commands.describe(target="Joueur ciblé", slot="Slot à vider")
    @admin_only
    async def force_unequip(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        slot: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(target.id)
            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.", ephemeral=True
                )
                return
            removed = EquipmentRepository(session).unequip_slot(profile.player.id, slot)
        if removed:
            await interaction.followup.send(
                f"✅ Slot `{slot}` de {target.mention} vidé.", ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"⚠️ Slot `{slot}` était déjà vide.", ephemeral=True
            )

    @force_unequip.autocomplete("slot")
    async def slot_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        current_lower = current.lower()
        return [
            app_commands.Choice(name=s.value, value=s.value)
            for s in EquipmentSlot
            if current_lower in s.value.lower()
        ][:25]

    @give_item.autocomplete("item_code")
    @remove_item.autocomplete("item_code")
    @force_equip.autocomplete("item_code")
    async def item_code_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        with get_db_session() as session:
            item_repository = ItemRepository(session)
            items = item_repository.list_all()

        if not items:
            return []

        current_lower = current.lower()
        choices: list[app_commands.Choice[str]] = []

        for item in items:
            if (
                current_lower in item.code.lower()
                or current_lower in item.name.lower()
            ):
                choices.append(
                    app_commands.Choice(
                        name=f"{item.name} ({item.code})",
                        value=item.code,
                    )
                )

            if len(choices) >= 25:
                break

        return choices
