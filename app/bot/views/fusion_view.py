"""Écran de fusion chez un artisan (équipement v2).

Borak (armes, boucliers, tête, corps) et Elna (accessoires) ne fabriquent plus :
ils FUSIONNENT. Le joueur choisit une pièce dont il a au moins deux copies de
même rareté, voit le coût (or + matériaux de la famille du monstre) et les
stats avant / après, puis fusionne. Même panneau PNJ que le reste du jeu ;
leur maîtrise monte à chaque fusion et réduit l'or demandé.
"""

from __future__ import annotations

import asyncio

import discord

from app.application.use_cases.fuse_gear import FuseGearUseCase
from app.bot.rendering.npc_panel import compose_npc_panel, panel_path
from app.domain.entities.artisan import ArtisanDefinition
from app.domain.services.gear_service import RARITY_EMOJIS, RARITY_LABELS
from app.shared.emoji_mappings import format_stat_bonuses_short
from app.shared.formatters import format_int


def _rarity(r: str | None) -> str:
    return RARITY_LABELS.get(r or "", r or "").lower()


class FusionView(discord.ui.View):
    def __init__(self, *, definition: ArtisanDefinition, player_id: int,
                 session_factory, artisan_service, timeout: float = 300.0) -> None:
        super().__init__(timeout=timeout)
        self.definition = definition
        self.player_id = player_id
        self._session_factory = session_factory
        self.artisans = artisan_service
        self.selected: tuple[str, str] | None = None   # (code, rareté)
        self._candidates: list = []
        self._preview = None
        self._orders_completed = 0
        self.last_message: str | None = None

    # ------------------------------------------------------------ données --
    def refresh_data(self) -> None:
        with self._session_factory() as session:
            uc = FuseGearUseCase(session, self.artisans)
            self._candidates = uc.candidates(self.definition, self.player_id)
            self._orders_completed = uc.orders.orders_completed(self.player_id, self.definition.code)
            keys = {(c.item_code, c.rarity) for c in self._candidates}
            if self.selected not in keys:
                self.selected = None
            self._preview = uc.preview(self.definition, self.player_id, *self.selected) if self.selected else None

    def build(self) -> None:
        self.clear_items()
        if self._candidates:
            self.add_item(_PieceSelect(self))
        self.add_item(_FuseButton(self))
        self.add_item(_CloseButton(self))

    # -------------------------------------------------------------- rendu --
    def _info_rows(self) -> list[tuple[str, str]]:
        p = self._preview
        if p is None:
            fusable = sum(1 for c in self._candidates if c.copies >= 2 and c.rarity not in ("legendary", "mythic"))
            return [
                ("Son métier", "fusionner deux copies identiques en une plus rare"),
                ("Il lui faut", "2 copies de même rareté, de l'or et des matériaux"),
                ("Tes pièces", f"{len(self._candidates)} lot(s) · {fusable} fusionnable(s)"),
                ("Limite", "le légendaire ne se fusionne plus, le mythique ne s'obtient qu'au combat"),
            ]
        rows = [
            ("Pièce", f"{RARITY_EMOJIS.get(p.rarity, '')} {p.item_name} — {_rarity(p.rarity)} ×{p.copies}"),
        ]
        if p.target_rarity:
            rows += [
                ("Devient", f"{RARITY_EMOJIS.get(p.target_rarity, '')} {_rarity(p.target_rarity)}"),
                ("Stats", f"{format_stat_bonuses_short(p.stats_now)}  →  {format_stat_bonuses_short(p.stats_next)}"),
                ("Or", f"💰 {format_int(p.gold_cost)} (tu as {format_int(p.player_gold)})"),
            ]
            if p.material_needed:
                rows.append(("Matériaux", f"{p.material_needed} × {p.material_name} (tu en as {p.material_owned})"))
        if p.blocking_reason:
            rows.append(("Bloqué", p.blocking_reason))
        return rows

    async def render(self) -> tuple[discord.Embed, discord.File]:
        tier = self.artisans.tier_for(self.definition, self._orders_completed)
        path = panel_path(self.definition.code, self.player_id)
        await asyncio.to_thread(
            compose_npc_panel, path,
            npc_name=self.definition.name, npc_title=self.definition.title,
            image_name=self.definition.image, accent=self.definition.accent,
            greeting=self.last_message or tier.quote or self.definition.greeting,
            tier_name=tier.name, tier_level=tier.level, tier_total=len(self.definition.tiers),
            tier_progress=self.artisans.tier_progress(self.definition, self._orders_completed),
            orders_completed=self._orders_completed,
            orders_to_next=self.artisans.orders_until_next_tier(self.definition, self._orders_completed),
            info_rows=self._info_rows(), seed=self.player_id,
        )
        filename = path.rsplit("/", 1)[-1]
        embed = discord.Embed(color=discord.Color.from_rgb(*self.definition.accent))
        embed.set_image(url=f"attachment://{filename}")
        return embed, discord.File(path, filename=filename)

    async def refresh(self, interaction: discord.Interaction) -> None:
        await asyncio.to_thread(self.refresh_data)
        self.build()
        embed, file = await self.render()
        await interaction.response.edit_message(embed=embed, attachments=[file], view=self)


class _PieceSelect(discord.ui.Select):
    def __init__(self, view: FusionView) -> None:
        options = []
        for c in view._candidates[:25]:
            fusable = c.copies >= 2 and c.rarity not in ("legendary", "mythic")
            options.append(discord.SelectOption(
                label=f"{c.item_name} — {_rarity(c.rarity)} ×{c.copies}"[:100],
                value=f"{c.item_code}|{c.rarity}",
                emoji=RARITY_EMOJIS.get(c.rarity),
                description=("prête à fusionner" if fusable
                             else "ne se fusionne plus" if c.rarity in ("legendary", "mythic")
                             else "il faut une 2e copie")[:100],
                default=view.selected == (c.item_code, c.rarity),
            ))
        super().__init__(placeholder="Choisis la pièce à fusionner", options=options, row=0)
        self._owner = view

    async def callback(self, interaction: discord.Interaction) -> None:
        code, rarity = self.values[0].split("|", 1)
        self._owner.selected = (code, rarity)
        self._owner.last_message = None
        await self._owner.refresh(interaction)


class _FuseButton(discord.ui.Button):
    def __init__(self, view: FusionView) -> None:
        p = view._preview
        label = "Fusionner"
        if p is not None and p.target_rarity:
            label = f"Fusionner → {_rarity(p.target_rarity)} ({format_int(p.gold_cost)} or)"
        super().__init__(label=label[:80], emoji="🔨", style=discord.ButtonStyle.success,
                         disabled=not (p is not None and p.can_fuse), row=1)
        self._owner = view

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self._owner
        if view.selected is None:
            await interaction.response.defer()
            return

        def _run():
            with view._session_factory() as session:
                return FuseGearUseCase(session, view.artisans).fuse(
                    view.definition, view.player_id, *view.selected)

        result = await asyncio.to_thread(_run)
        view.last_message = result.message.replace("**", "") if result.success else None
        if not result.success:
            await interaction.response.send_message(result.message, ephemeral=True)
            return
        if result.new_rarity:
            view.selected = (view.selected[0], result.new_rarity)
        await view.refresh(interaction)


class _CloseButton(discord.ui.Button):
    def __init__(self, view: FusionView) -> None:
        super().__init__(label="Partir", style=discord.ButtonStyle.secondary, row=1)
        self._owner = view

    async def callback(self, interaction: discord.Interaction) -> None:
        for child in self._owner.children:
            child.disabled = True
        await interaction.response.edit_message(view=self._owner)
        self._owner.stop()
