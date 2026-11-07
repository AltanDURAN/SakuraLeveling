"""Cog `/bestiaire` — vue paginée des monstres et leurs stats, par famille.

Bestiaire À DÉCOUVRIR (07/11/2026) : un monstre que le joueur n'a pas encore
vaincu en combat de zone n'est qu'une silhouette ; vaincu, sa fiche complète
(drops, stats, famille) et le nombre de victoires du joueur contre lui.
"""

import discord
from discord import app_commands
from discord.ext import commands

from app.bot.views.bestiaire_view import BestiaireView
from app.domain.services.power_score_service import PowerScoreService
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.repositories.player_kill_repository import PlayerKillRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.encounters.farm_zone_loader import unreleased_families
from app.infrastructure.db.session import get_db_session
from app.bot.cogs._mixins import BetaChannelOnlyMixin


class BestiaireCog(BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="bestiaire",
        description="Bestiaire à découvrir : bats un monstre pour voir sa fiche et tes victoires",
    )
    async def bestiaire(self, interaction: discord.Interaction) -> None:
        with get_db_session() as session:
            hidden = unreleased_families()  # zones pas encore ouvertes
            mobs = [m for m in MobRepository(session).list_all() if m.family not in hidden]
            items = {i.code: i for i in ItemRepository(session).list_all()}
            # Victoires du joueur (combats de zone) : un monstre jamais vaincu
            # reste une silhouette. Pas encore de profil ⇒ rien de découvert.
            profile = PlayerRepository(session).get_by_discord_id(interaction.user.id)
            kills = PlayerKillRepository(session).get_kills_per_mob(profile.player.id) if profile else {}

        if not mobs:
            await interaction.response.send_message(
                "ℹ️ Aucun monstre dans le bestiaire.", ephemeral=True,
            )
            return

        # Tri par SCORE DE PUISSANCE croissant (du plus faible au plus fort).
        pss = PowerScoreService()
        mobs_sorted = sorted(mobs, key=lambda m: pss.calculate_from_mob(m))

        view = BestiaireView(author_id=interaction.user.id, mobs=mobs_sorted, items=items, kills=kills)
        embed, file = await view.render()
        await interaction.response.send_message(
            embed=embed, file=file if file is not None else discord.utils.MISSING,
            view=view,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BestiaireCog(bot))
