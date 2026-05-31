"""Cog de la brocante (marketplace P2P) — `/brocante *`.

Sous-commandes :
    • /brocante list                                 → catalogue actif
    • /brocante my                                   → vos annonces actives
    • /brocante sell <item> <qty> <price> [days]     → créer une annonce
    • /brocante buy <listing_id>                     → acheter
    • /brocante cancel <listing_id>                  → annuler une annonce

Loop horaire de cleanup des annonces expirées (auto-restitution des items
au vendeur). Toutes les opérations sensibles passent par les use cases
qui gèrent l'atomicité (ordre items ↔ gold ↔ statut).
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from app.application.use_cases.marketplace import (
    BuyMarketplaceListingUseCase,
    CancelMarketplaceListingUseCase,
    ExpireMarketplaceListingsUseCase,
    ListItemForSaleUseCase,
    MARKETPLACE_COMMISSION_PCT,
    MAX_LISTING_DAYS,
)
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.marketplace_repository import (
    MarketplaceRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session
from app.bot.cogs._mixins import BetaChannelOnlyMixin


_logger = logging.getLogger(__name__)


def _format_listing_line(listing, item_name: str, seller_name: str) -> str:
    return (
        f"`#{listing.id}` **{listing.quantity}× {item_name}** — "
        f"**{listing.price_per_unit}** or/u "
        f"({listing.total_price} total) · vendeur : {seller_name} · "
        f"expire <t:{int(listing.expires_at.timestamp())}:R>"
    )


class BrocanteCog(BetaChannelOnlyMixin, commands.Cog):
    brocante = app_commands.Group(
        name="brocante", description="Marché P2P entre joueurs"
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.expire_loop.start()

    def cog_unload(self) -> None:
        self.expire_loop.cancel()

    @tasks.loop(hours=1)
    async def expire_loop(self) -> None:
        try:
            with get_db_session() as session:
                use_case = ExpireMarketplaceListingsUseCase(
                    inventory_repository=InventoryRepository(session),
                    marketplace_repository=MarketplaceRepository(session),
                )
                result = use_case.execute()
            if result.expired_count > 0:
                _logger.info(
                    "Brocante cleanup : %d annonce(s) expirée(s), "
                    "items restitués aux vendeurs",
                    result.expired_count,
                )
        except Exception:
            _logger.exception("Brocante expire loop failed")

    @expire_loop.before_loop
    async def _before_expire(self) -> None:
        await self.bot.wait_until_ready()

    # ---------- list (catalogue actif) ----------

    @brocante.command(
        name="list",
        description="Voir le catalogue d'annonces actives",
    )
    @app_commands.describe(
        item="Filtre optionnel sur un item précis (autocomplete)"
    )
    async def list_listings(
        self,
        interaction: discord.Interaction,
        item: str | None = None,
    ) -> None:
        await interaction.response.defer()
        with get_db_session() as session:
            repo = MarketplaceRepository(session)
            listings = repo.list_active(limit=25, item_code=item)

            # Pre-charge les items et sellers en batch
            from app.infrastructure.db.models.item_model import ItemDefinitionModel
            from app.infrastructure.db.models.player_model import PlayerModel

            item_ids = {l.item_definition_id for l in listings}
            seller_ids = {l.seller_player_id for l in listings}
            items = {
                m.id: m for m in session.query(ItemDefinitionModel)
                .filter(ItemDefinitionModel.id.in_(item_ids)).all()
            } if item_ids else {}
            sellers = {
                m.id: m for m in session.query(PlayerModel)
                .filter(PlayerModel.id.in_(seller_ids)).all()
            } if seller_ids else {}

        embed = discord.Embed(
            title="🛍️ Brocante — annonces actives",
            color=discord.Color.dark_orange(),
        )
        if not listings:
            embed.description = "_Aucune annonce active pour l'instant._"
        else:
            lines = [
                _format_listing_line(
                    l,
                    items[l.item_definition_id].name if l.item_definition_id in items else "?",
                    sellers[l.seller_player_id].display_name if l.seller_player_id in sellers else "?",
                )
                for l in listings
            ]
            embed.description = "\n".join(lines)[:4000]
        embed.set_footer(
            text=f"Commission shop : {MARKETPLACE_COMMISSION_PCT}% · "
            f"durée max : {MAX_LISTING_DAYS}j · /brocante buy <id> pour acheter"
        )
        await interaction.followup.send(embed=embed)

    @list_listings.autocomplete("item")
    async def list_item_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        with get_db_session() as session:
            items = ItemRepository(session).list_all()
        current_lower = current.lower()
        return [
            app_commands.Choice(name=f"{i.name} ({i.code})", value=i.code)
            for i in items
            if current_lower in i.code.lower() or current_lower in i.name.lower()
        ][:25]

    # ---------- my listings ----------

    @brocante.command(
        name="my", description="Voir vos annonces actives"
    )
    async def my_listings(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(interaction.user.id)
            if profile is None:
                await interaction.followup.send(
                    "❌ Vous n'avez pas encore de profil.", ephemeral=True
                )
                return
            listings = MarketplaceRepository(session).list_active_for_seller(
                profile.player.id
            )
            from app.infrastructure.db.models.item_model import ItemDefinitionModel
            item_ids = {l.item_definition_id for l in listings}
            items = {
                m.id: m for m in session.query(ItemDefinitionModel)
                .filter(ItemDefinitionModel.id.in_(item_ids)).all()
            } if item_ids else {}

        embed = discord.Embed(
            title="🏷️ Mes annonces actives",
            color=discord.Color.dark_orange(),
        )
        if not listings:
            embed.description = "_Vous n'avez aucune annonce active._"
        else:
            lines = [
                f"`#{l.id}` {l.quantity}× **{items.get(l.item_definition_id).name if l.item_definition_id in items else '?'}** "
                f"à {l.price_per_unit} or/u — expire <t:{int(l.expires_at.timestamp())}:R>"
                for l in listings
            ]
            embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ---------- sell ----------

    @brocante.command(
        name="sell",
        description="Mettre un item en vente sur la brocante",
    )
    @app_commands.describe(
        item="Item à vendre (autocomplete sur votre inventaire)",
        quantity="Quantité à mettre en vente",
        price_per_unit="Prix unitaire en or",
        duration_days="Durée de l'annonce en jours (max 5)",
    )
    async def sell(
        self,
        interaction: discord.Interaction,
        item: str,
        quantity: app_commands.Range[int, 1, 9999],
        price_per_unit: app_commands.Range[int, 1, 1_000_000],
        duration_days: app_commands.Range[int, 1, 5] = 5,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            use_case = ListItemForSaleUseCase(
                player_repository=PlayerRepository(session),
                inventory_repository=InventoryRepository(session),
                item_repository=ItemRepository(session),
                marketplace_repository=MarketplaceRepository(session),
            )
            result = use_case.execute(
                seller_discord_id=interaction.user.id,
                seller_username=interaction.user.name,
                seller_display_name=interaction.user.display_name,
                item_code=item,
                quantity=quantity,
                price_per_unit=price_per_unit,
                duration_days=duration_days,
            )
        await interaction.followup.send(result.message, ephemeral=True)

    @sell.autocomplete("item")
    async def sell_item_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(interaction.user.id)
            if profile is None:
                return []
            inventory = InventoryRepository(session).list_by_player_id(profile.player.id)
        current_lower = current.lower()
        out: list[app_commands.Choice[str]] = []
        for inv in inventory:
            i = inv.item_definition
            if current_lower in i.code.lower() or current_lower in i.name.lower():
                out.append(
                    app_commands.Choice(
                        name=f"{i.name} (×{inv.quantity})", value=i.code,
                    )
                )
            if len(out) >= 25:
                break
        return out

    # ---------- buy ----------

    @brocante.command(
        name="buy",
        description="Acheter une annonce active",
    )
    @app_commands.describe(listing_id="ID de l'annonce à acheter")
    async def buy(
        self,
        interaction: discord.Interaction,
        listing_id: app_commands.Range[int, 1, 1_000_000_000],
    ) -> None:
        await interaction.response.defer()
        with get_db_session() as session:
            use_case = BuyMarketplaceListingUseCase(
                player_repository=PlayerRepository(session),
                inventory_repository=InventoryRepository(session),
                marketplace_repository=MarketplaceRepository(session),
            )
            result = use_case.execute(
                buyer_discord_id=interaction.user.id,
                buyer_username=interaction.user.name,
                buyer_display_name=interaction.user.display_name,
                listing_id=listing_id,
            )
        await interaction.followup.send(result.message)

    # ---------- cancel ----------

    @brocante.command(
        name="cancel",
        description="Annuler une de vos annonces et récupérer les items",
    )
    @app_commands.describe(listing_id="ID de l'annonce à annuler")
    async def cancel(
        self,
        interaction: discord.Interaction,
        listing_id: app_commands.Range[int, 1, 1_000_000_000],
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            use_case = CancelMarketplaceListingUseCase(
                player_repository=PlayerRepository(session),
                inventory_repository=InventoryRepository(session),
                marketplace_repository=MarketplaceRepository(session),
            )
            result = use_case.execute(
                seller_discord_id=interaction.user.id,
                listing_id=listing_id,
            )
        await interaction.followup.send(result.message, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BrocanteCog(bot))
