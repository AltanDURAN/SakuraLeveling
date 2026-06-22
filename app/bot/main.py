"""Point d'entrée du bot Discord.

Configure le logging structuré + un gestionnaire d'erreur global pour les
slash commands (un user n'a jamais une erreur opaque, et l'erreur est journalisée
côté serveur), et tolère qu'un cog cassé n'empêche pas le démarrage des autres.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from app.infrastructure.config.settings import settings


# Logging structuré dès le démarrage. Sans ça, en prod systemd, journalctl
# ne capte que les print/tracebacks bruts → diagnostic difficile (cf. audit A4).
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)-8s] %(name)s: %(message)s",
)
_logger = logging.getLogger("sakura.bot")


_COG_MODULES = [
    "app.bot.cogs.player_cog",
    "app.bot.cogs.encounter_cog",
    "app.bot.cogs.leaderboard_cog",
    "app.bot.cogs.admin_cog",
    "app.bot.cogs.shop_cog",
    "app.bot.cogs.skill_cog",
    "app.bot.cogs.competences_cog",
    "app.bot.cogs.trade_cog",
    "app.bot.cogs.world_boss_cog",
    "app.bot.cogs.help_cog",
    "app.bot.cogs.title_cog",
    "app.bot.cogs.weekly_quest_cog",
    "app.bot.cogs.daily_quest_cog",
    "app.bot.cogs.brocante_cog",
    "app.bot.cogs.chad_cog",
    "app.bot.cogs.bestiaire_cog",
    "app.bot.cogs.panoplie_cog",
]


class SakuraBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        # Tolérance par cog : si l'un plante au load, on logge et on continue
        # plutôt que de bloquer tout le démarrage (cf. audit A4).
        loaded, failed = 0, 0
        for module in _COG_MODULES:
            try:
                await self.load_extension(module)
                loaded += 1
            except Exception:
                failed += 1
                _logger.exception("Échec du chargement du cog %s", module)
        _logger.info("Cogs chargés : %d/%d (%d échec(s))",
                     loaded, len(_COG_MODULES), failed)
        await self.tree.sync()


bot = SakuraBot()


@bot.event
async def on_ready() -> None:
    _logger.info("Connecté en tant que %s (id=%s)", bot.user, bot.user.id if bot.user else "?")


@bot.tree.error
async def _on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    """Filet de sécurité global : un user n'a jamais d'erreur opaque, et la
    stack trace part dans les logs (cf. audit A4)."""
    _logger.exception(
        "Erreur slash command /%s (user=%s) : %s",
        getattr(interaction.command, "qualified_name", "?"),
        interaction.user.id, error,
    )
    msg = "❌ Une erreur est survenue. L'incident a été journalisé."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except discord.HTTPException:
        # Interaction expirée ou doublement répondue — on a déjà loggé.
        pass


bot.run(settings.discord_token)
