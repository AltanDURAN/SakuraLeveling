import discord
from discord.utils import escape_markdown

from app.shared.formatters import format_int as _format_int
from app.domain.value_objects.battle_summary import BattleSummary


def _outcome_color(summary: BattleSummary) -> discord.Color:
    if summary.is_victory:
        return discord.Color.gold()
    if summary.is_defeat:
        return discord.Color.dark_red()
    return discord.Color.light_grey()


def _outcome_title(summary: BattleSummary) -> str:
    if summary.is_victory:
        return f"🏆 Victoire — {summary.mob_name} vaincu"
    if summary.is_defeat:
        return f"💀 Défaite — {summary.mob_name} l'emporte"
    return f"🌫️ Le {summary.mob_name} s'est échappé"


def build_rewards_page_embed(summary: BattleSummary) -> discord.Embed:
    embed = discord.Embed(
        title=_outcome_title(summary),
        color=_outcome_color(summary),
    )

    if summary.is_flee:
        embed.description = (
            "Personne ne s'est présenté pour combattre. "
            "Le monstre a disparu dans la nature avec son butin."
        )
        return embed

    rewards_sorted = sorted(
        summary.rewards,
        key=lambda r: (r.gold, r.xp),
        reverse=True,
    )

    if not summary.is_victory:
        embed.description = (
            f"Le groupe a tenu **{summary.turns} actions** mais a été vaincu. "
            "Aucune récompense n'est distribuée."
        )

    for reward in rewards_sorted:
        contribution = reward.contribution
        survived_emoji = "✅" if (contribution and contribution.survived) else "💀"

        lines: list[str] = []
        if summary.is_victory and contribution and contribution.survived:
            lines.append(f"💰 **{_format_int(reward.gold)}** or")
            lines.append(f"⭐ **{_format_int(reward.xp)}** XP")
            if reward.items:
                items_text = " • ".join(
                    f"{quantity}× `{code}`" for code, quantity in reward.items
                )
                lines.append(f"🎁 {items_text}")
            else:
                lines.append("🎁 Aucun objet")
        elif summary.is_victory:
            lines.append("_Vaincu pendant le combat — aucune récompense._")
        else:
            lines.append("_Aucune récompense (défaite)._")

        embed.add_field(
            name=f"{survived_emoji} {escape_markdown(reward.name)}",
            value="\n".join(lines),
            inline=False,
        )

    if summary.is_victory:
        embed.set_footer(
            text=(
                f"Combat en {summary.turns} actions • "
                "Or partagé selon la contribution (dégâts + tank + soins) • "
                "XP selon le rapport de force"
            )
        )
    return embed


def _percent_of(value: int, total: int) -> str:
    if total <= 0:
        return ""
    return f" ({round(100 * value / total)}%)"


def _build_contribution_chart(rewards: list, bar_width: int = 18) -> str:
    """Construit un graphique ASCII de la part de contribution.

    Format en bloc monospace, classement décroissant, médailles pour le top 3
    et le nom tronqué/paddé pour aligner les barres. Renvoie une string déjà
    enrobée dans un bloc ``` (markdown code) pour préserver l'alignement
    fixe quel que soit le client Discord.
    """
    survivors = [r for r in rewards if r.contribution_share > 0]
    if not survivors:
        return ""

    # Classement décroissant par part de contribution
    sorted_rewards = sorted(survivors, key=lambda r: r.contribution_share, reverse=True)

    # Plus long nom (tronqué à 12) pour un padding cohérent
    name_width = max(len(r.name[:12]) for r in sorted_rewards)
    name_width = max(name_width, 8)

    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for idx, reward in enumerate(sorted_rewards):
        share = reward.contribution_share
        pct = round(share * 100)
        filled = round(share * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)
        # Les médailles ne sont PAS en monospace donc l'alignement post-médaille
        # peut bouger ; on accepte ce léger décalage pour le top 3.
        prefix = medals[idx] if idx < 3 else "  "
        name_str = reward.name[:12].ljust(name_width)
        lines.append(f"{prefix} {name_str}  {bar}  {pct:>3}%")

    return "```\n" + "\n".join(lines) + "\n```"


def build_details_page_embed(summary: BattleSummary) -> discord.Embed:
    embed = discord.Embed(
        title=f"📊 Détails du combat — {summary.mob_name}",
        color=_outcome_color(summary),
    )

    if summary.is_flee:
        embed.description = "Pas de combat à détailler."
        return embed

    if not summary.rewards:
        embed.description = "Aucun participant à détailler."
        return embed

    rewards_sorted = sorted(
        summary.rewards,
        key=lambda r: r.contribution_share,
        reverse=True,
    )

    # Bandeau "graphique de participation" en haut du panneau Détails.
    # Permet de voir d'un coup la répartition (qui a porté le combat)
    # avant de plonger dans le détail des métriques par joueur.
    chart = _build_contribution_chart(rewards_sorted)
    if chart:
        embed.add_field(
            name="🏅 Part de victoire",
            value=chart,
            inline=False,
        )

    team_dmg = sum(
        (r.contribution.damage_dealt if r.contribution else 0) for r in summary.rewards
    )
    team_tanked = sum(
        (r.contribution.damage_tanked if r.contribution else 0) for r in summary.rewards
    )
    team_healed = sum(
        (r.contribution.hp_healed if r.contribution else 0) for r in summary.rewards
    )

    for reward in rewards_sorted:
        contribution = reward.contribution
        if contribution is None:
            continue

        survived_emoji = "✅" if contribution.survived else "💀"
        share_pct = round(reward.contribution_share * 100)
        header_suffix = (
            f" — 🏅 {share_pct}% de la victoire" if contribution.survived else ""
        )

        lines = [
            f"⚔️ Dégâts infligés : **{_format_int(contribution.damage_dealt)}**"
            f"{_percent_of(contribution.damage_dealt, team_dmg)}",
            f"🛡️ Dégâts encaissés : **{_format_int(contribution.damage_tanked)}**"
            f"{_percent_of(contribution.damage_tanked, team_tanked)}",
            f"💚 PV soignés : **{_format_int(contribution.hp_healed)}**"
            f"{_percent_of(contribution.hp_healed, team_healed)}",
            f"❤️ PV restants : **{contribution.final_hp}** / {contribution.max_hp}",
        ]

        embed.add_field(
            name=f"{survived_emoji} {escape_markdown(reward.name)}{header_suffix}",
            value="\n".join(lines),
            inline=False,
        )

    embed.set_footer(
        text=(
            f"Combat en {summary.turns} actions • "
            "🏅 = part de contribution (dégâts + tank + soins) qui pondère le partage de l'or"
        )
    )
    return embed


PAGES = [
    ("🎁 Récompenses", build_rewards_page_embed),
    ("📊 Détails du combat", build_details_page_embed),
]
