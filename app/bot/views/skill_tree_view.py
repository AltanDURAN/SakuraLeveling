from __future__ import annotations

import io

import discord

from app.application.use_cases.get_skill_tree_state import (
    GetSkillTreeStateUseCase,
    SkillTreeState,
)
from app.application.use_cases.invest_skill_point import InvestSkillPointUseCase
from app.application.use_cases.reset_skill_tree import ResetSkillTreeUseCase
from app.bot.embeds.skill_embeds import build_skill_tree_embed
from app.bot.rendering.skill_tree_renderer import render_to_png
from app.domain.entities.skill_tree_definition import SkillTreeDefinition
from app.domain.services.cooldown_service import CooldownService
from app.domain.services.skill_tree_service import SkillTreeService
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.db.session import get_db_session


def render_attachment(
    state: SkillTreeState, definition: SkillTreeDefinition
) -> discord.File:
    png_bytes = render_to_png(state, definition)
    return discord.File(io.BytesIO(png_bytes), filename="skill_tree.png")


class SkillTreeView(discord.ui.View):
    """Vue principale de /skill : embed + 3 boutons.

    `owner_discord_id` est le seul autorisé à modifier l'arbre. Les autres
    utilisateurs (qui ont fait /skill @autre) ont les boutons désactivés.
    """

    def __init__(
        self,
        owner_discord_id: int,
        viewer_discord_id: int,
        definition: SkillTreeDefinition,
        web_url: str | None = None,
        timeout: float = 600.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.owner_discord_id = owner_discord_id
        self.viewer_discord_id = viewer_discord_id
        self.definition = definition
        self.web_url = web_url
        # Référence du message principal (posée par le cog après send).
        # Permet de re-render l'embed/image après une action.
        self.message: discord.Message | None = None

        if viewer_discord_id != owner_discord_id:
            for child in self.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True

    async def _refresh_embed(self, interaction: discord.Interaction) -> None:
        with get_db_session() as session:
            state = GetSkillTreeStateUseCase(
                player_repository=PlayerRepository(session),
                skill_allocation_repository=PlayerSkillAllocationRepository(session),
                cooldown_repository=CooldownRepository(session),
                skill_tree_definition=self.definition,
            ).execute(self.owner_discord_id)

        if state is None:
            await interaction.followup.send(
                "❌ Profil introuvable.", ephemeral=True
            )
            return

        embed = build_skill_tree_embed(state, web_url=self.web_url)
        attachment = render_attachment(state, self.definition)
        # Édite le message principal (pas celui du picker éphémère qui peut
        # contenir l'interaction courante). Si la référence n'a pas été
        # posée par le cog (cas de fallback), on retombe sur interaction.message.
        target_message = self.message or interaction.message
        if target_message is None:
            return
        await target_message.edit(
            embed=embed, attachments=[attachment], view=self,
        )

    async def _check_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_discord_id:
            await interaction.response.send_message(
                "❌ Vous ne pouvez modifier que votre propre arbre.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Investir un point",
        style=discord.ButtonStyle.primary,
        emoji="✨",
    )
    async def invest_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not await self._check_owner(interaction):
            return

        with get_db_session() as session:
            state = GetSkillTreeStateUseCase(
                player_repository=PlayerRepository(session),
                skill_allocation_repository=PlayerSkillAllocationRepository(session),
                cooldown_repository=CooldownRepository(session),
                skill_tree_definition=self.definition,
            ).execute(self.owner_discord_id)

        if state is None:
            await interaction.response.send_message(
                "❌ Profil introuvable.", ephemeral=True
            )
            return

        # Limite à 25 = max d'options Discord (plus haute → tronqué silencieusement).
        # Garde cohérent avec ce que le PNG/SVG montre comme débloquable.
        candidates = SkillTreeService(self.definition).compute_unlockable_skills(
            state.allocations, limit=25
        )
        if not candidates:
            await interaction.response.send_message(
                "Aucune compétence à débloquer pour le moment.",
                ephemeral=True,
            )
            return

        select = SkillInvestSelect(
            owner_discord_id=self.owner_discord_id,
            definition=self.definition,
            parent_view=self,
            available_points=state.available_points,
            allocations=state.allocations,
            candidates=candidates,
        )
        select_view = discord.ui.View(timeout=120)
        select_view.add_item(select)

        await interaction.response.send_message(
            f"Choisissez une compétence à investir "
            f"(vous avez **{state.available_points}** point(s) dispo) :",
            view=select_view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Vue détaillée",
        style=discord.ButtonStyle.secondary,
        emoji="🔗",
    )
    async def detail_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if self.web_url is None:
            await interaction.response.send_message(
                "ℹ️ La vue web n'est pas configurée.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"🔗 **Vue détaillée :** {self.web_url}",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Réinitialiser",
        style=discord.ButtonStyle.danger,
        emoji="♻️",
    )
    async def reset_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not await self._check_owner(interaction):
            return

        confirm_view = SkillResetConfirmView(
            owner_discord_id=self.owner_discord_id,
            parent_view=self,
            definition=self.definition,
        )
        await interaction.response.send_message(
            "⚠️ Voulez-vous **vraiment** réinitialiser votre arbre ?\n"
            "Tous les points seront restitués, mais un cooldown de **7 jours** s'appliquera.",
            view=confirm_view,
            ephemeral=True,
        )


class SkillInvestSelect(discord.ui.Select):
    def __init__(
        self,
        owner_discord_id: int,
        definition: SkillTreeDefinition,
        parent_view: SkillTreeView,
        available_points: int,
        allocations: dict[str, int],
        candidates: list,
    ) -> None:
        self.owner_discord_id = owner_discord_id
        self.definition = definition
        self.parent_view = parent_view

        options: list[discord.SelectOption] = []
        for node in candidates:
            current = allocations.get(node.code, 0)
            target = current + 1
            cost = node.cost_for_level(target)
            label = f"{node.name} ({current}/{node.max_level})"[:100]
            description = f"Coût : {cost} pt(s) — {node.description}"[:100]
            options.append(
                discord.SelectOption(
                    label=label,
                    description=description,
                    value=node.code,
                    emoji=node.icon[:2] if node.icon else None,
                )
            )

        super().__init__(
            placeholder="Choisissez une compétence à investir...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        skill_code = self.values[0]

        with get_db_session() as session:
            use_case = InvestSkillPointUseCase(
                player_repository=PlayerRepository(session),
                skill_allocation_repository=PlayerSkillAllocationRepository(session),
                skill_tree_definition=self.definition,
            )
            result = use_case.execute(
                discord_id=self.owner_discord_id, skill_code=skill_code
            )

        if not result.success:
            await interaction.response.edit_message(
                content=f"❌ {result.message}", view=None
            )
            return

        await interaction.response.edit_message(content=result.message, view=None)
        await self.parent_view._refresh_embed(interaction)


class SkillResetConfirmView(discord.ui.View):
    def __init__(
        self,
        owner_discord_id: int,
        parent_view: SkillTreeView,
        definition: SkillTreeDefinition,
        timeout: float = 60.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.owner_discord_id = owner_discord_id
        self.parent_view = parent_view
        self.definition = definition

    @discord.ui.button(label="Oui, réinitialiser", style=discord.ButtonStyle.danger)
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        with get_db_session() as session:
            use_case = ResetSkillTreeUseCase(
                player_repository=PlayerRepository(session),
                skill_allocation_repository=PlayerSkillAllocationRepository(session),
                cooldown_repository=CooldownRepository(session),
                cooldown_service=CooldownService(),
                skill_tree_definition=self.definition,
            )
            result = use_case.execute(self.owner_discord_id)

        await interaction.response.edit_message(content=result.message, view=None)
        if result.success:
            await self.parent_view._refresh_embed(interaction)

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            content="✋ Réinitialisation annulée.", view=None
        )
