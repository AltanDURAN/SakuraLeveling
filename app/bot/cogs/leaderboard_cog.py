import discord
from discord import app_commands
from discord.ext import commands

from app.application.use_cases.get_leaderboard import GetLeaderboardUseCase
from app.bot.embeds.leaderboard_embeds import build_leaderboard_embed
from app.domain.services.leaderboard_service import LeaderboardService
from app.domain.services.power_score_service import PowerScoreService
from app.domain.services.stats_service import StatsService
from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.repositories.player_duel_rank_repository import (
    PlayerDuelRankRepository,
)
from app.infrastructure.db.repositories.player_kill_repository import PlayerKillRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session


STATIC_CATEGORIES: list[tuple[str, str]] = [
    ("power", "Puissance"),
    ("level", "Niveau"),
    ("gold", "Or"),
    ("max_hp", "Points de vie"),
    ("attack", "Attaque"),
    ("defense", "Défense"),
    ("speed", "Vitesse"),
    ("crit_chance", "Chance de critique"),
    ("crit_damage", "Dégâts de critique"),
    ("dodge", "Esquive"),
    ("hp_regeneration", "Régénération"),
    ("kills_total", "Monstres tués (total)"),
    ("duel_rank", "Classement duels 1v1"),
]


class LeaderboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="classement", description="Affiche un classement")
    @app_commands.describe(category="Type de classement à afficher")
    async def top(self, interaction: discord.Interaction, category: str) -> None:
        await interaction.response.defer()

        with get_db_session() as session:
            use_case = GetLeaderboardUseCase(
                player_repository=PlayerRepository(session),
                equipment_repository=EquipmentRepository(session),
                class_repository=ClassRepository(session),
                kill_repository=PlayerKillRepository(session),
                mob_repository=MobRepository(session),
                stats_service=StatsService(),
                power_score_service=PowerScoreService(),
                leaderboard_service=LeaderboardService(),
                duel_rank_repository=PlayerDuelRankRepository(session),
            )

            leaderboard = use_case.execute(category_code=category, limit=10)

        if leaderboard is None:
            await interaction.followup.send(
                "Catégorie de classement inconnue.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(embed=build_leaderboard_embed(leaderboard))

    @top.autocomplete("category")
    async def category_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        current_lower = current.lower()
        choices: list[app_commands.Choice[str]] = []

        for code, label in STATIC_CATEGORIES:
            if current_lower in label.lower() or current_lower in code.lower():
                choices.append(app_commands.Choice(name=label, value=code))

        with get_db_session() as session:
            mob_repository = MobRepository(session)
            mobs = mob_repository.list_all()
            families = mob_repository.list_distinct_families()

        for family in families:
            label = f"Tués : famille {family.capitalize()}"
            code = f"kills_family:{family}"
            if current_lower in label.lower() or current_lower in code.lower():
                choices.append(app_commands.Choice(name=label, value=code))

        for mob in mobs:
            label = f"Tués : {mob.name}"
            code = f"kills_mob:{mob.code}"
            if current_lower in label.lower() or current_lower in code.lower():
                choices.append(app_commands.Choice(name=label, value=code))

        return choices[:25]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LeaderboardCog(bot))
