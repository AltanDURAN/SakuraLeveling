"""Embeds pour le système de world boss."""

from pathlib import Path
import discord
from discord.utils import escape_markdown

from app.application.use_cases.world_boss import BossRewardEntry
from app.domain.entities.world_boss import WorldBoss


BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent


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
            "Cliquez **Rejoindre** pour vous inscrire au raid, puis "
            "**Lancer le combat** quand vous êtes prêt (1 combat / jour)."
        ),
        color=color,
    )
    embed.add_field(
        name="❤️ PV restants",
        value=(
            f"{_hp_bar(boss.current_hp, boss.max_hp)}\n"
            f"**{boss.current_hp:,} / {boss.max_hp:,}**"
        ),
        inline=False,
    )
    embed.add_field(
        name="📊 Stats",
        value=(
            f"⚔️ Atk : **{boss.attack:,}**\n"
            f"🛡️ Def : **{boss.defense:,}**\n"
            f"💨 Spd : **{boss.speed}**"
        ),
        inline=True,
    )
    inscrit_word = _pluralize(num_participants, "inscrit")
    combattu_word = _pluralize(num_fought, "combattu")
    participant_lines = [f"**{num_participants}** {inscrit_word}"]
    if num_fought > 0:
        participant_lines.append(f"dont **{num_fought}** {combattu_word}")
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


def build_boss_defeated_embed(
    boss: WorldBoss, rewards: list[BossRewardEntry]
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
        "top_damage": "💥 Top Dégâts",
        "top_tank": "🛡️ Top Tank",
        "top_heal": "💚 Top Heal",
        "participant": "🎖️ Participant",
    }

    # Trier : tops d'abord, puis participants
    role_priority = {"top_damage": 0, "top_tank": 1, "top_heal": 2, "participant": 3}
    rewards_sorted = sorted(rewards, key=lambda r: (role_priority.get(r.role, 99), -r.gold))

    lines: list[str] = []
    for reward in rewards_sorted[:25]:  # cap à 25 pour rester lisible
        items_txt = ", ".join(f"{q}× {c}" for c, q in reward.items)
        safe_name = escape_markdown(reward.display_name)
        lines.append(
            f"{role_label.get(reward.role, '🎖️')} **{safe_name}** — "
            f"{reward.gold}g, {reward.xp}xp, {items_txt}"
        )
    if lines:
        embed.add_field(name="🎁 Récompenses", value="\n".join(lines), inline=False)

    return embed
