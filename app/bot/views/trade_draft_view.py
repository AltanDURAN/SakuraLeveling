"""Workflow de proposition de trade par boutons itératifs.

Remplace l'ancienne modal mono-shot (TradeProposalModal) par un draft
visuellement maintenu avec autocomplete sur les items.

Flow d'utilisation :
    /trade @target
        → message ephemeral avec un brouillon vide (TradeDraftView) +
          boutons "+ Mon item", "+ Item demandé", "💰 Mon or", "💰 Or demandé",
          "🔄 Reset", "✅ Soumettre", "🛑 Annuler"

    Clic "+ Mon item" / "+ Item demandé"
        → la view du draft est temporairement remplacée par un Select Menu
          (TradeItemSelectView) listant les items du joueur ciblé. Sélection
          → modal de quantité → ajout au draft → retour à la TradeDraftView.

    Clic "💰 Mon or" / "💰 Or demandé"
        → modal courte avec un seul champ. Submit → met à jour l'état et
          rafraîchit l'embed du draft.

    Clic "✅ Soumettre"
        → crée le trade en DB via CreateTradeUseCase, poste un nouveau
          message public dans le canal avec embed + TradeResponseView
          (boutons accept/refuse/cancel). Édit le brouillon en "Trade soumis".

L'état du brouillon vit dans `TradeDraftView` (instance attributes). Le timeout
est aligné sur le TTL du trade (5 min par défaut).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import discord

from app.application.use_cases.create_trade import CreateTradeUseCase, TradeOffer
from app.bot.embeds.trade_embeds import build_trade_embed
from app.bot.views.trade_view import TradeResponseView
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.trade_repository import TradeRepository
from app.infrastructure.db.session import get_db_session


SELECT_LIMIT = 25  # contrainte Discord


@dataclass
class TradeDraft:
    """État d'un brouillon de trade côté initiateur."""

    offered_items: list[tuple[str, int]] = field(default_factory=list)
    requested_items: list[tuple[str, int]] = field(default_factory=list)
    offered_gold: int = 0
    requested_gold: int = 0

    def add_offered_item(self, code: str, quantity: int) -> None:
        self._add(self.offered_items, code, quantity)

    def add_requested_item(self, code: str, quantity: int) -> None:
        self._add(self.requested_items, code, quantity)

    def reset(self) -> None:
        self.offered_items.clear()
        self.requested_items.clear()
        self.offered_gold = 0
        self.requested_gold = 0

    @staticmethod
    def _add(target_list: list[tuple[str, int]], code: str, quantity: int) -> None:
        for idx, (existing_code, existing_qty) in enumerate(target_list):
            if existing_code == code:
                target_list[idx] = (code, existing_qty + quantity)
                return
        target_list.append((code, quantity))

    def is_empty(self) -> bool:
        return (
            not self.offered_items
            and not self.requested_items
            and self.offered_gold == 0
            and self.requested_gold == 0
        )


def _format_offer_lines(items: list[tuple[str, int]], gold: int) -> str:
    parts: list[str] = []
    if gold > 0:
        parts.append(f"💰 **{gold}** or")
    parts.extend(f"{quantity}× `{code}`" for code, quantity in items)
    return "\n".join(parts) if parts else "_Rien_"


def build_draft_embed(
    draft: TradeDraft,
    initiator_display_name: str,
    target_display_name: str,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🤝 Brouillon de trade avec {target_display_name}",
        color=discord.Color.blurple(),
        description=(
            "Construisez votre proposition avec les boutons ci-dessous, "
            "puis cliquez **Soumettre** pour envoyer la demande."
        ),
    )
    embed.add_field(
        name=f"📤 {initiator_display_name} propose",
        value=_format_offer_lines(draft.offered_items, draft.offered_gold),
        inline=True,
    )
    embed.add_field(
        name=f"📥 {target_display_name} doit donner",
        value=_format_offer_lines(draft.requested_items, draft.requested_gold),
        inline=True,
    )
    return embed


# ---------- Modals ----------


