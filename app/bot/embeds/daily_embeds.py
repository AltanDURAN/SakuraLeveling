from datetime import datetime

import discord


def _format_int(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def build_daily_success_embed(streak: int, gold_gained: int) -> discord.Embed:
    embed = discord.Embed(
        title=f"Daily Streak {streak} 🔥 !",
        description=(
            "Vous récupérez :\n"
            f"**{_format_int(gold_gained)}** 🪙\n"
            "Revenez également demain !"
        ),
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
