import discord
from discord.ext import commands

from app.infrastructure.config.settings import settings


class SakuraBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        await self.load_extension("app.bot.cogs.player_cog")
        await self.load_extension("app.bot.cogs.encounter_cog")
        await self.tree.sync()


bot = SakuraBot()


@bot.event
async def on_ready() -> None:
    print(f"Connecté en tant que {bot.user}")


bot.run(settings.discord_token)