from pathlib import Path
import discord

from app.domain.value_objects.battle_result import BattleResult
from app.domain.value_objects.battle_turn_log import BattleTurnLog

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
print(BASE_DIR)

def build_battle_turn_embed(
    result: BattleResult,
    turn_log: BattleTurnLog,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"⚔️ Combat — {result.mob_name}",
        description="Le combat est en cours...",
        color=discord.Color.orange(),
    )

    if result.mob_image_name:
        mob_image_path = BASE_DIR / "assets" / "mobs" / result.mob_image_name
        embed.set_image(url=f"attachment://{mob_image_path}")

    crit_text = "💥 Oui" if turn_log.player_crit else "➖ Non"
    dodge_text = "🌀 Oui" if turn_log.player_dodged else "➖ Non"

    embed.add_field(
        name="🕒 Tour",
        value=f"**{turn_log.turn_number}**",
        inline=False,
    )

    embed.add_field(
        name="🧍 Joueur",
        value=(
            f"⚔️ Dégâts infligés : **{turn_log.player_damage_dealt}**\n"
            f"💥 Critique : **{crit_text}**\n"
            f"❤️ PV restants : **{turn_log.player_hp_after}**"
        ),
        inline=True,
    )

    embed.add_field(
        name=f"👾 {result.mob_name}",
        value=(
            f"⚔️ Dégâts infligés : **{turn_log.mob_damage_dealt}**\n"
            f"🌀 Esquive du joueur : **{dodge_text}**\n"
            f"❤️ PV restants : **{turn_log.mob_hp_after}**"
        ),
        inline=True,
    )

    hp_bar_player = _build_hp_bar(turn_log.player_hp_after)
    hp_bar_mob = _build_hp_bar(turn_log.mob_hp_after)

    embed.add_field(
        name="📊 État du combat",
        value=(
            f"🧍 Joueur : {hp_bar_player} **{turn_log.player_hp_after} PV**\n"
            f"👾 {result.mob_name} : {hp_bar_mob} **{turn_log.mob_hp_after} PV**"
        ),
        inline=False,
    )

    embed.set_footer(text="Le combat continue...")
    return embed


def build_battle_result_embed(result: BattleResult) -> discord.Embed:
    color = discord.Color.green() if result.victory else discord.Color.red()
    title_emoji = "🏆" if result.victory else "💀"

    embed = discord.Embed(
        title=f"{title_emoji} Fin du combat — {result.mob_name}",
        description=result.summary,
        color=color,
    )

    if result.mob_image_name:
        mob_image_path = BASE_DIR / "assets" / "mobs" / result.mob_image_name
        embed.set_image(url=f"attachment://{mob_image_path}")

    embed.add_field(name="🕒 Tours", value=f"**{result.turns}**", inline=True)
    embed.add_field(
        name="❤️ PV joueur",
        value=f"**{result.player_remaining_hp}**",
        inline=True,
    )
    embed.add_field(
        name=f"👾 PV {result.mob_name}",
        value=f"**{result.mob_remaining_hp}**",
        inline=True,
    )

    if result.victory:
        embed.add_field(name="✨ XP gagnée", value=f"**{result.xp_gained}**", inline=True)
        embed.add_field(name="💰 Gold gagné", value=f"**{result.gold_gained}**", inline=True)

        if result.leveled_up and result.new_level is not None:
            embed.add_field(
                name="🎉 Level up",
                value=f"Vous passez niveau **{result.new_level}**",
                inline=True,
            )

        if result.items_gained:
            loot_lines = [
                f"🎁 `{item_code}` x**{quantity}**"
                for item_code, quantity in result.items_gained
            ]
            embed.add_field(
                name="📦 Loot",
                value="\n".join(loot_lines),
                inline=False,
            )

    if result.turn_logs:
        last_turn = result.turn_logs[-1]
        embed.add_field(
            name="📜 Dernier tour",
            value=(
                f"⚔️ Joueur : **{last_turn.player_damage_dealt}** dégâts\n"
                f"👾 Monstre : **{last_turn.mob_damage_dealt}** dégâts\n"
                f"💥 Critique : **{'Oui' if last_turn.player_crit else 'Non'}**\n"
                f"🌀 Esquive : **{'Oui' if last_turn.player_dodged else 'Non'}**"
            ),
            inline=False,
        )

    embed.set_footer(text="Combat terminé")
    return embed


def _build_hp_bar(current_hp: int) -> str:
    if current_hp <= 0:
        return "⬛⬛⬛⬛⬛"

    if current_hp >= 100:
        return "🟩🟩🟩🟩🟩"
    if current_hp >= 75:
        return "🟩🟩🟩🟩⬛"
    if current_hp >= 50:
        return "🟨🟨🟨⬛⬛"
    if current_hp >= 25:
        return "🟧🟧⬛⬛⬛"
    return "🟥⬛⬛⬛⬛"