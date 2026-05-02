from datetime import datetime

import discord

from app.application.use_cases.get_skill_tree_state import SkillTreeState


def _format_int(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def build_skill_tree_embed(
    state: SkillTreeState,
    web_url: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🌳 Arbre de compétences — {state.player_display_name}",
        color=discord.Color.purple(),
    )

    embed.add_field(
        name="✨ Points disponibles",
        value=f"**{_format_int(state.available_points)}**",
        inline=True,
    )
    embed.add_field(
        name="🔧 Points investis",
        value=f"**{_format_int(state.spent_points)}**",
        inline=True,
    )
    embed.add_field(
        name="📍 Compétences débloquées",
        value=f"**{len(state.allocations)}**",
        inline=True,
    )

    if web_url:
        embed.add_field(
            name="🔗 Vue détaillée",
            value=f"[Ouvrir l'arbre dans le navigateur]({web_url})",
            inline=False,
        )

    if state.next_reset_available_at is not None:
        ts = int(state.next_reset_available_at.timestamp())
        embed.set_footer(text=f"Prochain reset disponible : <t:{ts}:R>")

    embed.set_image(url="attachment://skill_tree.png")
    return embed
