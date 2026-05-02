import discord
from discord import app_commands
from discord.ext import commands

from app.application.use_cases.reset_player import ResetPlayerUseCase
from app.bot.checks.admin_check import admin_only
from app.shared.formatters import format_int as _format_int
from app.domain.services.progression_service import ProgressionService
from app.domain.services.shop_pricing_service import ShopPricingService
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.shop_repository import ShopRepository
from app.infrastructure.db.session import get_db_session


class AdminCog(commands.Cog):
    """Commandes administrateur — réservées aux Discord IDs listés dans `ADMIN_DISCORD_IDS`."""

    admin = app_commands.Group(
        name="admin",
        description="Commandes administrateur",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # -------------------------- Or --------------------------

    @admin.command(name="give_gold", description="Ajoute de l'or à un joueur")
    @app_commands.describe(target="Joueur ciblé", amount="Quantité d'or à ajouter")
    @admin_only
    async def give_gold(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        amount: app_commands.Range[int, 1, 1_000_000_000],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            profile = player_repository.get_by_discord_id(target.id)

            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.",
                    ephemeral=True,
                )
                return

            player_repository.add_gold(profile.player.id, amount)

        await interaction.followup.send(
            f"✅ **{_format_int(amount)}** or ajouté à {target.mention}.",
            ephemeral=True,
        )

    @admin.command(name="set_gold", description="Définit le montant d'or d'un joueur")
    @app_commands.describe(target="Joueur ciblé", amount="Nouvelle quantité d'or (>= 0)")
    @admin_only
    async def set_gold(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        amount: app_commands.Range[int, 0, 1_000_000_000],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            profile = player_repository.get_by_discord_id(target.id)

            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.",
                    ephemeral=True,
                )
                return

            player_repository.set_gold(profile.player.id, amount)

        await interaction.followup.send(
            f"✅ Or de {target.mention} défini à **{_format_int(amount)}**.",
            ephemeral=True,
        )

    # -------------------------- XP / Niveau --------------------------

    @admin.command(name="give_xp", description="Ajoute de l'XP à un joueur (peut faire monter de niveau)")
    @app_commands.describe(target="Joueur ciblé", amount="Quantité d'XP à ajouter")
    @admin_only
    async def give_xp(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        amount: app_commands.Range[int, 1, 1_000_000_000],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        progression_service = ProgressionService()

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            profile = player_repository.get_by_discord_id(target.id)

            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.",
                    ephemeral=True,
                )
                return

            new_level, new_xp, new_skill_points = progression_service.apply_level_up(
                current_level=profile.progression.level,
                current_xp=profile.progression.xp,
                gained_xp=amount,
                current_skill_points=profile.progression.skill_points,
            )

            player_repository.apply_progression(
                player_id=profile.player.id,
                new_level=new_level,
                new_xp=new_xp,
                new_skill_points=new_skill_points,
            )

            level_msg = (
                f" — niveau **{profile.progression.level} → {new_level}**"
                if new_level > profile.progression.level
                else ""
            )

        await interaction.followup.send(
            f"✅ **{_format_int(amount)}** XP ajoutés à {target.mention}{level_msg}.",
            ephemeral=True,
        )

    @admin.command(name="set_level", description="Définit le niveau d'un joueur (XP remis à 0 pour ce niveau)")
    @app_commands.describe(target="Joueur ciblé", level="Nouveau niveau (>= 1)")
    @admin_only
    async def set_level(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        level: app_commands.Range[int, 1, 1000],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            profile = player_repository.get_by_discord_id(target.id)

            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.",
                    ephemeral=True,
                )
                return

            player_repository.apply_progression(
                player_id=profile.player.id,
                new_level=level,
                new_xp=0,
                new_skill_points=profile.progression.skill_points,
            )

        await interaction.followup.send(
            f"✅ Niveau de {target.mention} défini à **{level}**.",
            ephemeral=True,
        )

    # -------------------------- Items --------------------------

    @admin.command(name="give_item", description="Ajoute un objet à l'inventaire d'un joueur")
    @app_commands.describe(
        target="Joueur ciblé",
        item_code="Code de l'objet (ex : slime_gel)",
        quantity="Quantité à ajouter",
    )
    @admin_only
    async def give_item(
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

    # -------------------------- Outils de test --------------------------

    @admin.command(
        name="reset_player",
        description="Réinitialise complètement le profil d'un joueur (garde son identité Discord)",
    )
    @app_commands.describe(target="Joueur à réinitialiser")
    @admin_only
    async def reset_player(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            profile = player_repository.get_by_discord_id(target.id)

            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.",
                    ephemeral=True,
                )
                return

            ResetPlayerUseCase().execute(session=session, player_id=profile.player.id)

        await interaction.followup.send(
            f"✅ Profil de {target.mention} réinitialisé "
            "(niveau 1, 0 or, inventaire/équipement/classes/quêtes/cooldowns/kills/HP vidés).",
            ephemeral=True,
        )

    @admin.command(
        name="spawn_encounter",
        description="Force le spawn immédiat d'un encounter (dans le canal d'encounter)",
    )
    @admin_only
    async def spawn_encounter(self, interaction: discord.Interaction) -> None:
        encounter_cog = self.bot.get_cog("EncounterCog")
        if encounter_cog is None:
            await interaction.response.send_message(
                "❌ Le cog d'encounter n'est pas chargé.",
                ephemeral=True,
            )
            return

        success, message = encounter_cog.trigger_immediate_spawn()
        await interaction.response.send_message(
            f"{'✅' if success else '⚠️'} {message}",
            ephemeral=True,
        )

    # -------------------------- Shop --------------------------

    @admin.command(
        name="shop_add",
        description="Ajoute un objet au shop (achat fixe + vente dynamique)",
    )
    @app_commands.describe(
        item_code="Code de l'objet à mettre en shop",
        buy_price="Prix d'achat (gold) — fixe, payé par les joueurs",
        max_sell_price="Prix de vente maximum (stock vide) — payé au joueur qui vend",
        min_sell_price="Prix de vente minimum (stock saturé). 0 par défaut.",
        stock_threshold="Stock à partir duquel le prix de vente atteint le minimum. 100 par défaut.",
    )
    @admin_only
    async def shop_add(
        self,
        interaction: discord.Interaction,
        item_code: str,
        buy_price: app_commands.Range[int, 0, 1_000_000_000],
        max_sell_price: app_commands.Range[int, 0, 1_000_000_000],
        min_sell_price: app_commands.Range[int, 0, 1_000_000_000] = 0,
        stock_threshold: app_commands.Range[int, 1, 1_000_000] = 100,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        if min_sell_price > max_sell_price:
            await interaction.followup.send(
                "❌ `min_sell_price` doit être ≤ `max_sell_price`.",
                ephemeral=True,
            )
            return

        with get_db_session() as session:
            item_repository = ItemRepository(session)
            shop_repository = ShopRepository(session)

            item = item_repository.get_by_code(item_code)
            if item is None:
                await interaction.followup.send(
                    f"❌ Objet `{item_code}` introuvable.",
                    ephemeral=True,
                )
                return

            existing = shop_repository.get_by_item_code(item_code)
            if existing is not None:
                await interaction.followup.send(
                    f"❌ `{item.name}` est déjà dans le shop. "
                    "Utilisez `/admin shop_set` pour le modifier.",
                    ephemeral=True,
                )
                return

            shop_repository.create(
                item_definition_id=item.id,
                buy_price=buy_price,
                max_sell_price=max_sell_price,
                min_sell_price=min_sell_price,
                stock_threshold=stock_threshold,
                current_stock=0,
                enabled=True,
            )

        await interaction.followup.send(
            f"✅ **{item.name}** ajouté au shop\n"
            f"• Achat : {buy_price} or\n"
            f"• Vente : {min_sell_price}–{max_sell_price} or "
            f"(saturation à {stock_threshold} en stock)",
            ephemeral=True,
        )

    @admin.command(
        name="shop_set",
        description="Modifie les paramètres d'un objet du shop (champs optionnels)",
    )
    @app_commands.describe(
        item_code="Code de l'objet à modifier",
        buy_price="Nouveau prix d'achat (optionnel)",
        max_sell_price="Nouveau prix de vente max (optionnel)",
        min_sell_price="Nouveau prix de vente min (optionnel)",
        stock_threshold="Nouveau seuil de saturation (optionnel)",
        enabled="Activer ou désactiver l'objet (optionnel)",
    )
    @admin_only
    async def shop_set(
        self,
        interaction: discord.Interaction,
        item_code: str,
        buy_price: app_commands.Range[int, 0, 1_000_000_000] | None = None,
        max_sell_price: app_commands.Range[int, 0, 1_000_000_000] | None = None,
        min_sell_price: app_commands.Range[int, 0, 1_000_000_000] | None = None,
        stock_threshold: app_commands.Range[int, 1, 1_000_000] | None = None,
        enabled: bool | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        with get_db_session() as session:
            shop_repository = ShopRepository(session)
            shop_item = shop_repository.get_by_item_code(item_code)

            if shop_item is None:
                await interaction.followup.send(
                    f"❌ `{item_code}` n'est pas dans le shop.",
                    ephemeral=True,
                )
                return

            new_max = max_sell_price if max_sell_price is not None else shop_item.max_sell_price
            new_min = min_sell_price if min_sell_price is not None else shop_item.min_sell_price
            if new_min > new_max:
                await interaction.followup.send(
                    "❌ `min_sell_price` doit être ≤ `max_sell_price`.",
                    ephemeral=True,
                )
                return

            updated = shop_repository.update(
                shop_item_id=shop_item.id,
                buy_price=buy_price,
                max_sell_price=max_sell_price,
                min_sell_price=min_sell_price,
                stock_threshold=stock_threshold,
                enabled=enabled,
            )

        if updated is None:
            await interaction.followup.send("❌ Échec de la mise à jour.", ephemeral=True)
            return

        await interaction.followup.send(
            f"✅ **{updated.item_definition.name}** mis à jour\n"
            f"• Achat : {updated.buy_price} or\n"
            f"• Vente : {updated.min_sell_price}–{updated.max_sell_price} or "
            f"(saturation à {updated.stock_threshold})\n"
            f"• Stock : {updated.current_stock}\n"
            f"• Actif : {'oui' if updated.enabled else 'non'}",
            ephemeral=True,
        )

    @admin.command(name="shop_remove", description="Supprime un objet du shop")
    @app_commands.describe(item_code="Code de l'objet à retirer")
    @admin_only
    async def shop_remove(
        self,
        interaction: discord.Interaction,
        item_code: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        with get_db_session() as session:
            shop_repository = ShopRepository(session)
            shop_item = shop_repository.get_by_item_code(item_code)

            if shop_item is None:
                await interaction.followup.send(
                    f"❌ `{item_code}` n'est pas dans le shop.",
                    ephemeral=True,
                )
                return

            shop_repository.delete(shop_item.id)

        await interaction.followup.send(
            f"✅ **{shop_item.item_definition.name}** retiré du shop.",
            ephemeral=True,
        )

    @admin.command(
        name="shop_set_stock",
        description="Définit manuellement le stock d'un objet (utile pour reset le prix)",
    )
    @app_commands.describe(item_code="Code de l'objet", stock="Nouvelle valeur de stock (>= 0)")
    @admin_only
    async def shop_set_stock(
        self,
        interaction: discord.Interaction,
        item_code: str,
        stock: app_commands.Range[int, 0, 10_000_000],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        pricing_service = ShopPricingService()

        with get_db_session() as session:
            shop_repository = ShopRepository(session)
            shop_item = shop_repository.get_by_item_code(item_code)

            if shop_item is None:
                await interaction.followup.send(
                    f"❌ `{item_code}` n'est pas dans le shop.",
                    ephemeral=True,
                )
                return

            updated = shop_repository.set_stock(shop_item.id, stock)

        new_sell = pricing_service.current_sell_price(updated)
        await interaction.followup.send(
            f"✅ Stock de **{updated.item_definition.name}** défini à **{stock}**\n"
            f"• Nouveau prix de vente : {new_sell} or",
            ephemeral=True,
        )

    @shop_set.autocomplete("item_code")
    @shop_remove.autocomplete("item_code")
    @shop_set_stock.autocomplete("item_code")
    async def shop_existing_item_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        with get_db_session() as session:
            shop_repository = ShopRepository(session)
            shop_items = shop_repository.list_all(only_enabled=False)

        current_lower = current.lower()
        choices: list[app_commands.Choice[str]] = []

        for shop_item in shop_items:
            item = shop_item.item_definition
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

    @shop_add.autocomplete("item_code")
    async def shop_addable_item_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        with get_db_session() as session:
            item_repository = ItemRepository(session)
            shop_repository = ShopRepository(session)
            already_in_shop = {
                shop_item.item_definition.id
                for shop_item in shop_repository.list_all(only_enabled=False)
            }
            items = item_repository.list_all()

        current_lower = current.lower()
        choices: list[app_commands.Choice[str]] = []

        for item in items:
            if item.id in already_in_shop:
                continue
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

    # -------------------------- Autocomplete --------------------------

    @give_item.autocomplete("item_code")
    @remove_item.autocomplete("item_code")
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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
