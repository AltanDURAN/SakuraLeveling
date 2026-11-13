"""Workflow de proposition de trade par boutons itératifs.

Remplace l'ancienne modal mono-shot (TradeProposalModal) par un draft
visuellement maintenu avec autocomplete sur les items.

Flow d'utilisation :
    /trade @target
        → message ephemeral avec un brouillon vide (TradeDraftView) +
          boutons "+ Mon item", "+ Item demandé", "Mon or", "Or demandé" (pièce d'or),
          "🔄 Reset", "✅ Soumettre", "🛑 Annuler"

    Clic "+ Mon item" / "+ Item demandé"
        → la view du draft est temporairement remplacée par un Select Menu
          (TradeItemSelectView) listant les items du joueur ciblé. Sélection
          → modal de quantité → ajout au draft → retour à la TradeDraftView.

    Clic "Mon or" / "Or demandé"
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
from app.domain.services.gear_service import gear_label, gear_ref, parse_gear_ref
from app.application.use_cases.create_trade import MAX_LOTS_PER_SIDE
from app.bot.embeds.limits import add_lines, clip
from app.infrastructure.db.repositories.gear_repository import GearRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.trade_repository import TradeRepository
from app.infrastructure.db.session import get_db_session
from app.shared.enums import GOLD_EMOJI
from app.shared.formatters import format_int


SELECT_LIMIT = 25  # contrainte Discord


@dataclass
class TradeDraft:
    """État d'un brouillon de trade côté initiateur."""

    offered_items: list[tuple[str, int]] = field(default_factory=list)
    requested_items: list[tuple[str, int]] = field(default_factory=list)
    offered_gold: int = 0
    requested_gold: int = 0
    #: Libellé affiché par code (une pièce « gear:<id> » n'a pas de code lisible).
    labels: dict[str, str] = field(default_factory=dict)

    #: Message à montrer au prochain affichage du brouillon (lot refusé).
    notice: str = ""

    def add_offered_item(self, code: str, quantity: int) -> bool:
        return self._add(self.offered_items, code, quantity)

    def add_requested_item(self, code: str, quantity: int) -> bool:
        return self._add(self.requested_items, code, quantity)

    def reset(self) -> None:
        self.offered_items.clear()
        self.requested_items.clear()
        self.offered_gold = 0
        self.requested_gold = 0
        self.notice = ""

    def _add(self, target_list: list[tuple[str, int]], code: str, quantity: int) -> bool:
        self.notice = ""
        for idx, (existing_code, existing_qty) in enumerate(target_list):
            if existing_code == code:
                # Une pièce d'équipement est un exemplaire : jamais ×2.
                if parse_gear_ref(code) is None:
                    target_list[idx] = (code, existing_qty + quantity)
                return True
        if len(target_list) >= MAX_LOTS_PER_SIDE:
            self.notice = (f"⚠️ Un échange porte au plus **{MAX_LOTS_PER_SIDE} lots** de chaque côté : "
                           "ce lot n'a pas été ajouté. Soumets celui-ci, puis fais-en un second.")
            return False
        target_list.append((code, quantity))
        return True

    def is_empty(self) -> bool:
        return (
            not self.offered_items
            and not self.requested_items
            and self.offered_gold == 0
            and self.requested_gold == 0
        )


def _format_offer_lines(items: list[tuple[str, int]], gold: int,
                        labels: dict[str, str] | None = None) -> list[str]:
    labels = labels or {}
    parts: list[str] = []
    if gold > 0:
        parts.append(f"{GOLD_EMOJI} **{format_int(gold)}** or")
    for code, quantity in items:
        if parse_gear_ref(code) is not None:
            parts.append(labels.get(code, code))
        else:
            parts.append(f"{quantity}× {labels.get(code, f'`{code}`')}")
    return parts


def build_draft_embed(
    draft: TradeDraft,
    initiator_display_name: str,
    target_display_name: str,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🤝 Brouillon d'échange avec {target_display_name}",
        color=discord.Color.blurple(),
        description=(
            "Construis ta proposition avec les boutons ci-dessous, "
            "puis clique sur **Soumettre** pour envoyer la demande."
        ),
    )
    if draft.notice:
        embed.description += f"\n\n{draft.notice}"
    # Plusieurs champs au besoin : tout ce qui s'échange reste visible.
    add_lines(embed, clip(f"📤 {initiator_display_name} propose", 250),
              _format_offer_lines(draft.offered_items, draft.offered_gold, draft.labels),
              inline=True, max_fields=3, empty="_Rien_")
    add_lines(embed, clip(f"📥 {target_display_name} doit donner", 250),
              _format_offer_lines(draft.requested_items, draft.requested_gold, draft.labels),
              inline=True, max_fields=3, empty="_Rien_")
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
                f"❌ Tu n'en as que {self.max_quantity}.", ephemeral=True
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
        # Plus de 25 objets (les cartes à collectionner s'ajoutent vite) :
        # des pages de 25, ◀ ▶ pour passer de l'une à l'autre.
        self.title = title
        self.choices = choices
        self.page = 0
        self.pages = max(1, -(-len(choices) // SELECT_LIMIT))

        self.select = discord.ui.Select(min_values=1, max_values=1, row=0)
        self._fill_select()

        async def select_callback(interaction: discord.Interaction):
            code = self.select.values[0]
            max_qty = self._max_qty_by_code.get(code)
            await self.on_pick_callback(interaction, code, max_qty)

        self.select.callback = select_callback
        self.add_item(self.select)
        if self.pages > 1:
            for label, step in (("◀", -1), ("▶", 1)):
                button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, row=1)

                async def turn(interaction: discord.Interaction, step=step):
                    self.page = (self.page + step) % self.pages
                    self._fill_select()
                    await interaction.response.edit_message(view=self)
                button.callback = turn
                self.add_item(button)

    def _fill_select(self) -> None:
        start = self.page * SELECT_LIMIT
        page = self.choices[start:start + SELECT_LIMIT]
        suffix = f" ({self.page + 1}/{self.pages})" if self.pages > 1 else ""
        self.select.placeholder = (self.title[: 100 - len(suffix)] + suffix)
        self.select.options = [discord.SelectOption(label=label[:100], value=code) for code, label, _ in page]

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary, row=1)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.on_cancel_callback(interaction)


