import discord

from app.shared.formatters import format_int as _format_int
from app.shared.enums import ALL_ELEMENTS, ELEMENT_EMOJIS, ELEMENT_LABELS
from app.domain.entities.player_career_stats import PlayerCareerStats
from app.domain.entities.player_profile import PlayerProfile
from app.domain.services.element_affinity_progression_service import (
    ElementAffinityProgressionService,
)
from app.domain.value_objects.stats import Stats


def _affinity_bar(value: int, width: int = 10, cap: int = 100) -> str:
    cap = max(1, cap)
    filled = round(max(0, min(cap, value)) / cap * width)
    return "█" * filled + "░" * (width - filled)


def build_affinities_embed(
    display_name: str,
    affinities: dict[str, int],
    essences: dict[str, int],
    is_self: bool = True,
    talents: dict | None = None,
    revealed: set[str] | None = None,
    next_paper_price: int | None = 0,
) -> discord.Embed:
    """Affinités élémentaires + progression d'essences vers le palier suivant
    (coût N→N+1 = N+1 essences), pour chaque élément.

    Le TALENT (caché) n'est affiché que pour les éléments découverts avec un
    la voyante ; les autres portent un ❓ qui dit comment le découvrir.
    Tant qu'un talent est inconnu, rien ne trahit son plafond réel."""
    from app.bot.views.seer_view import reading_price_label

    progression = ElementAffinityProgressionService()
    talents = talents or {}
    revealed = revealed or set()
    who = "Vos" if is_self else f"Affinités de {display_name} —"
    unknown = sum(1 for e in ALL_ELEMENTS if e.value not in revealed)
    description = (
        "Tuez des monstres d'un élément pour gagner des **essences** ; "
        "elles montent automatiquement l'affinité de cet élément "
        "(coût du palier N→N+1 = N+1 essences)."
    )
    if unknown:
        hint = (
            f"\n\n🔮 **{unknown} talent(s) encore inconnu(s).** Chacun de vous "
            "naît avec un talent caché par élément : il décide à quelle vitesse "
            "les essences tombent… et certains éléments réservent des surprises."
        )
        if is_self:
            hint += (
                "\n🔮 Ysaline, la **voyante** (`/voyante` ou le bouton ci-dessous), "
                "peut le lire pour toi — prochaine lecture : "
                f"**{reading_price_label(next_paper_price)}**."
            )
        description += hint
    embed = discord.Embed(
        title=f"✨ {who} affinités élémentaires",
        description=description,
        color=discord.Color.purple(),
    )
    for element in ALL_ELEMENTS:
        code = element.value
        aff = int(affinities.get(code, 0))
        ess = int(essences.get(code, 0))
        emoji = ELEMENT_EMOJIS.get(code, "")
        label = ELEMENT_LABELS.get(code, code)
        talent = talents.get(code)
        cap = talent.cap if talent is not None else 100
        known = code in revealed and talent is not None

        if known and talent.dead:
            embed.add_field(
                name=f"{emoji} {label} — 💀 élément mort",
                value="Aucune essence cette saison, inutilisable en combat.",
                inline=False,
            )
            continue

        next_cost = progression.cost_for_next_level(aff, cap=cap)
        if next_cost is None:
            progress = "**MAX** 🏆"
        else:
            progress = f"{ess}/{next_cost} essences → palier suivant"
        if known:
            name = f"{emoji} {label} — {aff}/{cap}"
            line = f"Talent **{talent.talent}** (+{talent.essence_bonus_pct} % d'essences)"
            if talent.boosts:
                line = "✨ " + line + " · don rare"
            bar = _affinity_bar(aff, cap=cap)
        else:
            name = f"{emoji} {label} — {aff}"
            line = "Talent ❓"
            bar = _affinity_bar(aff)
        embed.add_field(
            name=name,
            value=f"`{bar}` {progress}\n{line}",
            inline=False,
        )
    return embed


def build_player_profile_image_embed(
    display_name: str,
    attachment_filename: str,
) -> discord.Embed:
    """Embed minimaliste qui sert UNIQUEMENT à embarquer la bannière PNG.

    Le titre est placé sur l'image elle-même donc on ne le double pas ici :
    on utilise juste un set_image vers le fichier joint. Discord exige
    cependant un objet `Embed` pour que `set_image(attachment://...)`
    s'affiche, donc on en envoie un sans fields ni description.
    """
    embed = discord.Embed(color=discord.Color.dark_blue())
    embed.set_image(url=f"attachment://{attachment_filename}")
    return embed


def build_player_profile_embed(
    profile: PlayerProfile,
    stats: Stats,
    current_hp: int = 0,
    power_score: str = "0",
    rank_label: str = "F-",
    total_kills: int = 0,
    career_stats: PlayerCareerStats | None = None,
    active_title: str | None = None,
    affinities: dict[str, int] | None = None,
) -> discord.Embed:
    title_prefix = f"🏷️ {active_title} • " if active_title else ""
    embed = discord.Embed(
        title=f"👤 {title_prefix}Profil de {profile.player.display_name}",
        color=discord.Color.blue(),
    )

    # Bloc identité / progression
    embed.add_field(name="🎯 Niveau", value=str(profile.progression.level), inline=True)
    embed.add_field(name="✨ XP", value=_format_int(profile.progression.xp), inline=True)
    embed.add_field(name="💰 Or", value=_format_int(profile.resources.gold), inline=True)
    embed.add_field(name="🔥 Puissance", value=power_score, inline=True)
    embed.add_field(name="🏅 Rang", value=f"**{rank_label}**", inline=True)
    embed.add_field(
        name="📚 Skill points",
        value=_format_int(profile.progression.skill_points),
        inline=True,
    )

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

    # Affinités élémentaires (0-100 par élément) — utiles pour choisir ses
    # compétences face à l'élément de l'ennemi.
    if affinities:
        from app.shared.enums import ALL_ELEMENTS, ELEMENT_EMOJIS
        aff_str = "  ".join(
            f"{ELEMENT_EMOJIS.get(e.value, '')}{int(affinities.get(e.value, 0))}"
            for e in ALL_ELEMENTS
        )
        embed.add_field(name="🔮 Affinités élémentaires", value=aff_str, inline=False)
    embed.add_field(
        name="🔥 Daily Streak",
        value=f"{profile.resources.daily_streak}",
        inline=True,
    )

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
            f"💚 PV soignés : **{_format_int(career_stats.hp_healed_total)}**",
        ]
        embed.add_field(
            name="📈 Statistiques de carrière",
            value="\n".join(career_lines),
            inline=False,
        )

    embed.set_footer(text=f"ID Discord : {profile.player.discord_id}")

    return embed
