"""Embed du journal de combat tour par tour pour les encounters naturels.

Un message dédié envoyé pendant le combat, édité à chaque tour pour ajouter
la dernière action (qui frappe qui, crit, esquive, dégâts). À la fin du
combat, un lien de redirection vers le message de spawn (où s'affiche le
récap final) est ajouté en tête.
"""

from __future__ import annotations

import discord

from app.domain.value_objects.party_battle_turn_log import PartyBattleTurnLog


# Limite Discord pour le champ description (4096 chars). On coupe les
# anciennes lignes si on dépasse pour garder le message lisible et toujours
# centré sur les derniers tours.
_DESCRIPTION_BUDGET = 3500


def format_turn_action(turn_log: PartyBattleTurnLog) -> str:
    """Convertit un PartyBattleTurnLog en une ligne lisible pour le journal.

    Les textes brut viennent déjà du domain (`player_actions[0]` /
    `mob_action`). Ici on choisit l'icône qui résume le tour : esquive,
    crit, dégâts normaux. Pas de retraitement métier.
    """
    turn = turn_log.turn_number

    if turn_log.player_actions:
        # Tour d'un joueur — `mob_action` reflète ce qu'il subit
        # ("subit l'attaque" / "esquive l'attaque").
        player_action = turn_log.player_actions[0]
        if "esquive" in turn_log.mob_action.lower():
            return f"`T{turn}` 🌀 {turn_log.mob_action}"
        if "(CRIT)" in player_action:
            return f"`T{turn}` 💥 {player_action}"
        return f"`T{turn}` ⚔️ {player_action}"

    mob_action = turn_log.mob_action
    if "esquiv" in mob_action.lower():
        return f"`T{turn}` 🌀 {mob_action}"
    if "(CRIT)" in mob_action:
        return f"`T{turn}` 💥 {mob_action}"
    return f"`T{turn}` 🛡️ {mob_action}"


def _trim_to_budget(lines: list[str]) -> list[str]:
    """Coupe les anciennes lignes si la description dépasse le budget.
    Garde toujours les plus récentes (tail-trim)."""
    total = 0
    kept: list[str] = []
    for line in reversed(lines):
        new_total = total + len(line) + 1
        if new_total > _DESCRIPTION_BUDGET:
            break
        kept.append(line)
        total = new_total
    kept.reverse()
    if len(kept) < len(lines):
        kept.insert(0, "_(tours plus anciens tronqués…)_")
    return kept


def build_combat_log_embed(
    mob_name: str,
    actions: list[str],
    mob_current_hp: int,
    mob_max_hp: int,
    players_state: list[dict] | None,
    finished: bool = False,
    redirect_url: str | None = None,
) -> discord.Embed:
    color = discord.Color.dark_green() if finished else discord.Color.orange()
    title = (
        f"✅ Combat terminé — {mob_name}"
        if finished
        else f"⚔️ Combat en cours — {mob_name}"
    )

    description_lines: list[str] = []
    if finished and redirect_url:
        description_lines.append(
            f"🏁 **Combat terminé !** "
            f"Voir les récompenses et le détail : [aller au récap]({redirect_url})"
        )
        description_lines.append("")

    description_lines.extend(_trim_to_budget(actions))

    embed = discord.Embed(
        title=title,
        description="\n".join(description_lines) or "_Le combat va commencer…_",
        color=color,
    )

    # PV du mob — toujours utile pendant le combat
    embed.add_field(
        name=f"👹 {mob_name}",
        value=f"❤️ **{max(0, mob_current_hp):,} / {mob_max_hp:,}** PV",
        inline=False,
    )

    # PV des joueurs — uniquement pendant le combat (au récap on a la page Détails)
    if not finished and players_state:
        lines = []
        for ps in players_state:
            name = ps.get("name", "?")
            chp = max(0, int(ps.get("current_hp", 0) or 0))
            mhp = int(ps.get("max_hp", 1) or 1)
            status = "💀" if chp <= 0 else "❤️"
            lines.append(f"{status} **{name}** — {chp:,} / {mhp:,}")
        embed.add_field(
            name="👥 Équipe",
            value="\n".join(lines) or "_aucun_",
            inline=False,
        )

    return embed
