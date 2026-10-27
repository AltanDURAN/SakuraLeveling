"""Cog `/tour` : la tour solo (27/10/2026, décisions de l'auteur).

100 étages, les mêmes pour tous, 1 à 4 monstres par étage, un boss tous les
10. Seul, à PV et mana pleins, sans potion ni élixir. Une victoire garde le
ticket et fait avancer le record ; une défaite coûte le ticket, jamais un
étage. Règles : `tower_service` ; persistance : `use_cases/tower`.
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from app.application.use_cases import tower
from app.bot.cogs._mixins import BetaChannelOnlyMixin
from app.bot.embeds.tower_embeds import build_attempt_embed, build_daily_embed, build_status_embed
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.tower import tower_loader

_logger = logging.getLogger("sakura.tower")


def _material_names(session) -> dict[str, str]:
    """Noms des matériaux de fusion des étages (pour l'affichage)."""
    codes = {tower_loader.floor_material(f) for f in range(1, tower_loader.floor_count() + 1)}
    items = ItemRepository(session)
    names = {}
    for code in filter(None, codes):
        item = items.get_by_code(code)
        if item is not None:
            names[code] = item.name
    return names


def _profile(session, user):
    return PlayerRepository(session).get_or_create_by_discord_id(
        discord_id=user.id, username=user.name, display_name=user.display_name,
    )


def _status(user):
    with get_db_session() as session:
        profile = _profile(session, user)
        state = tower.status(session, profile)
        return state, profile.player.display_name, _material_names(session)


def _attempt(user):
    with get_db_session() as session:
        profile = _profile(session, user)
        try:
            outcome = tower.attempt(session, profile)
        except tower.TowerError as e:
            return None, str(e), {}
        return outcome, None, _material_names(session)


def _claim(user):
    with get_db_session() as session:
        profile = _profile(session, user)
        try:
            reward = tower.claim_daily(session, profile)
        except tower.TowerError as e:
            return None, str(e), 0, {}
        best = tower.status(session, profile).best_floor
        return reward, None, best, _material_names(session)


class TowerView(discord.ui.View):
    """Boutons de `/tour`, réservés à celui qui a ouvert la tour."""

    def __init__(self, owner_id: int, state: tower.TowerStatus) -> None:
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self._sync(state)

    def _sync(self, state: tower.TowerStatus) -> None:
        self.climb.disabled = state.next_floor is None or state.tickets.available <= 0
        self.climb.label = (f"Tenter l'étage {state.next_floor}" if state.next_floor else "Tour terminée")
        self.daily.disabled = state.daily_claimed or state.daily.is_empty

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Ouvre ta propre tour avec /tour.", ephemeral=True)
            return False
        return True

    async def _refresh(self, interaction: discord.Interaction) -> None:
        state, name, names = await asyncio.to_thread(_status, interaction.user)
        self._sync(state)
        try:
            await interaction.message.edit(embed=build_status_embed(state, name, names), view=self)
        except discord.HTTPException:
            _logger.warning("rafraîchissement de /tour échoué", exc_info=True)

    @discord.ui.button(label="Tenter l'étage", emoji="⚔️", style=discord.ButtonStyle.danger)
    async def climb(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        outcome, error, names = await asyncio.to_thread(_attempt, interaction.user)
        if error:
            await interaction.followup.send(error, ephemeral=True)
        else:
            await interaction.followup.send(embed=build_attempt_embed(outcome, names))
        await self._refresh(interaction)

    @discord.ui.button(label="Récompense du jour", emoji="🎁", style=discord.ButtonStyle.success)
    async def daily(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        reward, error, best, names = await asyncio.to_thread(_claim, interaction.user)
        if error:
            await interaction.followup.send(error, ephemeral=True)
        else:
            await interaction.followup.send(embed=build_daily_embed(reward, best, names))
        await self._refresh(interaction)


class TowerCog(BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="tour", description="La tour solo : 100 étages, ton record, ta récompense du jour")
    async def tour(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        state, name, names = await asyncio.to_thread(_status, interaction.user)
        await interaction.followup.send(embed=build_status_embed(state, name, names),
                                        view=TowerView(interaction.user.id, state))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TowerCog(bot))
