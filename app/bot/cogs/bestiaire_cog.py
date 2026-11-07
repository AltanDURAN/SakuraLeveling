"""Cog `/bestiaire` — les monstres (`/bestiaire monstres`) et les world boss
(`/bestiaire boss`, ex-`/boss list`), une page par entrée.

Bestiaire À DÉCOUVRIR (07/11/2026) : un monstre que le joueur n'a pas encore
vaincu en combat de zone, ou un boss qu'il n'a jamais aidé à abattre, n'est
qu'une silhouette ; vaincu, sa fiche complète et le nombre de victoires.
"""

import discord
from discord import app_commands
from discord.ext import commands

from app.bot.views.bestiaire_view import BestiaireView
from app.bot.views.boss_bestiary_view import BossBestiaryView
from app.domain.services.power_score_service import PowerScoreService
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.repositories.player_kill_repository import PlayerKillRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.world_boss_repository import WorldBossRepository
from app.infrastructure.config.settings import settings
from app.infrastructure.world_boss.boss_definition_loader import list_definitions
from app.infrastructure.encounters.farm_zone_loader import unreleased_families
from app.infrastructure.db.session import get_db_session
from app.bot.cogs._mixins import BetaChannelOnlyMixin


class BestiaireCog(BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    bestiaire = app_commands.Group(name="bestiaire", description="Les monstres et les world boss, à découvrir")

    @bestiaire.command(
        name="monstres",
        description="Les monstres, à découvrir : bats-en un pour voir sa fiche et tes victoires",
    )
    async def monstres(self, interaction: discord.Interaction) -> None:
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


    @bestiaire.command(
        name="boss",
        description="Les world boss, à découvrir : abats-en un en raid pour voir sa fiche",
    )
    async def boss(self, interaction: discord.Interaction) -> None:
        bosses = list_definitions()
        if not bosses:
            await interaction.response.send_message("ℹ️ Aucun world boss dans le jeu.", ephemeral=True)
            return
        with get_db_session() as session:
            items = {i.code: i for i in ItemRepository(session).list_all()}
            # Boss abattus avec lui (au moins un assaut) : les autres restent
            # des silhouettes. Pas encore de profil ⇒ rien de découvert.
            profile = PlayerRepository(session).get_by_discord_id(interaction.user.id)
            victories = WorldBossRepository(session).victories_by_code(profile.player.id) if profile else {}
        view = BossBestiaryView(author_id=interaction.user.id, bosses=bosses, items=items,
                                victories=victories, boss_channel_id=settings.boss_channel_id)
        embed, file = await view.render()
        await interaction.response.send_message(
            embed=embed, file=file if file is not None else discord.utils.MISSING, view=view,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BestiaireCog(bot))
