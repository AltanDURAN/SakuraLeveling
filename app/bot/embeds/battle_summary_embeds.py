import discord

from app.domain.value_objects.battle_summary import BattleSummary


def _format_int(value: int) -> str:
    return f"{value:,}".replace(",", " ")


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
            name=f"{survived_emoji} {reward.name}",
            value="\n".join(lines),
            inline=False,
        )

    if summary.is_victory:
        embed.set_footer(
            text=f"Combat en {summary.turns} actions • Or partagé selon les dégâts • XP selon le rapport de force"
        )
    return embed


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
        key=lambda r: (r.contribution.damage_dealt if r.contribution else 0),
        reverse=True,
    )

    total_damage = sum(
        (r.contribution.damage_dealt if r.contribution else 0) for r in summary.rewards
    )

    for reward in rewards_sorted:
        contribution = reward.contribution
        if contribution is None:
            continue

        survived_emoji = "✅" if contribution.survived else "💀"
        share = (
            f" ({100 * contribution.damage_dealt // total_damage}%)"
            if total_damage > 0
            else ""
        )

        lines = [
            f"⚔️ Dégâts infligés : **{_format_int(contribution.damage_dealt)}**{share}",
            f"🛡️ Dégâts encaissés : **{_format_int(contribution.damage_tanked)}**",
            f"💚 PV régénérés : **{_format_int(contribution.hp_healed)}**",
            f"❤️ PV restants : **{contribution.final_hp}** / {contribution.max_hp}",
        ]

        embed.add_field(
            name=f"{survived_emoji} {reward.name}",
            value="\n".join(lines),
            inline=False,
        )

    embed.set_footer(text=f"Combat en {summary.turns} actions")
    return embed


PAGES = [
    ("🎁 Récompenses", build_rewards_page_embed),
    ("📊 Détails du combat", build_details_page_embed),
]
