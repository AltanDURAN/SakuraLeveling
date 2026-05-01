import discord

from app.domain.services.leaderboard_service import Leaderboard


_RANK_EMOJI = {1: "🥇", 2: "🥈", 3: "🥉"}


def build_leaderboard_embed(leaderboard: Leaderboard) -> discord.Embed:
    embed = discord.Embed(
        title=f"🏆 Classement — {leaderboard.category_label}",
        color=discord.Color.gold(),
    )

    if not leaderboard.entries:
        embed.description = "Aucun joueur classé pour le moment."
        return embed

    lines: list[str] = []
    for rank, entry in enumerate(leaderboard.entries, start=1):
        prefix = _RANK_EMOJI.get(rank, f"`#{rank:>2}`")
        lines.append(f"{prefix} **{entry.display_name}** — `{entry.formatted_value}`")

    embed.description = "\n".join(lines)
    embed.set_footer(text=f"Top {len(leaderboard.entries)}")
    return embed
