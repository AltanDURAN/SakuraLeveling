"""Résolution des compétences élémentaires en combat.

Modèle V1 (refonte juin 2026) : 2 compétences équipées (slots libres). À chaque
tour où le joueur agit, CHAQUE compétence équipée se résout indépendamment :
la BASIQUE par défaut, et à `proc_chance` (10%) la SPÉCIALE la REMPLACE (jamais
les deux cumulées). Les effets sont en % de STATS (ATK ou DEF), jamais en % de PV.

Service pur (aucune dépendance DB/Discord). Le combat (`PartyCombatService`)
appelle `roll_effect` puis applique l'effet selon son `kind`.
"""

from __future__ import annotations

import random

from app.domain.entities.element_skill import ElementSkill, SkillEffect


class SkillEffectService:
    def roll_effect(
        self, skill: ElementSkill, rng: random.Random | None = None
    ) -> SkillEffect:
        """Tire l'effet du tour pour une compétence : spéciale si elle proc,
        sinon basique."""
        rng = rng or random
        if skill.special.proc_chance > 0 and rng.random() < skill.special.proc_chance:
            return skill.special
        return skill.basic


def offensive_element(skills: list[ElementSkill]) -> str | None:
    """Élément d'attaque du joueur = élément de sa compétence OFFENSIVE équipée
    (la première trouvée). None si aucune offensive → attaque neutre."""
    for skill in skills:
        if skill is not None and skill.role == "offensive":
            return skill.element
    return None
