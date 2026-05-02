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
        await self.load_extension("app.bot.cogs.leaderboard_cog")
        await self.load_extension("app.bot.cogs.admin_cog")
        await self.load_extension("app.bot.cogs.shop_cog")
        await self.load_extension("app.bot.cogs.skill_cog")
        await self.load_extension("app.bot.cogs.trade_cog")
        await self.load_extension("app.bot.cogs.world_boss_cog")
        await self.load_extension("app.bot.cogs.help_cog")
        await self.load_extension("app.bot.cogs.title_cog")
        await self.load_extension("app.bot.cogs.weekly_quest_cog")
        await self.load_extension("app.bot.cogs.daily_quest_cog")
        await self.load_extension("app.bot.cogs.brocante_cog")
        await self.tree.sync()


bot = SakuraBot()


@bot.event
async def on_ready() -> None:
    print(f"Connecté en tant que {bot.user}")


bot.run(settings.discord_token)