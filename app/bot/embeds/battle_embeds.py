import discord

from app.domain.value_objects.battle_result import BattleResult
from app.domain.value_objects.battle_turn_log import BattleTurnLog


def build_battle_turn_embed(
    result: BattleResult,
    turn_log: BattleTurnLog,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"⚔️ Combat contre {result.mob_name}",
        color=discord.Color.orange(),
    )

    if result.mob_image_url:
        embed.set_thumbnail(url=result.mob_image_url)

    crit_text = "Oui" if turn_log.player_crit else "Non"
    dodge_text = "Oui" if turn_log.player_dodged else "Non"

    embed.add_field(name="Tour", value=str(turn_log.turn_number), inline=False)

    embed.add_field(
        name="Action du joueur",
        value=(
            f"Dégâts infligés : {turn_log.player_damage_dealt}\n"
            f"Coup critique : {crit_text}"
        ),
        inline=True,
    )

    embed.add_field(
        name="Action du monstre",
        value=(
            f"Dégâts infligés : {turn_log.mob_damage_dealt}\n"
            f"Esquive du joueur : {dodge_text}"
        ),
        inline=True,
    )

    embed.add_field(
        name="PV après le tour",
        value=(
            f"Joueur : {turn_log.player_hp_after}\n"
            f"{result.mob_name} : {turn_log.mob_hp_after}"
        ),
        inline=False,
    )

    embed.set_footer(text="Le combat continue...")
    return embed


def build_battle_result_embed(result: BattleResult) -> discord.Embed:
    color = discord.Color.green() if result.victory else discord.Color.red()

    embed = discord.Embed(
        title=f"🏁 Fin du combat contre {result.mob_name}",
        description=result.summary,
        color=color,
    )

    if result.mob_image_url:
        embed.set_thumbnail(url=result.mob_image_url)

    embed.add_field(name="Tours", value=str(result.turns), inline=True)
    embed.add_field(name="PV restants joueur", value=str(result.player_remaining_hp), inline=True)
    embed.add_field(name=f"PV restants {result.mob_name}", value=str(result.mob_remaining_hp), inline=True)

    if result.victory:
        embed.add_field(name="XP gagnée", value=str(result.xp_gained), inline=True)
        embed.add_field(name="Gold gagné", value=str(result.gold_gained), inline=True)

        if result.items_gained:
            loot_lines = [
                f"{item_code} x{quantity}"
                for item_code, quantity in result.items_gained
            ]
            embed.add_field(name="Loot", value="\n".join(loot_lines), inline=False)

        if result.leveled_up and result.new_level is not None:
            embed.add_field(name="🎉 Level up", value=f"Niveau {result.new_level}", inline=False)

    return embed