def _sorted_items(inventory) -> list:
    """Objets d'abord (les plus nombreux en tête), puis les cartes à
    collectionner, les plus rares en tête."""
    from app.domain.services.card_service import rarity_index

    def key(item):
        definition = item.item_definition
        if definition.category == "carte":
            return (1, -rarity_index(definition.rarity), definition.name)
        return (0, -item.quantity, definition.name)
    return sorted(inventory, key=key)


def _gear_choices(gear) -> list[tuple[str, str, int | None]]:
    """Pièces d'équipement (les plus rares d'abord) pour le menu de sélection."""
    return [
        (
            gear_ref(g.id),
            gear_label(g.item_definition.name, g.rarity, g.forge_level)
            + (" (portée)" if g.equipped else ""),
            1,
        )
        for g in gear
    ]


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
                items, gear = [], []
            else:
                inventory = InventoryRepository(session).list_by_player_id(
                    profile.player.id
                )
                items = _sorted_items(inventory)
                # Pièces libres seulement : on ne cède pas ce qu'on porte.
                gear = [g for g in GearRepository(session).list_owned(profile.player.id)
                        if not g.equipped]

        choices = _gear_choices(gear) + [
            (
                item.item_definition.code,
                f"{item.item_definition.name} (×{item.quantity})",
                item.quantity,
            )
            for item in items
        ]
        if not choices:
            await interaction.response.send_message(
                "❌ Tu n'as aucun objet à proposer dans ton inventaire.",
                ephemeral=True,
            )
            return

        await self._open_item_select(
            interaction,
            title="Choisis un objet à proposer",
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
                items, gear = [], []
            else:
                inventory = InventoryRepository(session).list_by_player_id(
                    target_profile.player.id
                )
                items = _sorted_items(inventory)
                gear = GearRepository(session).list_owned(target_profile.player.id)

        choices = _gear_choices(gear) + [
            (
                item.item_definition.code,
                f"{item.item_definition.name} (chez {self.target.display_name}: ×{item.quantity})",
                None,  # pas de cap côté demande
            )
            for item in items
        ]
        if not choices:
            await interaction.response.send_message(
                f"❌ {self.target.display_name} n'a aucun objet à demander dans son inventaire.",
                ephemeral=True,
            )
            return

        await self._open_item_select(
            interaction,
            title=f"Choisis un objet à demander à {self.target.display_name}",
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
            item_name = next((label for c, label, _ in choices if c == code), code)
            if parse_gear_ref(code) is not None:
                # Une pièce est un exemplaire unique : pas de quantité à saisir.
                self.draft.labels[code] = item_name.removesuffix(" (portée)")
                if side == "offered":
                    self.draft.add_offered_item(code, 1)
                else:
                    self.draft.add_requested_item(code, 1)
                await self._refresh_self(picked_interaction)
                return
            self.draft.labels[code] = item_name.split(" (")[0]

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

    @discord.ui.button(label="Mon or", emoji=GOLD_EMOJI, style=discord.ButtonStyle.secondary, row=1)
    async def set_offered_gold(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        async def on_submit(submit_interaction, value):
            self.draft.offered_gold = value
            await self._refresh_self(submit_interaction)

        modal = _GoldInputModal(
            title="Or que tu proposes",
            current_value=self.draft.offered_gold,
            on_submit_callback=on_submit,
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Or demandé", emoji=GOLD_EMOJI, style=discord.ButtonStyle.secondary, row=1)
    async def set_requested_gold(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        async def on_submit(submit_interaction, value):
            self.draft.requested_gold = value
            await self._refresh_self(submit_interaction)

        modal = _GoldInputModal(
            title="Or que tu demandes",
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
            content=f"{self.target.mention}, {self.initiator.mention} te propose un échange :",
            embed=build_trade_embed(result.trade),
            view=public_view,
            ephemeral=False,
        )
