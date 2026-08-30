"""Écran du marchand : portrait, menus en cascade, achat sans taper de code.

Même grammaire que les artisans — catégorie, puis article — pour que les trois
PNJ se manipulent de la même façon. La quantité se règle avec des boutons
plutôt qu'une saisie : c'est plus rapide et ça évite les fautes de frappe.
"""

from __future__ import annotations

import asyncio

import discord

from app.bot.rendering.npc_panel import compose_npc_panel, panel_path
from app.domain.entities.artisan import MerchantDefinition
from app.shared.enums import CATEGORY_ICONS, ITEM_CATEGORY_LABELS
from app.shared.formatters import format_int

_QUANTITY_STEPS = (1, 5, 10)


class MerchantView(discord.ui.View):
    def __init__(
        self,
        *,
        definition: MerchantDefinition,
        player_id: int,
        session_factory,
        buy_use_case_factory,
        discord_user: discord.abc.User,
        timeout: float = 300.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.definition = definition
        self.player_id = player_id
        self._session_factory = session_factory
        self._buy_factory = buy_use_case_factory
        self._user = discord_user

        self.category: str | None = None
        self.item_code: str | None = None
        self.quantity: int = 1

        self._by_category: dict[str, list] = {}
        self._selected = None
        self._player_gold = 0
        self._owned = 0

        self._build_components()

    # ------------------------------------------------------------ données --
    def refresh_data(self) -> None:
        from app.infrastructure.db.repositories.inventory_repository import (
            InventoryRepository,
        )
        from app.infrastructure.db.repositories.player_repository import (
            PlayerRepository,
        )
        from app.infrastructure.db.repositories.shop_repository import ShopRepository

        with self._session_factory() as session:
            shop_items = ShopRepository(session).list_all(only_enabled=True)
            grouped: dict[str, list] = {}
            for shop_item in shop_items:
                grouped.setdefault(
                    shop_item.item_definition.category, [],
                ).append(shop_item)
            for entries in grouped.values():
                entries.sort(key=lambda s: s.item_definition.name.lower())
            self._by_category = grouped

            profile = PlayerRepository(session).get_profile_by_player_id(
                self.player_id,
            )
            self._player_gold = profile.resources.gold if profile else 0

            self._selected = None
            self._owned = 0
            if self.item_code:
                self._selected = next(
                    (
                        s
                        for entries in grouped.values()
                        for s in entries
                        if s.item_definition.code == self.item_code
                    ),
                    None,
                )
                if self._selected is not None:
                    inventory = InventoryRepository(session).list_by_player_id(
                        self.player_id,
                    )
                    self._owned = next(
                        (
                            i.quantity
                            for i in inventory
                            if i.item_definition.code == self.item_code
                        ),
                        0,
                    )

        if self.category and self.category not in self._by_category:
            self.category = None
            self.item_code = None

    @property
    def total_cost(self) -> int:
        if self._selected is None:
            return 0
        return self._selected.buy_price * max(1, self.quantity)

    @property
    def can_buy(self) -> bool:
        return self._selected is not None and self._player_gold >= self.total_cost

    # -------------------------------------------------------- composition --
    def _build_components(self) -> None:
        self.clear_items()
        categories = sorted(self._by_category)
        if categories:
            self.add_item(_CategorySelect(self, categories))
        if self.category:
            entries = self._by_category.get(self.category, [])
            if entries:
                self.add_item(_ArticleSelect(self, entries))
        if self._selected is not None:
            for step in _QUANTITY_STEPS:
                self.add_item(_QuantityButton(self, step))
        self.add_item(_BuyButton(self, enabled=self.can_buy))
        self.add_item(_CloseButton(self))

    def _selection_payload(self) -> dict | None:
        if self._selected is None:
            return None
        item = self._selected.item_definition
        return {
            "kind": "purchase",
            "item_code": item.code,
            "item_name": item.name,
            "category_label": ITEM_CATEGORY_LABELS.get(item.category, item.category),
            "result_quantity": 1,
            "description": item.description or "",
            "stat_bonuses": item.stat_bonuses or {},
            "quantity": self.quantity,
            "unit_price": self._selected.buy_price,
            "owned": self._owned,
            "gold_cost": self.total_cost,
            "can_afford": self.can_buy,
            "blocking_reason": (
                ""
                if self.can_buy
                else f"Il te manque {format_int(self.total_cost - self._player_gold)} or."
            ),
        }

    def _info_rows(self) -> list[tuple[str, str]]:
        total = sum(len(v) for v in self._by_category.values())
        cats = " · ".join(
            f"{CATEGORY_ICONS.get(c, '📦')} {ITEM_CATEGORY_LABELS.get(c, c)}"
            for c in sorted(self._by_category)
        ) or "rien en rayon"
        return [
            ("Son étal", cats),
            ("Articles", f"{total} référence(s)"),
            ("Ta bourse", f"💰 {format_int(self._player_gold)} or"),
            ("Sa règle", "il achète, il ne reprend rien"),
        ]

    async def render(self) -> tuple[discord.Embed, discord.File]:
        path = panel_path(self.definition.code, self.player_id)
        selection = self._selection_payload()
        await asyncio.to_thread(
            compose_npc_panel,
            path,
            npc_name=self.definition.name,
            npc_title=self.definition.title,
            image_name=self.definition.image,
            accent=self.definition.accent,
            greeting=self.definition.greeting,
            selection=selection,
            info_rows=self._info_rows() if selection is None else None,
            seed=self.player_id,
        )
        filename = path.rsplit("/", 1)[-1]
        embed = discord.Embed(color=discord.Color.from_rgb(*self.definition.accent))
        embed.set_image(url=f"attachment://{filename}")
        return embed, discord.File(path, filename=filename)

    async def refresh(self, interaction: discord.Interaction) -> None:
        await asyncio.to_thread(self.refresh_data)
        self._build_components()
        embed, file = await self.render()
        await interaction.response.edit_message(
            embed=embed, attachments=[file], view=self,
        )


# --------------------------------------------------------------- éléments --
class _CategorySelect(discord.ui.Select):
    def __init__(self, view: MerchantView, categories: list[str]) -> None:
        options = [
            discord.SelectOption(
                label=ITEM_CATEGORY_LABELS.get(c, c),
                value=c,
                emoji=CATEGORY_ICONS.get(c),
                description=f"{len(view._by_category[c])} article(s)",
                default=(c == view.category),
            )
            for c in categories[:25]
        ]
        super().__init__(placeholder="1️⃣  Choisis un rayon", options=options)
        self._parent = view

    async def callback(self, interaction: discord.Interaction) -> None:
        self._parent.category = self.values[0]
        self._parent.item_code = None
        self._parent.quantity = 1
        await self._parent.refresh(interaction)


class _ArticleSelect(discord.ui.Select):
    def __init__(self, view: MerchantView, entries: list) -> None:
        options = [
            discord.SelectOption(
                label=s.item_definition.name[:100],
                value=s.item_definition.code,
                description=f"{format_int(s.buy_price)} or l'unité"[:100],
                default=(s.item_definition.code == view.item_code),
            )
            for s in entries[:25]
        ]
        super().__init__(placeholder="2️⃣  Choisis un article", options=options)
        self._parent = view

    async def callback(self, interaction: discord.Interaction) -> None:
        self._parent.item_code = self.values[0]
        self._parent.quantity = 1
        await self._parent.refresh(interaction)


class _QuantityButton(discord.ui.Button):
    def __init__(self, view: MerchantView, step: int) -> None:
        super().__init__(
            label=f"×{step}",
            style=(
                discord.ButtonStyle.primary
                if view.quantity == step
                else discord.ButtonStyle.secondary
            ),
            row=2,
        )
        self._parent = view
        self._step = step

    async def callback(self, interaction: discord.Interaction) -> None:
        self._parent.quantity = self._step
        await self._parent.refresh(interaction)


class _BuyButton(discord.ui.Button):
    def __init__(self, view: MerchantView, enabled: bool) -> None:
        super().__init__(
            label="Acheter",
            style=discord.ButtonStyle.success,
            emoji="💰",
            disabled=not enabled,
            row=3,
        )
        self._parent = view

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self._parent
        if parent._selected is None:
            await interaction.response.defer()
            return

        item_code = parent.item_code
        quantity = parent.quantity

        def _run():
            with parent._session_factory() as session:
                use_case = parent._buy_factory(session)
                return use_case.execute(
                    discord_id=parent._user.id,
                    username=parent._user.name,
                    display_name=parent._user.display_name,
                    item_code=item_code,
                    quantity=quantity,
                )

        result = await asyncio.to_thread(_run)
        if not result.success:
            await interaction.response.send_message(
                f"❌ {result.message}", ephemeral=True,
            )
            return
        await parent.refresh(interaction)
        await interaction.followup.send(
            f"💰 **{result.item_name}** ×{result.quantity} acheté pour "
            f"**{format_int(result.total_cost)} or**.",
            ephemeral=True,
        )


class _CloseButton(discord.ui.Button):
    def __init__(self, view: MerchantView) -> None:
        super().__init__(label="Fermer", style=discord.ButtonStyle.secondary, row=3)
        self._parent = view

    async def callback(self, interaction: discord.Interaction) -> None:
        for child in self._parent.children:
            child.disabled = True
        await interaction.response.edit_message(view=self._parent)
        self._parent.stop()
