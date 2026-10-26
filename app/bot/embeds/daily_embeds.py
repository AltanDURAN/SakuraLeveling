from datetime import datetime

import discord

from app.shared.formatters import format_int as _format_int


def build_daily_success_embed(
    streak: int,
    gold_gained: int,
    bonus_items: list[tuple[str, int]] | None = None,
    streak_bonus_pct: int = 0,
    days_missed: int = 0,
    streak_before_absence: int = 0,
    titles_unlocked: list[str] | None = None,
    guard_used: bool = False,
) -> discord.Embed:
    lines = [
        "Vous récupérez :",
        f"**{_format_int(gold_gained)}** 🪙"
        + (f" (dont **+{streak_bonus_pct} %** de série)" if streak_bonus_pct else ""),
    ]
    if guard_used:
        lines.append("")
        lines.append("⏳ Ton **sablier de fidélité** s'est brisé : un jour manqué t'est pardonné.")
    if days_missed:
        lines.append("")
        lines.append(
            f"💔 {days_missed} jour{'s' if days_missed > 1 else ''} manqué"
            f"{'s' if days_missed > 1 else ''} : ta série de **{streak_before_absence}** "
            f"a été divisée par deux par jour d'absence."
        )
    if titles_unlocked:
        lines.append("")
        for title in titles_unlocked:
            lines.append(f"🏷️ Nouveau titre débloqué : **{title}** (voir `/titre`)")
    if streak_bonus_pct < 90:
        lines.append("")
        lines.append(
            "_La série ajoute +3 % par jour (jusqu'à +90 % à 30 jours). "
            "Un jour manqué la divise par deux._"
        )
    if bonus_items:
        lines.append("")
        lines.append("🏷️ **Bonus de titres :**")
        for name, qty in bonus_items:
            lines.append(f"• **{name}** ×{qty}")
    lines.append("")
    lines.append("Revenez également demain !")

    embed = discord.Embed(
        title=f"Série de {streak} jour{'s' if streak > 1 else ''} 🔥 !",
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
