"""Capacités spéciales propres à certains monstres (identifiées par code).

Chaque monstre peut avoir des « particularités » résolues à des phases précises
du combat de groupe (`PartyCombatService`) :
  • `opening_assassinate` : avant le combat, une frappe PRIORITAIRE (même si le
    mob n'est pas le plus rapide), TOUJOURS critique, sur la cible la plus
    faible. Si elle tue, elle enchaîne sur la nouvelle cible la plus faible avec
    des dégâts ×2, ×3, … (série de kills) tant qu'elle tue. Puis combat normal.
  • `death_explosion` : à sa MORT, le mob explose et inflige `attack_multiplier`
    × son attaque à CHAQUE joueur (peut critique, peut être esquivé). Les
    joueurs qui en meurent perdent leurs récompenses (or/loot/kill).
  • `charm` : au DÉBUT, charme le joueur le plus puissant — il rejoint le mob et
    attaque ses alliés (jamais le mob). Le mob est INTOUCHABLE tant que le
    charmé vit. Seul face au mob, le joueur charmé est dévoré immédiatement
    (défaite). En groupe, il faut tuer le charmé pour pouvoir frapper le mob.

Ajouter une capacité = une entrée ici + (si nouvelle) le hook côté
PartyCombatService. Le combat lit un simple dict, il n'importe pas ce module
(les capacités lui sont passées en paramètre par l'appelant)."""

from __future__ import annotations

MOB_ABILITIES: dict[str, dict] = {
    "gobelin_runique": {"death_explosion": {"attack_multiplier": 3}},
    "gobelin_assassin": {"opening_assassinate": {}},
    "succube": {"charm": {}},
}


def get_mob_abilities(mob_code: str | None) -> dict:
    """Capacités spéciales du monstre (dict vide si aucune)."""
    return dict(MOB_ABILITIES.get(mob_code or "", {}))
