"""Chez Elna, l'alchimiste (`/alchimiste`) : on choisit une potion, on voit
les ingrédients (matériaux de famille) et l'or de confection, puis on en fait
préparer une, cinq ou le maximum. Même panneau PNJ que le reste du jeu ; sa
maîtrise compte les potions préparées. Toujours éphémère.
"""

from __future__ import annotations

import asyncio

import discord

from app.application.use_cases.brew_potion import AlchemyStatus, BrewPotionUseCase
from app.bot.rendering.npc_panel import compose_npc_panel, panel_path
from app.domain.services.artisan_service import ArtisanService
from app.infrastructure.artisans import artisan_loader
from app.shared.formatters import format_int


def _ingredients_text(recipe, count: int = 1) -> str:
    return " + ".join(
        f"{i.needed * count} × {i.name}" + ("" if i.owned >= i.needed * count else f" (tu en as {i.owned})")
        for i in recipe.ingredients
    )


class AlchemyView(discord.ui.View):
    def __init__(self, player_id: int, session_factory, timeout: float = 300.0) -> None:
        super().__init__(timeout=timeout)
        self.definition = artisan_loader.get_alchemist()
        self.player_id = player_id
        self._session_factory = session_factory
        self.status: AlchemyStatus | None = None
        self.selected: str | None = None
        self.last_message: str | None = None

    # ------------------------------------------------------------ données --
    def refresh_data(self) -> None:
        with self._session_factory() as session:
            self.status = BrewPotionUseCase(session, self.definition).status(self.player_id)
        if self.selected and self.status.recipe(self.selected) is None:
            self.selected = None

    @property
    def recipe(self):
        return self.status.recipe(self.selected) if self.status and self.selected else None

    def build(self) -> None:
        self.clear_items()
        if self.status and self.status.recipes:
            self.add_item(_RecipeSelect(self))
        recipe = self.recipe
        counts = []
        if recipe is not None and recipe.max_count:
            # ×1, ×5 et le maximum possible (sans doublon).
            counts = sorted({n for n in (1, 5) if n <= recipe.max_count} | {recipe.max_count})
        for n in counts or [1]:
            self.add_item(_BrewButton(self, n, enabled=bool(counts)))
        self.add_item(_CloseButton(self))

    # -------------------------------------------------------------- rendu --
    def _info_rows(self) -> list[tuple[str, str]]:
        st = self.status
        recipe = self.recipe
        if recipe is None:
            return [
                ("Son art", "préparer des potions avec ce que les monstres laissent"),
                ("Il lui faut", "tes matériaux de famille et de l'or pour le feu"),
                ("Ses potions", f"{len(st.recipes)} recettes · soins, mana, élixirs"),
                ("Élixirs", "combats de zone et world boss seulement"),
                ("Ta bourse", f"💰 {format_int(st.gold)} or"),
            ]
        return [
            ("Potion", f"🧪 {recipe.item_name} (tu en as {recipe.owned})"),
            ("Effet", recipe.effect),
            ("Ingrédients", _ingredients_text(recipe)),
            ("Confection", f"💰 {format_int(recipe.unit_fee)} or la potion (tu as {format_int(st.gold)})"),
            ("Possible", f"{recipe.max_count} d'un coup" if recipe.max_count else "il te manque de quoi la faire"),
        ]

    async def render(self) -> tuple[discord.Embed, discord.File]:
        st = self.status
        service = ArtisanService()
        path = panel_path(self.definition.code, self.player_id)
        await asyncio.to_thread(
            compose_npc_panel, path,
            npc_name=self.definition.name, npc_title=self.definition.title,
            image_name=self.definition.image, accent=self.definition.accent,
            greeting=self.last_message or st.tier.quote or self.definition.greeting,
            tier_name=st.tier.name, tier_level=st.tier.level, tier_total=len(self.definition.tiers),
            tier_progress=service.tier_progress(self.definition, st.orders_completed),
            orders_completed=st.orders_completed,
            orders_to_next=service.orders_until_next_tier(self.definition, st.orders_completed),
            orders_unit="potion(s)",
            info_rows=self._info_rows(), seed=self.player_id,
        )
        filename = path.rsplit("/", 1)[-1]
        embed = discord.Embed(color=discord.Color.from_rgb(*self.definition.accent))
        embed.set_image(url=f"attachment://{filename}")
        perks = []
        if st.tier.gold_discount_pct:
            perks.append(f"−{st.tier.gold_discount_pct} % sur la confection")
        if st.tier.bonus_pct:
            perks.append(f"{st.tier.bonus_pct} % de chance d'une potion offerte")
        embed.set_footer(text="Maîtrise : " + (" · ".join(perks) if perks else "pas encore d'avantage")
                         + " · on boit avec /utiliser")
        return embed, discord.File(path, filename=filename)

    async def refresh(self, interaction: discord.Interaction) -> None:
        await asyncio.to_thread(self.refresh_data)
        self.build()
        embed, file = await self.render()
        await interaction.response.edit_message(embed=embed, attachments=[file], view=self)


class _RecipeSelect(discord.ui.Select):
    def __init__(self, view: AlchemyView) -> None:
        options = [
            discord.SelectOption(
                label=f"{r.item_name} — {format_int(r.unit_fee)} or"[:100],
                value=r.item_code, emoji="🧪",
                description=(f"{r.effect} · " + _ingredients_text(r))[:100],
                default=r.item_code == view.selected,
            )
            for r in view.status.recipes[:25]
        ]
        super().__init__(placeholder="Quelle potion veux-tu ?", options=options, row=0)
        self._owner = view

    async def callback(self, interaction: discord.Interaction) -> None:
        self._owner.selected = self.values[0]
        self._owner.last_message = None
        await self._owner.refresh(interaction)


class _BrewButton(discord.ui.Button):
    def __init__(self, view: AlchemyView, count: int, enabled: bool) -> None:
        recipe = view.recipe
        if recipe is None:
            label = "Préparer"
        else:
            label = f"Préparer ×{count} ({format_int(recipe.unit_fee * count)} or)"
        super().__init__(label=label[:80], emoji="🧪", style=discord.ButtonStyle.success,
                         disabled=not enabled, row=1)
        self._owner = view
        self._count = count

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self._owner
        if view.selected is None:
            await interaction.response.defer()
            return

        def _run():
            with view._session_factory() as session:
                return BrewPotionUseCase(session, view.definition).brew(
                    view.player_id, view.selected, self._count)

        result = await asyncio.to_thread(_run)
        if not result.success:
            await interaction.response.send_message(result.message, ephemeral=True)
            return
        view.last_message = result.message.replace("**", "")
        await view.refresh(interaction)


class _CloseButton(discord.ui.Button):
    def __init__(self, view: AlchemyView) -> None:
        super().__init__(label="Partir", style=discord.ButtonStyle.secondary, row=1)
        self._owner = view

    async def callback(self, interaction: discord.Interaction) -> None:
        for child in self._owner.children:
            child.disabled = True
        await interaction.response.edit_message(view=self._owner)
        self._owner.stop()
