import discord
from discord import app_commands
from discord.ext import commands

from app.application.use_cases.get_player_profile import GetPlayerProfileUseCase
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session


class PlayerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="profile", description="Afficher votre profil joueur")
    async def profile(self, interaction: discord.Interaction) -> None:
        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            use_case = GetPlayerProfileUseCase(player_repository)

            profile = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )

        message = (
            f"**Profil de {profile.player.display_name}**\n"
            f"Niveau : {profile.progression.level}\n"
            f"XP : {profile.progression.xp}\n"
            f"Gold : {profile.resources.gold}"
        )

        await interaction.response.send_message(message)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PlayerCog(bot))