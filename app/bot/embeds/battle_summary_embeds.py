import discord
from discord.utils import escape_markdown

from app.shared.formatters import format_int as _format_int
from app.shared.enums import ELEMENT_EMOJIS, ELEMENT_LABELS
from app.domain.services.gear_service import RARITY_EMOJIS, RARITY_LABELS
from app.domain.value_objects.battle_summary import BattleSummary

#: Limites de Discord : 25 champs et 6 000 caractères par embed, 1 024 par
#: champ. Dépassées, l'envoi est refusé en bloc (26 joueurs ont suffi à figer
#: une zone). Au-delà, les derniers joueurs sont résumés en une ligne.
MAX_PLAYER_FIELDS = 20
EMBED_BUDGET = 5500
FIELD_LIMIT = 1024


def _add_player_fields(embed: discord.Embed, fields: list[tuple[str, str]],
                       rest_line, rest_title: str) -> None:
    """Un champ par joueur tant que l'embed peut en porter ; `rest_line(i)` :
    la ligne qui résume le joueur `i` de ceux qui n'y tiennent pas."""
    used = len(embed)
    shown = 0
    for name, value in fields:
        if shown >= MAX_PLAYER_FIELDS or used + len(name) + len(value) > EMBED_BUDGET - FIELD_LIMIT:
            break
        embed.add_field(name=name, value=value, inline=False)
        used += len(name) + len(value)
        shown += 1
    if shown == len(fields):
        return
    lines: list[str] = []
    total = 0
    for index in range(shown, len(fields)):
        line = rest_line(index)
        more = f"… et {len(fields) - index} de plus."
        if total + len(line) + 1 + len(more) > FIELD_LIMIT - 8:
            lines.append(more)
            break
        lines.append(line)
        total += len(line) + 1
    embed.add_field(name=rest_title, value="\n".join(lines), inline=False)


def _growth_lines(reward) -> list[str]:
    """Niveau gagné et titres débloqués : les moments forts d'un récap."""
    lines: list[str] = []
    if reward.levels_gained > 0:
        to_place = []
        if reward.stat_points:
            to_place.append(f"{reward.stat_points} point{'s' if reward.stat_points > 1 else ''} "
                            "de stats (/stats)")
        if reward.skill_points:
            to_place.append(f"{reward.skill_points} point{'s' if reward.skill_points > 1 else ''} "
                            "d'arbre (/arbre)")
        lines.append(f"🆙 **Niveau {reward.level_after} !**"
                     + (f" À placer : {', '.join(to_place)}." if to_place else ""))
    for title in reward.titles:
        lines.append(f"🏷️ Titre débloqué : **{escape_markdown(title)}** (/titre_actif)")
    return lines


def _xp_line(reward) -> str:
    return f"⭐ **{_format_int(reward.xp)}** XP" + (" 🌱 ×2 pour tes débuts" if reward.newcomer_bonus else "")


def _essence_lines(reward) -> list[str]:
    """Lignes de récap des essences gagnées + montées d'affinité (auto)."""
    lines: list[str] = []
    for g in getattr(reward, "essence_gains", None) or []:
        emoji = ELEMENT_EMOJIS.get(g.element, "")
        label = ELEMENT_LABELS.get(g.element, g.element)
        if g.leveled_up:
            lines.append(
                f"{emoji} +{g.essences_gained} essence · **Affinité {label} "
                f"{g.affinity_before}→{g.affinity_after}** ✨"
            )
        else:
            lines.append(
                f"{emoji} +{g.essences_gained} essence de {label.lower()} "
                f"(affinité {g.affinity_after}/100)"
            )
    return lines


def _outcome_color(summary: BattleSummary) -> discord.Color:
    return discord.Color.gold() if summary.is_victory else discord.Color.dark_red()


def _outcome_title(summary: BattleSummary) -> str:
    # « contre » : pas d'accord à faire avec une meute ou un monstre au féminin.
    return f"🏆 Victoire contre {summary.mob_name}" if summary.is_victory \
        else f"💀 Défaite contre {summary.mob_name}"


