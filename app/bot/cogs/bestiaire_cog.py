"""Cog `/bestiaire` — vue paginée des mobs et leurs stats.

Lecture seule : sert de référence pour les joueurs qui veulent connaître
les drops, stats et familles des monstres rencontrables.
"""

import discord
from discord import app_commands
from discord.ext import commands

from app.bot.views.bestiaire_view import BestiaireView
from app.domain.services.power_score_service import PowerScoreService
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.session import get_db_session


class BestiaireCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.channel_id != settings.beta_channel_id:
            message = (
                "🚧 Le bot est actuellement en phase de test.\n"
                "Utilisez le channel beta dédié."
            )
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return False
        return True

    @app_commands.command(
        name="bestiaire",
        description="Catalogue des monstres : stats et drops, 1 par page",
    )
    async def bestiaire(self, interaction: discord.Interaction) -> None:
        with get_db_session() as session:
            mobs = MobRepository(session).list_all()

        if not mobs:
            await interaction.response.send_message(
                "ℹ️ Aucun monstre dans le bestiaire.", ephemeral=True,
            )
            return

        # Tri par SCORE DE PUISSANCE croissant (du plus faible au plus fort).
        pss = PowerScoreService()
        mobs_sorted = sorted(mobs, key=lambda m: pss.calculate_from_mob(m))

        view = BestiaireView(author_id=interaction.user.id, mobs=mobs_sorted)
        embed, file = view.render_current()
        await interaction.response.send_message(
            embed=embed, file=file if file is not None else discord.utils.MISSING,
            view=view,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BestiaireCog(bot))
