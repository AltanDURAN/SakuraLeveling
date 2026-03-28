import discord

from app.domain.value_objects.battle_result import BattleResult


def build_battle_result_embed(result: BattleResult) -> discord.Embed:
    color = discord.Color.green() if result.victory else discord.Color.red()

    embed = discord.Embed(
        title="⚔️ Résultat du combat",
        description=result.summary,
        color=color,
    )

    embed.add_field(name="Tours", value=str(result.turns), inline=True)
    embed.add_field(name="PV restants joueur", value=str(result.player_remaining_hp), inline=True)
    embed.add_field(name="PV restants monstre", value=str(result.mob_remaining_hp), inline=True)

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