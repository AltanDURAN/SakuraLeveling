"""Stats de BASE du joueur — le socle sur lequel tout le reste s'appuie.

SAISON 1 — refonte. Trois stats seulement, montées par des POINTS DE STATS
(un par niveau, placés par le joueur comme dans un isekai) :

    ⚔️ attaque de base · 🛡️ défense de base · ❤️ PV max de base

Pourquoi seulement trois : parce que **l'équipement et l'arbre s'expriment en
POURCENTAGE de ces trois-là**. C'est ce qui fait qu'une pièce de haut niveau
offerte à un débutant ne le rend pas surpuissant — elle ne multiplie qu'un
socle minuscule. Plus le socle est large, plus le même objet rapporte.

Les autres stats de combat (vitesse, esquive, crit, régénérations, mana) ne
passent JAMAIS par les points de stats : elles viennent de l'arbre de
compétences, en valeurs BRUTES. Un « pourcentage de pourcentage de crit »
n'aurait aucun sens lisible.

Valeurs par point : un point de défense et un point de PV pèsent le MÊME
poids en PV effectifs (le projet convertit 1 DEF ≈ 25 PV dans le power score,
ici 50 PV pour 2 DEF). L'attaque est l'axe offensif, volontairement distinct.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Socle au niveau 1, avant le moindre point investi.
START_ATTACK = 10
START_DEFENSE = 5
START_MAX_HP = 100

#: Ce que rapporte UN point de stat.
ATTACK_PER_POINT = 2
DEFENSE_PER_POINT = 2
MAX_HP_PER_POINT = 50


@dataclass(frozen=True)
class BaseStats:
    """Les trois stats de base, déjà résolues (socle + points investis)."""

    attack: int = START_ATTACK
    defense: int = START_DEFENSE
    max_hp: int = START_MAX_HP

    @classmethod
    def from_points(
        cls, attack_points: int = 0, defense_points: int = 0, hp_points: int = 0,
    ) -> "BaseStats":
        return cls(
            attack=START_ATTACK + ATTACK_PER_POINT * max(0, attack_points),
            defense=START_DEFENSE + DEFENSE_PER_POINT * max(0, defense_points),
            max_hp=START_MAX_HP + MAX_HP_PER_POINT * max(0, hp_points),
        )

    @property
    def invested_points(self) -> int:
        """Nombre de points réellement placés (utile pour un remboursement)."""
        return (
            (self.attack - START_ATTACK) // ATTACK_PER_POINT
            + (self.defense - START_DEFENSE) // DEFENSE_PER_POINT
            + (self.max_hp - START_MAX_HP) // MAX_HP_PER_POINT
        )


#: Les trois cibles investissables, pour l'UI et la validation des commandes.
STAT_POINT_TARGETS: dict[str, str] = {
    "attack": "Attaque",
    "defense": "Défense",
    "max_hp": "PV max",
}

STAT_POINT_GAIN: dict[str, int] = {
    "attack": ATTACK_PER_POINT,
    "defense": DEFENSE_PER_POINT,
    "max_hp": MAX_HP_PER_POINT,
}
