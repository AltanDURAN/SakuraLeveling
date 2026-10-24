"""Cog `/panoplie` : bonus de panoplie du joueur et choix de son TYPE.

Saison 1 : plus de familles d'objets. Le bonus vient des pièces portées de
même rareté (paliers 2 / 4 / 7, comptage cumulatif — cf. set_bonus_service).
La commande montre ce que rapporte chaque rareté et propose un menu pour
choisir le type de bonus (un seul, tous les paliers s'y additionnent).
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.application.services.set_bonus_resolver import resolve_set_bonuses
from app.bot.cogs._mixins import BetaChannelOnlyMixin
from app.domain.services.gear_service import RARITY_EMOJIS, RARITY_LABELS
from app.domain.services.set_bonus_service import (
    PANOPLIE_TYPES,
    TIERS,
    format_panoplie_value,
    panoplie_type,
)
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session


def build_panoplie_embed(set_bonuses) -> discord.Embed:
    kind = panoplie_type(set_bonuses.bonus_type)
    embed = discord.Embed(
        title=f"🌸 Panoplie — {kind.emoji} {kind.label}",
        color=discord.Color.from_rgb(220, 130, 180),
        description=(
            "Porte des pièces de même rareté : à **2**, **4** et **7** pièces, "
            "chaque rareté donne un bonus (×1 · ×1,5 · ×3). Une pièce compte pour "
            "sa rareté **et toutes celles en dessous** ; une arme à deux mains "
            "compte pour 2. Tous les bonus s'ajoutent dans le type choisi."
        ),
    )
    lines = []
    for tier in set_bonuses.tiers:
        label = f"{RARITY_EMOJIS.get(tier.rarity, '')} **{RARITY_LABELS.get(tier.rarity, tier.rarity)}** ou mieux · {tier.pieces} pièce(s)"
        if tier.multiplier:
            label += f" · ×{tier.multiplier:g} → {format_panoplie_value(kind, round(tier.value, 1))}"
        if tier.next_tier:
            label += f" · _palier suivant à {tier.next_tier}_"
        lines.append(label)
    embed.add_field(
        name="Tes pièces portées",
        value="\n".join(lines) or "_Aucune pièce portée._",
        inline=False,
    )
    embed.add_field(
        name="Bonus total",
        value=f"**{format_panoplie_value(kind, set_bonuses.total)}**",
        inline=False,
    )
    simple = ", ".join(
        f"{t.emoji} {t.label} {format_panoplie_value(t, t.base).split(' ')[0]}"
        for t in PANOPLIE_TYPES.values()
    )
    embed.set_footer(text=f"Bonus simple (2 pièces, commun) : {simple}. "
                          f"Paliers : {', '.join(f'{n} pièces ×{m:g}' for n, m in reversed(TIERS))}.")
    return embed


class PanoplieTypeView(discord.ui.View):
    def __init__(self, owner_discord_id: int, current: str) -> None:
        super().__init__(timeout=300)
        self.add_item(_TypeSelect(owner_discord_id, current))


class _TypeSelect(discord.ui.Select):
    def __init__(self, owner_discord_id: int, current: str) -> None:
        options = [
            discord.SelectOption(
                label=t.label, value=t.code, emoji=t.emoji,
                description=f"Bonus simple : {format_panoplie_value(t, t.base).split(' ')[0]}",
                default=t.code == current,
            )
            for t in PANOPLIE_TYPES.values()
        ]
        super().__init__(placeholder="Choisis ton type de bonus", options=options)
        self._owner_id = owner_discord_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self._owner_id:
            await interaction.response.send_message("Ce menu n'est pas pour toi.", ephemeral=True)
            return
        choice = self.values[0]
        with get_db_session() as session:
            repo = PlayerRepository(session)
            profile = repo.get_by_discord_id(interaction.user.id)
            if profile is None:
                await interaction.response.send_message("Profil introuvable.", ephemeral=True)
                return
            repo.set_panoplie_bonus(profile.player.id, choice)
            equipped = EquipmentRepository(session).list_by_player_id(profile.player.id)
        bonuses = resolve_set_bonuses(equipped, choice)
        await interaction.response.edit_message(
            embed=build_panoplie_embed(bonuses),
            view=PanoplieTypeView(interaction.user.id, choice),
        )


class PanoplieCog(BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="panoplie",
        description="Ton bonus de panoplie (raretés portées) et le choix de son type",
    )
    async def panoplie(self, interaction: discord.Interaction) -> None:
        with get_db_session() as session:
            profile = PlayerRepository(session).get_or_create_by_discord_id(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )
            equipped = EquipmentRepository(session).list_by_player_id(profile.player.id)
            current = profile.player.panoplie_bonus
        bonuses = resolve_set_bonuses(equipped, current)
        await interaction.response.send_message(
            embed=build_panoplie_embed(bonuses),
            view=PanoplieTypeView(interaction.user.id, current),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PanoplieCog(bot))
