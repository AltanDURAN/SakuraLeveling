"""Commandes `/admin shop_*` : la boutique de Sorn (ajout, réglage, retrait,
stock) et leurs autocomplétions. Mixin d'`AdminCog`, sorti d'`admin_cog.py`
le 28/11/2026 (audit) : texte inchangé."""

import discord
from discord import app_commands
from app.bot.checks.admin_check import admin_only
from app.domain.services.shop_pricing_service import ShopPricingService
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.shop_repository import ShopRepository
from app.infrastructure.db.session import get_db_session
from app.bot.cogs.admin_group import admin


class AdminShopMixin:
    @admin.command(
        name="shop_add",
        description="Ajoute un objet à la boutique",
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
                    "Utilise `/admin shop_set` pour le modifier.",
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
