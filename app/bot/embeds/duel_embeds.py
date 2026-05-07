"""Embeds pour la commande /fight @target (duel 1v1).

Trois fonctions :
    - `build_duel_intro_embed` : avant le 1er coup, affiche les deux full HP
    - `build_duel_turn_embed` : pendant l'animation, à chaque tour
    - `build_duel_result_embed` : à la fin, avec le récap ladder

Convention HP : on calcule des barres en pourcentage de max_hp pour rester
lisible quels que soient les plafonds (les deux joueurs n'ont pas forcément
les mêmes max_hp).
"""

import discord
from discord.utils import escape_markdown

from app.domain.value_objects.duel_result import DuelResult, DuelTurnLog


def _hp_bar(current: int, maximum: int) -> str:
    if maximum <= 0:
        return "⬛⬛⬛⬛⬛"
    ratio = max(0.0, current / maximum)
    if current <= 0:
        return "⬛⬛⬛⬛⬛"
    if ratio >= 0.95:
        return "🟩🟩🟩🟩🟩"
    if ratio >= 0.75:
        return "🟩🟩🟩🟩⬛"
    if ratio >= 0.50:
        return "🟨🟨🟨⬛⬛"
    if ratio >= 0.25:
        return "🟧🟧⬛⬛⬛"
    return "🟥⬛⬛⬛⬛"


def build_duel_intro_embed(
    challenger_name: str,
    target_name: str,
    challenger_max_hp: int,
    target_max_hp: int,
) -> discord.Embed:
    challenger_name = escape_markdown(challenger_name)
    target_name = escape_markdown(target_name)
    embed = discord.Embed(
        title=f"⚔️ Duel — {challenger_name} vs {target_name}",
        description="Le duel commence... Aucun PV réel ne sera perdu.",
        color=discord.Color.orange(),
    )
    embed.add_field(
        name=f"🧍 {challenger_name}",
        value=f"{_hp_bar(challenger_max_hp, challenger_max_hp)} **{challenger_max_hp}/{challenger_max_hp} PV**",
        inline=False,
    )
    embed.add_field(
        name=f"🧍 {target_name}",
        value=f"{_hp_bar(target_max_hp, target_max_hp)} **{target_max_hp}/{target_max_hp} PV**",
        inline=False,
    )
    embed.set_footer(text="Préparation au combat...")
    return embed


def build_duel_turn_embed(
    challenger_name: str,
    target_name: str,
    result: DuelResult,
    turn_log: DuelTurnLog,
) -> discord.Embed:
    challenger_name = escape_markdown(challenger_name)
    target_name = escape_markdown(target_name)
    actor_name = challenger_name if turn_log.actor == "a" else target_name
    target_of_hit = target_name if turn_log.actor == "a" else challenger_name

    if turn_log.target_dodged:
        action_line = f"🌀 **{target_of_hit}** esquive l'attaque !"
    else:
        crit_marker = " 💥 **CRITIQUE**" if turn_log.is_crit else ""
        action_line = (
            f"⚔️ **{actor_name}** inflige **{turn_log.damage}** dégâts à "
            f"**{target_of_hit}**{crit_marker}"
        )

    embed = discord.Embed(
        title=f"⚔️ Duel — Tour {turn_log.turn_number}",
        description=action_line,
        color=discord.Color.orange(),
    )
    embed.add_field(
        name=f"🧍 {challenger_name}",
        value=(
            f"{_hp_bar(turn_log.a_hp_after, result.a_max_hp)} "
            f"**{turn_log.a_hp_after}/{result.a_max_hp} PV**"
        ),
        inline=False,
    )
    embed.add_field(
        name=f"🧍 {target_name}",
        value=(
            f"{_hp_bar(turn_log.b_hp_after, result.b_max_hp)} "
            f"**{turn_log.b_hp_after}/{result.b_max_hp} PV**"
        ),
        inline=False,
    )
    embed.set_footer(text="Le duel continue...")
    return embed


def build_duel_result_embed(
    challenger_name: str,
    target_name: str,
    result: DuelResult,
    challenger_won: bool,
    swapped: bool,
    challenger_old_position: int,
    target_old_position: int,
    challenger_new_position: int,
    target_new_position: int,
) -> discord.Embed:
    challenger_name = escape_markdown(challenger_name)
    target_name = escape_markdown(target_name)
    color = discord.Color.green() if challenger_won else discord.Color.red()
    title_emoji = "🏆" if challenger_won else "💀"
    winner_name = challenger_name if challenger_won else target_name

    embed = discord.Embed(
        title=f"{title_emoji} Fin du duel — {winner_name} l'emporte",
        description=(
            f"**{challenger_name}** vs **{target_name}** — "
            f"{result.turns} tour(s).\n"
            "_Aucun PV réel n'a été perdu._"
        ),
        color=color,
    )

    embed.add_field(
        name=f"🧍 {challenger_name}",
        value=(
            f"{_hp_bar(result.a_remaining_hp, result.a_max_hp)} "
            f"**{result.a_remaining_hp}/{result.a_max_hp} PV**"
        ),
        inline=True,
    )
    embed.add_field(
        name=f"🧍 {target_name}",
        value=(
            f"{_hp_bar(result.b_remaining_hp, result.b_max_hp)} "
            f"**{result.b_remaining_hp}/{result.b_max_hp} PV**"
        ),
        inline=True,
    )

    if swapped:
        embed.add_field(
            name="🔁 Échange de places dans le ladder",
            value=(
                f"**{challenger_name}** : #{challenger_old_position} → "
                f"**#{challenger_new_position}**\n"
                f"**{target_name}** : #{target_old_position} → "
                f"**#{target_new_position}**"
            ),
            inline=False,
        )
    else:
        embed.add_field(
            name="🛡️ Ladder inchangé",
            value=(
                f"**{challenger_name}** : #{challenger_old_position}\n"
                f"**{target_name}** : #{target_old_position}"
            ),
            inline=False,
        )

    embed.set_footer(text="Voir /top duel_rank pour le classement complet")
    return embed
