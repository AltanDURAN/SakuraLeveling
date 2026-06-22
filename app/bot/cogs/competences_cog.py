"""Cog `/competences` — équiper ses 2 compétences élémentaires.

Le joueur compose son build (2 slots libres) parmi les 24 compétences
(8 éléments × offensive/défensive/support) en fonction de ses affinités et de
l'élément de l'ennemi. L'élément de la compétence OFFENSIVE équipée détermine
l'élément d'attaque (avantage ±30%).
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.bot.cogs._mixins import BetaChannelOnlyMixin
from app.infrastructure.db.repositories.element_affinity_repository import (
    ElementAffinityRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.elements import element_skill_loader
from app.shared.enums import ALL_ELEMENTS, ELEMENT_EMOJIS, ELEMENT_LABELS

_ROLE_LABELS = {
    "offensive": "⚔️ Offensive",
    "defensive": "🛡️ Défense",
    "support": "💚 Support",
}


def _skill_label(code: str) -> str:
    skill = element_skill_loader.get_skill(code)
    if skill is None:
        return "—"
    el = ELEMENT_LABELS.get(skill.element, skill.element)
    role = _ROLE_LABELS.get(skill.role, skill.role)
    return f"{skill.emoji} {el} · {role} — *{skill.basic.name}*"


def build_competences_embed(
    display_name: str,
    slot_1: str | None,
    slot_2: str | None,
    affinities: dict[str, int],
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🔮 Compétences de {display_name}",
        description=(
            "Équipe **2 compétences** (slots libres). L'**offensive** détermine "
            "ton élément d'attaque (avantage **±30%** selon l'élément de l'ennemi).\n"
            "🛡️ Défense = **bouclier** (% de ta DEF) · 💚 Support = **soin** de "
            "l'allié le plus bas (% de ton ATK).\n"
            "À chaque tour : la basique ; **10%** → la spéciale à la place.\n"
            "_Adapte ton build à l'élément du boss/mob !_"
        ),
        color=discord.Color.purple(),
    )
    embed.add_field(name="Slot 1", value=_skill_label(slot_1) if slot_1 else "_vide_", inline=False)
    embed.add_field(name="Slot 2", value=_skill_label(slot_2) if slot_2 else "_vide_", inline=False)
    aff_str = "  ".join(
        f"{ELEMENT_EMOJIS.get(e.value, '')}{int(affinities.get(e.value, 0))}"
        for e in ALL_ELEMENTS
    )
    embed.add_field(name="🔮 Tes affinités élémentaires", value=aff_str, inline=False)
    return embed


def _skill_options(current_code: str | None) -> list[discord.SelectOption]:
    options: list[discord.SelectOption] = []
    skills = element_skill_loader.all_skills()
    # Ordre : par élément (ordre canonique) puis rôle.
    role_order = {"offensive": 0, "defensive": 1, "support": 2}
    ordered = sorted(
        skills.values(),
        key=lambda s: (
            [e.value for e in ALL_ELEMENTS].index(s.element)
            if s.element in [e.value for e in ALL_ELEMENTS] else 99,
            role_order.get(s.role, 9),
        ),
    )
    for skill in ordered:
        el = ELEMENT_LABELS.get(skill.element, skill.element)
        role = _ROLE_LABELS.get(skill.role, skill.role)
        options.append(
            discord.SelectOption(
                label=f"{el} · {role}"[:100],
                value=skill.code,
                description=f"{skill.basic.name} / {skill.special.name}"[:100],
                emoji=skill.emoji or None,
                default=(skill.code == current_code),
            )
        )
    return options


class _SkillSlotSelect(discord.ui.Select):
    def __init__(self, slot_index: int, owner_id: int, current_code: str | None):
        self.slot_index = slot_index
        self.owner_id = owner_id
        super().__init__(
            placeholder=f"Choisir la compétence du slot {slot_index}…",
            options=_skill_options(current_code),
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ Seul le propriétaire peut modifier ses compétences.", ephemeral=True
            )
            return
        chosen = self.values[0]
        with get_db_session() as session:
            repo = PlayerRepository(session)
            profile = repo.get_by_discord_id(interaction.user.id)
            if profile is None:
                await interaction.response.send_message("❌ Profil introuvable.", ephemeral=True)
                return
            repo.set_skill_slot(profile.player.id, self.slot_index, chosen)
            slot_1 = chosen if self.slot_index == 1 else profile.player.skill_slot_1
            slot_2 = chosen if self.slot_index == 2 else profile.player.skill_slot_2
            affinities = ElementAffinityRepository(session).get_affinities(profile.player.id)

        embed = build_competences_embed(
            interaction.user.display_name, slot_1, slot_2, affinities
        )
        view = CompetencesView(self.owner_id, slot_1, slot_2)
        await interaction.response.edit_message(embed=embed, view=view)


class CompetencesView(discord.ui.View):
    def __init__(self, owner_id: int, slot_1: str | None, slot_2: str | None):
        super().__init__(timeout=300.0)
        self.add_item(_SkillSlotSelect(1, owner_id, slot_1))
        self.add_item(_SkillSlotSelect(2, owner_id, slot_2))


class CompetencesCog(BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="competences",
        description="Voir et équiper tes 2 compétences élémentaires",
    )
    async def competences(self, interaction: discord.Interaction) -> None:
        with get_db_session() as session:
            repo = PlayerRepository(session)
            profile = repo.get_or_create_by_discord_id(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )
            slot_1 = profile.player.skill_slot_1
            slot_2 = profile.player.skill_slot_2
            affinities = ElementAffinityRepository(session).get_affinities(profile.player.id)

        embed = build_competences_embed(
            interaction.user.display_name, slot_1, slot_2, affinities
        )
        view = CompetencesView(interaction.user.id, slot_1, slot_2)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CompetencesCog(bot))
