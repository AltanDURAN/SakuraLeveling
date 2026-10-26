"""Écran du marchand : portrait, menus en cascade, achat sans taper de code.

Même grammaire que les artisans — catégorie, puis article — pour que les trois
PNJ se manipulent de la même façon. La quantité se règle avec des boutons
plutôt qu'une saisie : c'est plus rapide et ça évite les fautes de frappe.

Un COSMÉTIQUE sélectionné s'accompagne d'un aperçu : l'en-tête de la bannière
/profil de l'acheteur, ce cosmétique porté avec le reste de sa tenue actuelle
(demande de l'auteur, 26/10/2026 : savoir ce qu'on achète).
"""

from __future__ import annotations

import asyncio

import discord

from app.bot.rendering.npc_panel import compose_npc_panel, panel_path
from app.domain.entities.artisan import MerchantDefinition
from app.domain.services.shop_pricing_service import ShopPricingService
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
        self._player_level = 1
        self._owned = 0
        #: Aperçu d'un cosmétique sélectionné : {"looks", "title", "name"}.
        self._preview: dict | None = None
        self._pricing = ShopPricingService()

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
            self._player_level = profile.progression.level if profile else 1


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

            self._preview = self._cosmetic_preview(session)

        if self.category and self.category not in self._by_category:
            self.category = None
            self.item_code = None

    def _cosmetic_preview(self, session) -> dict | None:
        """Tenue actuelle du joueur, le cosmétique sélectionné à sa place."""
        selected = self._selected
        if selected is None or selected.item_definition.category != "cosmetic":
            return None
        look = dict(selected.item_definition.stat_bonuses or {})
        slot = look.get("cosmetic")
        if not slot:
            return None
        from app.application.services.cosmetic_resolver import worn_cosmetics
        from app.infrastructure.db.repositories.player_title_repository import PlayerTitleRepository
        from app.infrastructure.titles.title_loader import get_definition as get_title

        looks = worn_cosmetics(session, self.player_id)
        looks[slot] = look
        code = PlayerTitleRepository(session).get_active_title_code(self.player_id)
        title = get_title(code) if code else None
        return {"looks": looks, "name": selected.item_definition.name,
                "title": f"{title.icon} {title.name}" if title else None}

    def unit_price(self, shop_item) -> int:
        return self._pricing.unit_buy_price(shop_item, self._player_level)

    @property
    def total_cost(self) -> int:
        if self._selected is None:
            return 0
        return self.unit_price(self._selected) * max(1, self.quantity)

    @property
    def limit_reached(self) -> bool:
        """Objet limité (un seul à la fois…) et déjà possédé."""
        s = self._selected
        return s is not None and s.max_owned > 0 and self._owned + self.quantity > s.max_owned

    @property
    def can_buy(self) -> bool:
        return (self._selected is not None and not self.limit_reached
                and self._player_gold >= self.total_cost)

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
            limit = self._selected.max_owned
            for step in _QUANTITY_STEPS:
                if not limit or step <= limit:
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
            "unit_price": self.unit_price(self._selected),
            "owned": self._owned,
            "gold_cost": self.total_cost,
            "can_afford": self.can_buy,
            "blocking_reason": (
                ""
                if self.can_buy
                else f"Tu en as déjà : {self._selected.max_owned} à la fois au plus."
                if self.limit_reached
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
            ("Sa règle", "il vend, il ne rachète rien"),
        ]

    async def render(self) -> tuple[list[discord.Embed], list[discord.File]]:
        path = panel_path(self.definition.code, self.player_id)
        selection = self._selection_payload()
        await asyncio.to_thread(
            compose_npc_panel,
            path,
            npc_name=self.definition.name,
            npc_title=self.definition.title,
            image_name=self.definition.image,
            accent=self.definition.accent,
            greeting=(self.definition.greeting if self._by_category else
                      "Mes caisses sont vides en ce moment. Les potions, c'est Elna "
                      "qui les prépare : va la voir avec /alchimiste."),
            selection=selection,
            info_rows=self._info_rows() if selection is None else None,
            seed=self.player_id,
        )
        filename = path.rsplit("/", 1)[-1]
        embed = discord.Embed(color=discord.Color.from_rgb(*self.definition.accent))
        embed.set_image(url=f"attachment://{filename}")
        embeds, files = [embed], [discord.File(path, filename=filename)]
        if self._preview is not None:
            preview = await self._render_preview()
            if preview is not None:
                embeds.append(preview[0])
                files.append(preview[1])
        return embeds, files

    async def _render_preview(self) -> tuple[discord.Embed, discord.File] | None:
        from app.bot.rank_roles import current_rank
        from app.bot.rendering.profile_banner import compose_cosmetic_preview
        from app.shared.paths import GENERATED_PROFILES_DIR

        GENERATED_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        path = GENERATED_PROFILES_DIR / f"apercu_boutique_{self.player_id}.png"
        avatar = getattr(getattr(self._user, "display_avatar", None), "url", None)
        rank = current_rank(self._user) if isinstance(self._user, discord.Member) else ""
        try:
            await asyncio.to_thread(
                compose_cosmetic_preview, str(path),
                display_name=self._user.display_name, avatar_url=avatar,
                title=self._preview["title"], rank_label=rank, cosmetics=self._preview["looks"],
            )
        except Exception:  # noqa: BLE001 — l'aperçu ne doit jamais bloquer l'achat
            return None
        embed = discord.Embed(
            title="🎨 Aperçu sur ta bannière /profil",
            description=(f"**{self._preview['name']}**, avec le reste de ta tenue actuelle. "
                         "Une fois acheté, porte-le avec `/apparence`."),
            color=discord.Color.from_rgb(214, 120, 170),
        )
        embed.set_image(url=f"attachment://{path.name}")
        return embed, discord.File(str(path), filename=path.name)

    async def refresh(self, interaction: discord.Interaction) -> None:
        await asyncio.to_thread(self.refresh_data)
        self._build_components()
        embeds, files = await self.render()
        await interaction.response.edit_message(
            embeds=embeds, attachments=files, view=self,
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
        self._owner = view

    async def callback(self, interaction: discord.Interaction) -> None:
        self._owner.category = self.values[0]
        self._owner.item_code = None
        self._owner.quantity = 1
        await self._owner.refresh(interaction)


class _ArticleSelect(discord.ui.Select):
    def __init__(self, view: MerchantView, entries: list) -> None:
        options = [
            discord.SelectOption(
                label=s.item_definition.name[:100],
                value=s.item_definition.code,
                description=(
                    f"{format_int(view.unit_price(s))} or"
                    + (f" ({s.price_per_level} × ton niveau)" if s.price_per_level else " l'unité")
                    + (" · un seul à la fois" if s.max_owned == 1 else "")
                )[:100],
                default=(s.item_definition.code == view.item_code),
            )
            for s in entries[:25]
        ]
        super().__init__(placeholder="2️⃣  Choisis un article", options=options)
        self._owner = view

    async def callback(self, interaction: discord.Interaction) -> None:
        self._owner.item_code = self.values[0]
        self._owner.quantity = 1
        await self._owner.refresh(interaction)


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
        self._owner = view
        self._step = step

    async def callback(self, interaction: discord.Interaction) -> None:
        self._owner.quantity = self._step
        await self._owner.refresh(interaction)


class _BuyButton(discord.ui.Button):
    def __init__(self, view: MerchantView, enabled: bool) -> None:
        super().__init__(
            label="Acheter",
            style=discord.ButtonStyle.success,
            emoji="💰",
            disabled=not enabled,
            row=3,
        )
        self._owner = view

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self._owner
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
        self._owner = view

    async def callback(self, interaction: discord.Interaction) -> None:
        for child in self._owner.children:
            child.disabled = True
        await interaction.response.edit_message(view=self._owner)
        self._owner.stop()