def build_rewards_page_embed(summary: BattleSummary) -> discord.Embed:
    embed = discord.Embed(
        title=_outcome_title(summary),
        color=_outcome_color(summary),
    )

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
    if summary.lunar_note:
        embed.description = "\n".join(filter(None, [summary.lunar_note, embed.description]))

    fields: list[tuple[str, str]] = []
    for reward in rewards_sorted:
        contribution = reward.contribution
        survived_emoji = "✅" if (contribution and contribution.survived) else "💀"

        lines: list[str] = []
        if summary.is_victory and contribution and contribution.survived:
            lines.append(f"💰 **{_format_int(reward.gold)}** or")
            lines.append(_xp_line(reward))
            if reward.items:
                items_text = " • ".join(
                    f"{quantity}× {getattr(reward, 'item_names', {}).get(code) or f'`{code}`'}"
                    for code, quantity in reward.items
                )
                lines.append(f"🎁 {items_text}")
            else:
                lines.append("🎁 Aucun objet")
            for gear_name, rarity in getattr(reward, "gear", None) or []:
                lines.append(
                    f"{RARITY_EMOJIS.get(rarity, '⚔️')} **{gear_name}** "
                    f"({RARITY_LABELS.get(rarity, rarity).lower()})"
                    + (" — **MYTHIQUE !**" if rarity == "mythic" else "")
                )
            lines.extend(_essence_lines(reward))
            lines.extend(_growth_lines(reward))
        elif summary.is_victory:
            lines.append(_xp_line(reward))
            lines.append("_K.O. pendant le combat : ni or ni butin._")
            lines.extend(_growth_lines(reward))
        else:
            lines.append("_Aucune récompense (défaite)._")

        fields.append((f"{survived_emoji} {escape_markdown(reward.name)}", "\n".join(lines)))

    def rest_line(index: int) -> str:
        reward = rewards_sorted[index]
        growth = f" 🆙 niveau {reward.level_after}" if reward.levels_gained > 0 else ""
        return f"{escape_markdown(reward.name)} : {_format_int(reward.gold)} or, {_format_int(reward.xp)} XP{growth}"

    _add_player_fields(embed, fields, rest_line, "Et aussi")

    if summary.is_victory:
        embed.set_footer(
            text=(
                f"Combat en {summary.turns} actions • "
                "Or partagé selon la contribution (dégâts, coups encaissés, soins) • "
                "XP égale pour tous"
            )
        )
    return embed


#: Lignes du graphique de contribution (une ligne fait ~45 caractères).
CHART_MAX_LINES = 20


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

    # Classement décroissant par part de contribution ; le graphique tient
    # dans un champ de Discord (1 024 caractères).
    ranked = sorted(survivors, key=lambda r: r.contribution_share, reverse=True)
    sorted_rewards = ranked[:CHART_MAX_LINES]

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
    if len(ranked) > len(sorted_rewards):
        lines.append(f"   … et {len(ranked) - len(sorted_rewards)} de plus")

    return "```\n" + "\n".join(lines) + "\n```"


def build_details_page_embed(summary: BattleSummary) -> discord.Embed:
    embed = discord.Embed(
        title=f"📊 Détails du combat — {summary.mob_name}",
        color=_outcome_color(summary),
    )

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

    fields: list[tuple[str, str]] = []
    detailed = []
    for reward in rewards_sorted:
        contribution = reward.contribution
        if contribution is None:
            continue
        detailed.append(reward)

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
        if contribution.mana_max > 0:
            spent = f" (−{contribution.mana_spent} en compétences)" if contribution.mana_spent else ""
            lines.append(f"💧 Mana restant : **{contribution.final_mana}** / {contribution.mana_max}{spent}")

        fields.append((f"{survived_emoji} {escape_markdown(reward.name)}{header_suffix}", "\n".join(lines)))

    def rest_line(index: int) -> str:
        c = detailed[index].contribution
        return (f"{escape_markdown(detailed[index].name)} : ⚔️ {_format_int(c.damage_dealt)} · "
                f"🛡️ {_format_int(c.damage_tanked)} · 💚 {_format_int(c.hp_healed)}")

    _add_player_fields(embed, fields, rest_line, "Et aussi")

    embed.set_footer(
        text=(
            f"Combat en {summary.turns} actions • "
            "🏅 = part de contribution (dégâts, coups encaissés, soins) qui répartit l'or"
        )
    )
    return embed


#: Lignes du journal qui méritent d'être gardées quand tout ne tient pas :
#: critiques, chutes, exécutions, résurrections, renforcements…
_KEY_MARKERS = ("CRIT", "💀", "exécuté", "renaît", "revient", "relevé", "engloutit", "charme",
                "explose", "s'éternise", "libéré", "Égide", "tient bon")
_JOURNAL_BUDGET = 3900


def build_journal_page_embed(summary: BattleSummary) -> discord.Embed:
    """Le déroulé du combat : tout s'il tient, sinon les moments clés."""
    embed = discord.Embed(title=f"📜 Journal du combat — {summary.mob_name}", color=_outcome_color(summary))
    lines = list(summary.journal)
    if not lines:
        embed.description = "_Aucune action enregistrée._"
        return embed
    if sum(len(line) + 1 for line in lines) > _JOURNAL_BUDGET:
        key = [line for line in lines if any(m in line for m in _KEY_MARKERS)]
        header = f"_Moments clés — {len(lines)} actions en tout._"
        kept, total = [], len(header) + 1
        for line in key + [lines[-1]] if lines[-1] not in key else key:
            if total + len(line) + 1 > _JOURNAL_BUDGET:
                break
            kept.append(line)
            total += len(line) + 1
        lines = [header, *kept]
    embed.description = "\n".join(lines)
    return embed


PAGES = [
    ("🎁 Récompenses", build_rewards_page_embed),
    ("📊 Détails du combat", build_details_page_embed),
    ("📜 Journal", build_journal_page_embed),
]
