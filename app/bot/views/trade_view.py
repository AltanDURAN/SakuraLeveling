from __future__ import annotations

import discord

from app.application.use_cases.accept_trade import AcceptTradeUseCase
from app.application.use_cases.create_trade import (
    CreateTradeUseCase,
    TradeOffer,
)
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


def parse_items_text(text: str) -> tuple[list[tuple[str, int]], list[str]]:
    """Parse le texte d'un champ d'items.

    Format attendu : une ligne par item, "code quantite" ou "code:quantite" ou
    "quantite code" ou juste "code" (quantité = 1).

    Renvoie (items, errors). errors est une liste de descriptions de lignes
    qui n'ont pas pu être parsées.
    """
    items: list[tuple[str, int]] = []
    errors: list[str] = []
    if not text:
        return items, errors

    for raw_line in text.splitlines():
        line = raw_line.strip().replace(",", " ").replace(":", " ")
        if not line:
            continue
        parts = [p for p in line.split() if p]
        if not parts:
            continue

        if len(parts) == 1:
            items.append((parts[0], 1))
            continue

        # Cherche un nombre dans les parts pour décider de la quantité
        first_int = None
        first_int_idx = -1
        for idx, p in enumerate(parts):
            try:
                first_int = int(p)
                first_int_idx = idx
                break
            except ValueError:
                continue

        if first_int is None:
            errors.append(raw_line)
            continue

        # Le code est la concat des autres parts
        code_parts = [p for i, p in enumerate(parts) if i != first_int_idx]
        if not code_parts:
            errors.append(raw_line)
            continue
        code = "_".join(code_parts) if len(code_parts) > 1 else code_parts[0]
        items.append((code, max(1, first_int)))

    return items, errors


def _parse_int(text: str) -> int:
    """Parse un nombre. Vide → 0. Invalide → raise ValueError."""
    text = (text or "").strip()
    if not text:
        return 0
    return int(text)


class TradeProposalModal(discord.ui.Modal):
    """Modal de proposition de trade : 4 champs (offre items/or, demande items/or)."""

    def __init__(
        self,
        target_member: discord.Member,
        target_display_name: str,
        on_submit_callback,
    ) -> None:
        super().__init__(title=f"Trade avec {target_display_name[:30]}")
        self.target_member = target_member
        self.target_display_name = target_display_name
        self.on_submit_callback = on_submit_callback

        self.items_offered_input = discord.ui.TextInput(
            label="Items que vous proposez (un par ligne)",
            style=discord.TextStyle.paragraph,
            placeholder="iron_ingot 5\nleather_strip 2",
            required=False,
            max_length=1500,
        )
        self.gold_offered_input = discord.ui.TextInput(
            label="Or que vous proposez",
            style=discord.TextStyle.short,
            placeholder="0",
            required=False,
            max_length=10,
        )
        self.items_requested_input = discord.ui.TextInput(
            label="Items que vous demandez",
            style=discord.TextStyle.paragraph,
            placeholder="gobelin_tooth 10",
            required=False,
            max_length=1500,
        )
        self.gold_requested_input = discord.ui.TextInput(
            label="Or que vous demandez",
            style=discord.TextStyle.short,
            placeholder="0",
            required=False,
            max_length=10,
        )

        self.add_item(self.items_offered_input)
        self.add_item(self.gold_offered_input)
        self.add_item(self.items_requested_input)
        self.add_item(self.gold_requested_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            offered_items, off_errs = parse_items_text(self.items_offered_input.value)
            requested_items, req_errs = parse_items_text(self.items_requested_input.value)
            offered_gold = _parse_int(self.gold_offered_input.value)
            requested_gold = _parse_int(self.gold_requested_input.value)
        except ValueError as exc:
            await interaction.response.send_message(
                f"❌ Format invalide pour l'or : {exc}", ephemeral=True
            )
            return

        errors = off_errs + req_errs
        if errors:
            await interaction.response.send_message(
                f"❌ Lignes d'items non parsables : {', '.join('`' + e + '`' for e in errors)}\n"
                f"Format attendu : `code quantité` (ex : `iron_ingot 5`)",
                ephemeral=True,
            )
            return

        await self.on_submit_callback(
            interaction=interaction,
            offered_items=offered_items,
            offered_gold=offered_gold,
            requested_items=requested_items,
            requested_gold=requested_gold,
        )


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
