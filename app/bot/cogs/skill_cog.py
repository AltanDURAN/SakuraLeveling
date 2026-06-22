import asyncio

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


# URL de la page web — lue depuis settings (configurable via .env via
# `WEBAPP_BASE_URL=...`). Par défaut localhost pour le dev.
from app.infrastructure.config.settings import settings as _settings
from app.bot.cogs._mixins import BetaChannelOnlyMixin
WEB_BASE_URL = _settings.webapp_base_url


class SkillCog(BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

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
        attachment = await asyncio.to_thread(render_attachment, state, definition)
        view = SkillTreeView(
            owner_discord_id=state.discord_id,
            viewer_discord_id=interaction.user.id,
            definition=definition,
            web_url=web_url,
        )
        message = await interaction.followup.send(
            embed=embed, file=attachment, view=view, wait=True,
        )
        # Persiste la référence du message principal pour permettre aux
        # callbacks (Select / boutons) d'éditer cet embed après une action.
        view.message = message


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SkillCog(bot))
