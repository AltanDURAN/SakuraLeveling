"""Guilde des aventuriers — niveau global (placeholder).

Le vrai système de guilde (montée en niveau, déblocages) viendra plus tard.
Pour l'instant on considère la guilde au **niveau 1**. Point d'entrée unique
pour que les fonctionnalités gatées (ex : révélation des spécialités de mobs
dans le bestiaire au niveau 2) branchent déjà la logique — il suffira de
remplacer cette fonction quand le système existera.
"""

from __future__ import annotations

# Seuil de révélation des spécialités de monstres dans le bestiaire.
SPECIALTY_REVEAL_GUILD_LEVEL = 2


def adventurers_guild_level() -> int:
    """Niveau actuel de la guilde des aventuriers (1 tant que le système n'existe pas)."""
    return 1


def specialties_revealed() -> bool:
    """Les spécialités des monstres sont-elles visibles de tous ?"""
    return adventurers_guild_level() >= SPECIALTY_REVEAL_GUILD_LEVEL
