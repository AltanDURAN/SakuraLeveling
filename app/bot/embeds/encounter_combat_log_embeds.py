"""Embed du journal de combat tour par tour pour les encounters naturels.

Un message dédié envoyé pendant le combat, édité à chaque tour pour ajouter
la dernière action (qui frappe qui, crit, esquive, dégâts). À la fin du
combat, un lien de redirection vers le message de spawn (où s'affiche le
récap final) est ajouté en tête.
"""

from __future__ import annotations


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


