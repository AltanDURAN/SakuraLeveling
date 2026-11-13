"""Embeds pour le système de world boss."""

from pathlib import Path
import discord
from discord.utils import escape_markdown

from app.application.use_cases.world_boss import BossRewardEntry
from app.bot.embeds.limits import add_lines
from app.domain.entities.world_boss import WorldBoss
from app.domain.services import element_service
from app.shared.enums import ELEMENT_EMOJIS, ELEMENT_LABELS
from app.shared.formatters import format_int


BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent


def _element_field_value(element: str) -> str:
    """Élément du boss + faiblesses (éléments qui le battent) pour l'embed."""
    if not element:
        return "**neutre**"
    emoji = ELEMENT_EMOJIS.get(element, "")
    label = ELEMENT_LABELS.get(element, element)
    weak = element_service.weaknesses_of(element)
    weak_str = ", ".join(
        f"{ELEMENT_EMOJIS.get(e.value, '')}{ELEMENT_LABELS.get(e.value, e.value)}"
        for e in weak
    ) or "—"
    return f"{emoji} **{label}**\nFaible à : {weak_str}"


def _hp_bar(current: int, maximum: int) -> str:
    if maximum <= 0 or current <= 0:
        return "⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛"
    ratio = current / maximum
    filled = int(round(ratio * 10))
    if ratio >= 0.5:
        char = "🟩"
    elif ratio >= 0.25:
        char = "🟨"
    else:
        char = "🟥"
    return char * filled + "⬛" * (10 - filled)


def _pluralize(n: int, singular: str, plural: str | None = None) -> str:
    return singular if n <= 1 else (plural or singular + "s")


def build_boss_dashboard_embed(
    boss: WorldBoss,
    num_participants: int,
    team_bonus_pct: int,
    num_fought: int = 0,
    votes: int = 0,
) -> discord.Embed:
    color = (
        discord.Color.dark_purple()
        if boss.is_alive
        else discord.Color.dark_grey()
    )
    title_emoji = "👑" if boss.is_alive else "💀"
    embed = discord.Embed(
        title=f"{title_emoji} World Boss : {boss.name}",
        description=(
            "Combat à l'usure : le boss ne regagne **jamais** de PV.\n"
            "🤝 **Rejoindre** pour vous inscrire, puis 🗳️ **Voter pour lancer** "
            "quand vous êtes prêt. Combat lancé quand **tous** les inscrits "
            "ont voté."
        ),
        color=color,
    )
    embed.add_field(
        name="❤️ PV restants",
        value=(
            f"{_hp_bar(boss.current_hp, boss.max_hp)}\n"
            f"**{format_int(boss.current_hp)} / {format_int(boss.max_hp)}**"
        ),
        inline=False,
    )
    embed.add_field(
        name="📊 Stats",
        value=(
            f"⚔️ Atk : **{format_int(boss.attack)}**\n"
            f"🛡️ Def : **{format_int(boss.defense)}**\n"
            f"💨 Spd : **{boss.speed}**"
        ),
        inline=True,
    )
    embed.add_field(
        name="🔮 Élément",
        value=_element_field_value(boss.element),
        inline=True,
    )
    inscrit_word = _pluralize(num_participants, "inscrit")
    combattu_word = _pluralize(num_fought, "combattu")
    participant_lines = [f"**{num_participants}** {inscrit_word}"]
    if num_fought > 0:
        participant_lines.append(f"dont **{num_fought}** {combattu_word}")
    if num_participants > 0:
        participant_lines.append(
            f"🗳️ Votes : **{votes}/{num_participants}**"
        )
    participant_lines.append(f"Bonus d'équipe : **+{team_bonus_pct}%**")
    embed.add_field(
        name="🤝 Participants",
        value="\n".join(participant_lines),
        inline=True,
    )
    if not boss.is_alive:
        embed.set_footer(text="Boss vaincu — récompenses distribuées.")
    else:
        embed.set_footer(text="Le boss reste actif tant qu'il a des PV.")

    if boss.image_name:
        path = BASE_DIR / "assets" / "mobs" / boss.image_name
        if path.exists():
            embed.set_thumbnail(url=f"attachment://{boss.image_name}")
    return embed


def build_boss_escaped_embed(boss: WorldBoss, rewards: list[BossRewardEntry]) -> discord.Embed:
    """Le boss a tenu toute la semaine : il repart, chacun touche sa part."""
    left = round(100 * boss.current_hp / max(1, boss.max_hp))
    embed = discord.Embed(
        title=f"🌫️ {boss.name} repart",
        description=(
            f"Il quitte le champ de bataille avec **{left} %** de ses PV. Pas de butin ni de titre "
            "cette fois, mais chacun touche sa part selon les PV qu'on lui a retirés."
            if rewards else f"Il quitte le champ de bataille avec **{left} %** de ses PV : "
                            "personne ne s'est mesuré à lui cette semaine."
        ),
        color=discord.Color.dark_grey(),
    )
    lines = [f"**{escape_markdown(r.display_name)}** : {format_int(r.gold)} or, {format_int(r.xp)} XP"
             for r in sorted(rewards, key=lambda r: -r.gold)]
    add_lines(embed, "🎁 Récompenses", lines, max_fields=4, more="… et {n} autre(s) participant(s)")
    return embed


def build_boss_defeated_embed(
    boss: WorldBoss, rewards: list[BossRewardEntry], item_names: dict[str, str] | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🏆 {boss.name} a été vaincu !",
        description=(
            f"Les héros ont triomphé après l'avoir lentement épuisé.\n"
            f"**{len(rewards)}** participant(s) reçoivent leur dû."
        ),
        color=discord.Color.gold(),
    )

    role_label = {
        "top1_global": "🥇 MVP",
        "top2_global": "🥈 2ᵉ",
        "top3_global": "🥉 3ᵉ",
        "top_damage": "💥 Top Dégâts",
        "top_tank": "🛡️ Top Tank",
        "top_heal": "💚 Top Soin",
        "top_participation": "⏱️ Top Présence",
        "participant": "🎖️ Participant",
    }

    # Trier : podium global d'abord, puis catégories, puis participants.
    role_priority = {
        "top1_global": 0, "top2_global": 1, "top3_global": 2,
        "top_damage": 3, "top_tank": 4, "top_heal": 5,
        "top_participation": 6, "participant": 7,
    }
    rewards_sorted = sorted(rewards, key=lambda r: (role_priority.get(r.role, 99), -r.gold))

    # Un joueur ne doit jamais lire un code d'objet (`potion_soin`).
    names = item_names or {}
    lines: list[str] = []
    for reward in rewards_sorted:
        parts = [f"{format_int(reward.gold)} or", f"{format_int(reward.xp)} XP"]
        parts += [f"{q}× {names.get(c, c.replace('_', ' '))}" for c, q in reward.items]
        safe_name = escape_markdown(reward.display_name)
        lines.append(f"{role_label.get(reward.role, '🎖️')} **{safe_name}** — {', '.join(parts)}")
    # Tout le monde est listé, en plusieurs champs : à 14 participants, un
    # seul champ dépassait les 1 024 caractères et Discord refusait le message
    # de victoire (revue du 13/11/2026).
    add_lines(embed, "🎁 Récompenses", lines, max_fields=5, more="… et {n} autre(s) participant(s)")

    return embed