class _GoldInputModal(discord.ui.Modal):
    """Modal courte avec un seul champ pour saisir un montant d'or ≥ 0."""

    def __init__(
        self,
        title: str,
        current_value: int,
        on_submit_callback,
    ) -> None:
        super().__init__(title=title)
        self.on_submit_callback = on_submit_callback
        self.gold_input = discord.ui.TextInput(
            label="Montant d'or (≥ 0)",
            style=discord.TextStyle.short,
            placeholder="0",
            default=str(current_value) if current_value > 0 else "",
            required=False,
            max_length=12,
        )
        self.add_item(self.gold_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        text = (self.gold_input.value or "").strip()
        try:
            value = int(text) if text else 0
        except ValueError:
            await interaction.response.send_message(
                "❌ Montant invalide.", ephemeral=True
            )
            return
        if value < 0:
            await interaction.response.send_message(
                "❌ Le montant doit être ≥ 0.", ephemeral=True
            )
            return
        await self.on_submit_callback(interaction, value)


class _QuantityModal(discord.ui.Modal):
    """Modal pour saisir la quantité d'un item ajouté au draft."""

    def __init__(
        self,
        item_code: str,
        item_name: str,
        max_quantity: int | None,
        on_submit_callback,
    ) -> None:
        super().__init__(title=f"Quantité : {item_name[:30]}")
        self.item_code = item_code
        self.max_quantity = max_quantity
        self.on_submit_callback = on_submit_callback

        placeholder = "1"
        if max_quantity is not None:
            placeholder = f"1 à {max_quantity}"

        self.qty_input = discord.ui.TextInput(
            label="Quantité (≥ 1)",
            style=discord.TextStyle.short,
            placeholder=placeholder,
            required=True,
            max_length=6,
        )
        self.add_item(self.qty_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            qty = int(self.qty_input.value.strip())
        except ValueError:
            await interaction.response.send_message(
                "❌ Quantité invalide.", ephemeral=True
            )
            return
        if qty <= 0:
            await interaction.response.send_message(
                "❌ La quantité doit être ≥ 1.", ephemeral=True
            )
            return
        if self.max_quantity is not None and qty > self.max_quantity:
            await interaction.response.send_message(
                f"❌ Vous n'en avez que {self.max_quantity}.", ephemeral=True
            )
            return
        await self.on_submit_callback(interaction, qty)


# ---------- Select Menu intermédiaire ----------


class _ItemSelectView(discord.ui.View):
    """View temporaire pour choisir un item parmi 25 (Select Menu Discord)."""

    def __init__(
        self,
        title: str,
        choices: list[tuple[str, str, int | None]],  # (code, label, max_qty)
        on_pick_callback,
        on_cancel_callback,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.on_pick_callback = on_pick_callback
        self.on_cancel_callback = on_cancel_callback
        self._max_qty_by_code = {code: max_qty for code, _, max_qty in choices}

        self.select = discord.ui.Select(
            placeholder=title[:100],
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label=label[:100], value=code)
                for code, label, _ in choices
            ],
        )

        async def select_callback(interaction: discord.Interaction):
            code = self.select.values[0]
            max_qty = self._max_qty_by_code.get(code)
            await self.on_pick_callback(interaction, code, max_qty)

        self.select.callback = select_callback
        self.add_item(self.select)

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.on_cancel_callback(interaction)


# ---------- Vue principale du brouillon ----------


class TradeDraftView(discord.ui.View):
    """Brouillon interactif de trade. Maintient l'état dans ses attributs et
    rafraîchit l'embed à chaque action utilisateur."""

    def __init__(
        self,
        initiator: discord.abc.User,
        target: discord.Member,
        timeout: float = 300.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.initiator = initiator
        self.target = target
        self.draft = TradeDraft()
        self.draft_message: discord.InteractionMessage | None = None

    def _build_embed(self) -> discord.Embed:
        return build_draft_embed(
            self.draft,
            self.initiator.display_name,
            self.target.display_name,
        )

    async def _refresh_self(self, interaction: discord.Interaction) -> None:
        """Restaure la vue principale après un sub-flow (Select / Modal)."""
        await interaction.response.edit_message(
            embed=self._build_embed(), view=self
        )

    # ---------- Boutons ----------

    @discord.ui.button(label="+ Mon item", style=discord.ButtonStyle.primary, row=0)
    async def add_offered_item(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(self.initiator.id)
            if profile is None:
                items = []
            else:
                inventory = InventoryRepository(session).list_by_player_id(
                    profile.player.id
                )
                items = sorted(
                    inventory, key=lambda i: -i.quantity
                )[:SELECT_LIMIT]

        choices = [
            (
                item.item_definition.code,
                f"{item.item_definition.name} (×{item.quantity})",
                item.quantity,
            )
            for item in items
        ]
        if not choices:
            await interaction.response.send_message(
                "❌ Vous n'avez aucun item dans votre inventaire à proposer.",
                ephemeral=True,
            )
            return

        await self._open_item_select(
            interaction,
            title="Choisissez un item à proposer",
            choices=choices,
            side="offered",
        )

    @discord.ui.button(label="+ Item demandé", style=discord.ButtonStyle.primary, row=0)
    async def add_requested_item(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        with get_db_session() as session:
            target_profile = PlayerRepository(session).get_by_discord_id(self.target.id)
            if target_profile is None:
                items = []
            else:
                inventory = InventoryRepository(session).list_by_player_id(
                    target_profile.player.id
                )
                items = sorted(inventory, key=lambda i: -i.quantity)[:SELECT_LIMIT]

        choices = [
            (
                item.item_definition.code,
                f"{item.item_definition.name} (chez {self.target.display_name}: ×{item.quantity})",
                None,  # pas de cap côté demande
            )
            for item in items
        ]
        if not choices:
            await interaction.response.send_message(
                f"❌ {self.target.display_name} n'a aucun item dans son inventaire à demander.",
                ephemeral=True,
            )
            return

        await self._open_item_select(
            interaction,
            title=f"Choisissez un item à demander à {self.target.display_name}",
            choices=choices,
            side="requested",
        )

    async def _open_item_select(
        self,
        interaction: discord.Interaction,
        title: str,
        choices: list[tuple[str, str, int | None]],
        side: str,  # "offered" ou "requested"
    ) -> None:
        async def on_pick(picked_interaction, code, max_qty):
            # Ouvre la modal de quantité
            item_name = next((label for c, label, _ in choices if c == code), code)

            async def on_qty_submit(qty_interaction, qty):
                if side == "offered":
                    self.draft.add_offered_item(code, qty)
                else:
                    self.draft.add_requested_item(code, qty)
                await self._refresh_self(qty_interaction)

            modal = _QuantityModal(
                item_code=code,
                item_name=item_name,
                max_quantity=max_qty,
                on_submit_callback=on_qty_submit,
            )
            await picked_interaction.response.send_modal(modal)

        async def on_cancel(cancel_interaction):
            await self._refresh_self(cancel_interaction)

        select_view = _ItemSelectView(
            title=title,
            choices=choices,
            on_pick_callback=on_pick,
            on_cancel_callback=on_cancel,
        )
        await interaction.response.edit_message(
            embed=self._build_embed(), view=select_view
        )

    @discord.ui.button(label="💰 Mon or", style=discord.ButtonStyle.secondary, row=1)
    async def set_offered_gold(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        async def on_submit(submit_interaction, value):
            self.draft.offered_gold = value
            await self._refresh_self(submit_interaction)

        modal = _GoldInputModal(
            title="Or que vous proposez",
            current_value=self.draft.offered_gold,
            on_submit_callback=on_submit,
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="💰 Or demandé", style=discord.ButtonStyle.secondary, row=1)
    async def set_requested_gold(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        async def on_submit(submit_interaction, value):
            self.draft.requested_gold = value
            await self._refresh_self(submit_interaction)

        modal = _GoldInputModal(
            title="Or que vous demandez",
            current_value=self.draft.requested_gold,
            on_submit_callback=on_submit,
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🔄 Reset", style=discord.ButtonStyle.secondary, row=2)
    async def reset_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.draft.reset()
        await self._refresh_self(interaction)

    @discord.ui.button(label="🛑 Annuler", style=discord.ButtonStyle.secondary, row=2)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="🛑 Brouillon annulé.",
            embed=self._build_embed(),
            view=self,
        )
        self.stop()

    @discord.ui.button(label="✅ Soumettre", style=discord.ButtonStyle.success, row=2)
    async def submit_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if self.draft.is_empty():
            await interaction.response.send_message(
                "❌ Brouillon vide : ajoutez au moins un item ou de l'or.",
                ephemeral=True,
            )
            return

        with get_db_session() as session:
            use_case = CreateTradeUseCase(
                player_repository=PlayerRepository(session),
                inventory_repository=InventoryRepository(session),
                item_repository=ItemRepository(session),
                trade_repository=TradeRepository(session),
            )
            result = use_case.execute(
                initiator_discord_id=self.initiator.id,
                target_discord_id=self.target.id,
                initiator_username=self.initiator.name,
                initiator_display_name=self.initiator.display_name,
                target_display_name=self.target.display_name,
                initiator_offer=TradeOffer(
                    items=list(self.draft.offered_items),
                    gold=self.draft.offered_gold,
                ),
                target_request=TradeOffer(
                    items=list(self.draft.requested_items),
                    gold=self.draft.requested_gold,
                ),
                ttl_minutes=5,
            )

        if not result.success or result.trade is None:
            await interaction.response.send_message(result.message, ephemeral=True)
            return

        # Désactive le brouillon ephemeral
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="✅ Trade soumis ! Voir le message public.",
            embed=self._build_embed(),
            view=self,
        )
        self.stop()

        # Poste le message public avec embed + boutons accept/refuse/cancel
        public_view = TradeResponseView(
            trade_id=result.trade.id,
            initiator_discord_id=result.trade.initiator_discord_id,
            target_discord_id=result.trade.target_discord_id,
            timeout=5 * 60,
        )
        await interaction.followup.send(
            content=f"{self.target.mention}, {self.initiator.mention} vous propose un échange :",
            embed=build_trade_embed(result.trade),
            view=public_view,
            ephemeral=False,
        )
