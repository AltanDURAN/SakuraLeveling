import discord

from app.domain.entities.class_definition import ClassDefinition
from app.domain.entities.player_career_stats import PlayerCareerStats
from app.domain.entities.player_profile import PlayerProfile
from app.domain.value_objects.stats import Stats


def _format_int(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def build_player_profile_embed(
    profile: PlayerProfile,
    stats: Stats,
    active_class: ClassDefinition | None = None,
    current_hp: int = 0,
    power_score: str = "0",
    total_kills: int = 0,
    career_stats: PlayerCareerStats | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"👤 Profil de {profile.player.display_name}",
        color=discord.Color.blue(),
    )

    # Bloc identité / progression
    embed.add_field(name="🎯 Niveau", value=str(profile.progression.level), inline=True)
    embed.add_field(name="✨ XP", value=_format_int(profile.progression.xp), inline=True)
    embed.add_field(name="💰 Or", value=_format_int(profile.resources.gold), inline=True)
    embed.add_field(name="🔥 Puissance", value=power_score, inline=True)

    # Bloc combat / stats
    embed.add_field(name="❤️ PV", value=f"{current_hp}/{stats.max_hp}", inline=True)
    embed.add_field(name="⚔️ Attaque", value=str(stats.attack), inline=True)
    embed.add_field(name="🛡️ Défense", value=str(stats.defense), inline=True)

    embed.add_field(name="🎯 Crit", value=f"{int(stats.crit_chance)}%", inline=True)
    embed.add_field(name="💥 Dégâts crit", value=f"{int(stats.crit_damage)}%", inline=True)
    embed.add_field(name="🌀 Esquive", value=f"{int(stats.dodge)}%", inline=True)

    embed.add_field(name="💨 Vitesse", value=str(stats.speed), inline=True)
    embed.add_field(
        name="✨ Régénération",
        value=f"{stats.hp_regeneration} PV/min",
        inline=True,
    )
    embed.add_field(
        name="🔥 Daily Streak",
        value=f"{profile.resources.daily_streak}",
        inline=True,
    )

    # Bloc classe
    if active_class is None:
        embed.add_field(name="🧬 Classe", value="Aucune", inline=False)
    else:
        embed.add_field(name="🧬 Classe", value=active_class.name, inline=False)

    # Bloc carrière (cumulés sur la durée de vie du profil)
    if career_stats is not None:
        win_rate = ""
        if career_stats.combats_fought > 0:
            ratio = round(100 * career_stats.combats_won / career_stats.combats_fought)
            win_rate = f" ({ratio}% W)"

        career_lines = [
            f"💀 Monstres tués : **{_format_int(total_kills)}**",
            (
                f"⚔️ Combats : **{_format_int(career_stats.combats_fought)}**"
                f" — {career_stats.combats_won}V / {career_stats.combats_lost}D{win_rate}"
            ),
            f"💰 Or amassé : **{_format_int(career_stats.gold_earned_total)}** au total",
            f"💢 Dégâts infligés : **{_format_int(career_stats.damage_dealt_total)}**",
            f"🛡️ Dégâts encaissés : **{_format_int(career_stats.damage_tanked_total)}**",
            f"💚 PV régénérés : **{_format_int(career_stats.hp_healed_total)}**",
        ]
        embed.add_field(
            name="📈 Statistiques de carrière",
            value="\n".join(career_lines),
            inline=False,
        )

    embed.set_footer(text=f"ID Discord : {profile.player.discord_id}")

    return embed
