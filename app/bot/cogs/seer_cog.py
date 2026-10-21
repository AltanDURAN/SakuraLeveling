"""Cog de la voyante : `/voyante`.

Ysaline lit le talent caché d'un élément contre une prestation dont le prix
monte à chaque lecture (cf. `views/seer_view.py`).
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.bot.cogs._mixins import BetaChannelOnlyMixin
from app.bot.views.seer_view import open_seer
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session


class SeerCog(BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="voyante",
        description="Consulter Ysaline, la voyante : elle lit ton talent caché dans un élément",
    )
    async def voyante(self, interaction: discord.Interaction) -> None:
        with get_db_session() as session:
            profile = PlayerRepository(session).get_or_create_by_discord_id(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )
            player_id = profile.player.id
        await open_seer(interaction, get_db_session, player_id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SeerCog(bot))
