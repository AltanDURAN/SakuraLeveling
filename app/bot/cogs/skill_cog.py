import discord
from discord import app_commands
from discord.ext import commands

from app.application.use_cases.get_skill_tree_state import GetSkillTreeStateUseCase
from app.bot.embeds.skill_embeds import build_skill_tree_embed
from app.bot.views.skill_tree_view import SkillTreeView, render_attachment
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.db.session import get_db_session
from app.infrastructure.skill_tree.skill_tree_loader import (
    get_definition as get_skill_tree_definition,
)


# URL de la page web (locale par défaut). À déplacer dans settings.py + .env
# quand le déploiement public sera fait.
WEB_BASE_URL = "http://localhost:8000"


class SkillCog(commands.Cog):
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
        name="skill",
        description="Afficher votre arbre de compétences",
    )
    @app_commands.describe(
        target="Joueur dont afficher l'arbre (par défaut : vous)",
    )
    async def skill(
        self,
        interaction: discord.Interaction,
        target: discord.Member | None = None,
    ) -> None:
        await interaction.response.defer()

        target_member = target or interaction.user
        is_self = target is None
        definition = get_skill_tree_definition()

        with get_db_session() as session:
            use_case = GetSkillTreeStateUseCase(
                player_repository=PlayerRepository(session),
                skill_allocation_repository=PlayerSkillAllocationRepository(session),
                cooldown_repository=CooldownRepository(session),
                skill_tree_definition=definition,
            )
            if is_self:
                state = use_case.execute_for_self(
                    discord_id=interaction.user.id,
                    username=interaction.user.name,
                    display_name=interaction.user.display_name,
                )
            else:
                state = use_case.execute(target_member.id)

        if state is None:
            await interaction.followup.send(
                f"❌ {target_member.display_name} n'a pas encore de profil.",
                ephemeral=True,
            )
            return

        web_url = f"{WEB_BASE_URL}/skill/{state.discord_id}"
        embed = build_skill_tree_embed(state, web_url=web_url)
        attachment = render_attachment(state, definition)
        view = SkillTreeView(
            owner_discord_id=state.discord_id,
            viewer_discord_id=interaction.user.id,
            definition=definition,
            web_url=web_url,
        )
        await interaction.followup.send(
            embed=embed, file=attachment, view=view
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SkillCog(bot))
