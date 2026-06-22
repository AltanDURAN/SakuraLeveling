from dataclasses import dataclass


# Types d'effet possibles d'une compétence (volet basique OU spécial).
SKILL_KIND_DAMAGE = "damage"            # inflige value × ATTAQUE
SKILL_KIND_SHIELD_SELF = "shield_self"  # bouclier value × DÉFENSE sur soi
SKILL_KIND_HEAL_ALLY = "heal_ally"      # soigne l'allié au PV le plus bas (value × ATTAQUE)
SKILL_KIND_SHIELD_TEAM = "shield_team"  # bouclier value × DÉFENSE sur toute l'équipe


@dataclass(frozen=True)
class SkillEffect:
    """Un effet de compétence. `value` est une FRACTION d'une stat (jamais des
    PV) : selon `kind`, multiplie l'ATTAQUE (damage/heal) ou la DÉFENSE (shield).
    `proc_chance` : 0 pour la basique (auto), >0 pour la spéciale (remplace la
    basique ce tour-là si elle proc)."""

    name: str
    kind: str
    value: float
    proc_chance: float = 0.0


@dataclass(frozen=True)
class ElementSkill:
    code: str
    element: str
    role: str  # "offensive" | "defensive" | "support"
    emoji: str
    basic: SkillEffect
    special: SkillEffect
