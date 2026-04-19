import discord

from app.domain.entities.class_definition import ClassDefinition
from app.domain.entities.player_profile import PlayerProfile
from app.domain.value_objects.stats import Stats


def build_player_profile_embed(
    profile: PlayerProfile,
    stats: Stats,
    active_class: ClassDefinition | None = None,
    current_hp: int = 0,
    power_score: str = "0",
) -> discord.Embed:
    embed = discord.Embed(
        title=f"👤 Profil de {profile.player.display_name}",
        color=discord.Color.blue(),
    )

    embed.add_field(name="🎯 Niveau", value=str(profile.progression.level), inline=True)
    embed.add_field(name="✨ XP", value=str(profile.progression.xp), inline=True)
    embed.add_field(name="💰 Gold", value=str(profile.resources.gold), inline=True)
    embed.add_field(name="🔥 Puissance", value=power_score, inline=True)

    embed.add_field(name="❤️ PV", value=f"{current_hp}/{stats.max_hp}", inline=True)
    embed.add_field(name="⚔️ Attaque", value=str(stats.attack), inline=True)
    embed.add_field(name="🛡️ Défense", value=str(stats.defense), inline=True)

    embed.add_field(name="🎯 Crit", value=f"{int(stats.crit_chance)}%", inline=True)
    embed.add_field(name="💥 Dégâts crit", value=f"{int(stats.crit_damage)}%", inline=True)
    embed.add_field(name="🌀 Esquive", value=f"{int(stats.dodge)}%", inline=True)

    embed.add_field(name="💨 Vitesse", value=str(stats.speed), inline=True)
    embed.add_field(name="✨ Régénération", value=f"{stats.hp_regeneration} PV/min", inline=True,)

    if active_class is None:
        embed.add_field(name="🧬 Classe", value="Aucune", inline=False)
    else:
        embed.add_field(name="🧬 Classe", value=active_class.name, inline=False)

    embed.set_footer(text=f"ID Discord : {profile.player.discord_id}")

    return embed