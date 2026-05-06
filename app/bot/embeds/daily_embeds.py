from datetime import datetime

import discord

from app.shared.formatters import format_int as _format_int


def build_daily_success_embed(
    streak: int,
    gold_gained: int,
    bonus_items: list[tuple[str, int]] | None = None,
) -> discord.Embed:
    lines = [
        "Vous récupérez :",
        f"**{_format_int(gold_gained)}** 🪙",
    ]
    if bonus_items:
        lines.append("")
        lines.append("🏷️ **Bonus de titres :**")
        for name, qty in bonus_items:
            lines.append(f"• **{name}** ×{qty}")
    lines.append("")
    lines.append("Revenez également demain !")

    embed = discord.Embed(
        title=f"Daily Streak {streak} 🔥 !",
        description="\n".join(lines),
        color=discord.Color.gold(),
    )
    return embed


def build_daily_cooldown_embed(
    streak: int,
    next_available_at: datetime,
) -> discord.Embed:
    timestamp = int(next_available_at.timestamp())
    embed = discord.Embed(
        title="⏳ Daily déjà récupéré",
        description=(
            f"Vous avez déjà récupéré votre récompense quotidienne.\n"
            f"Prochain daily disponible <t:{timestamp}:R> (<t:{timestamp}:F>).\n\n"
            f"Série actuelle : **{streak}** 🔥"
        ),
        color=discord.Color.orange(),
    )
    return embed
