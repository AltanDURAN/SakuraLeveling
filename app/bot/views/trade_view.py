from __future__ import annotations

import discord

from app.application.use_cases.accept_trade import AcceptTradeUseCase
from app.application.use_cases.refuse_trade import (
    CancelTradeUseCase,
    RefuseTradeUseCase,
)
from app.bot.embeds.trade_embeds import build_trade_embed
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.trade_repository import TradeRepository
from app.infrastructure.db.session import get_db_session


class TradeResponseView(discord.ui.View):
    """Boutons Accepter / Refuser pour le destinataire ; Annuler pour l'initiator."""

    def __init__(
        self,
        trade_id: int,
        initiator_discord_id: int,
        target_discord_id: int,
        timeout: float = 300.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.trade_id = trade_id
        self.initiator_discord_id = initiator_discord_id
        self.target_discord_id = target_discord_id

    @discord.ui.button(label="Accepter", style=discord.ButtonStyle.success, emoji="✅")
    async def accept_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if interaction.user.id != self.target_discord_id:
            await interaction.response.send_message(
                "❌ Seul le destinataire du trade peut l'accepter.",
                ephemeral=True,
            )
            return

        with get_db_session() as session:
            use_case = AcceptTradeUseCase(
                session=session,
                player_repository=PlayerRepository(session),
                inventory_repository=InventoryRepository(session),
                item_repository=ItemRepository(session),
                trade_repository=TradeRepository(session),
            )
            result = use_case.execute(
                trade_id=self.trade_id,
                accepting_player_discord_id=interaction.user.id,
            )

        if result.trade is not None:
            embed = build_trade_embed(result.trade)
        else:
            embed = None

        # Désactive tous les boutons après réponse
        for child in self.children:
            child.disabled = True

        if result.success and embed:
            await interaction.response.edit_message(
                content=result.message, embed=embed, view=self
            )
        else:
            # Échec : on garde l'embed précédent en l'état mais on ajoute le motif
            await interaction.response.edit_message(
                content=result.message,
                embed=embed,
                view=self,
            )

    @discord.ui.button(label="Refuser", style=discord.ButtonStyle.danger, emoji="✋")
    async def refuse_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if interaction.user.id != self.target_discord_id:
            await interaction.response.send_message(
                "❌ Seul le destinataire du trade peut le refuser.",
                ephemeral=True,
            )
            return

        with get_db_session() as session:
            use_case = RefuseTradeUseCase(TradeRepository(session))
            result = use_case.execute(
                trade_id=self.trade_id,
                refusing_player_discord_id=interaction.user.id,
            )

        embed = build_trade_embed(result.trade) if result.trade else None
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=result.message, embed=embed, view=self
        )

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary, emoji="🛑")
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if interaction.user.id != self.initiator_discord_id:
            await interaction.response.send_message(
                "❌ Seul l'initiateur peut annuler son trade.",
                ephemeral=True,
            )
            return

        with get_db_session() as session:
            use_case = CancelTradeUseCase(TradeRepository(session))
            result = use_case.execute(
                trade_id=self.trade_id,
                cancelling_player_discord_id=interaction.user.id,
            )

        embed = build_trade_embed(result.trade) if result.trade else None
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=result.message, embed=embed, view=self
        )
