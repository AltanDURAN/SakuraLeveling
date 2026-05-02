from dataclasses import dataclass, field


@dataclass
class SkillEffect:
    type: str  # ex : "atk_percent", "crit_chance_flat"
    values: list[float | int]  # valeurs par niveau (taille = max_level)


@dataclass
class SkillPosition:
    x: int
    y: int


@dataclass
class SkillNode:
    """Définition statique d'un nœud d'arbre de compétences (chargée depuis le JSON)."""

    code: str
    name: str
    description: str
    icon: str
    max_level: int
    costs: list[int]  # coût en points pour chaque niveau (taille = max_level)
    effects: list[SkillEffect]
    prerequisites: list[str]  # codes des compétences parentes
    position: SkillPosition

    def cost_for_level(self, target_level: int) -> int:
        """Coût pour passer au niveau target_level (1-indexed)."""
        if target_level <= 0 or target_level > self.max_level:
            return 0
        return self.costs[target_level - 1]

    def cumulative_cost(self, level: int) -> int:
        """Total des coûts pour atteindre `level` (utile pour le refund)."""
        if level <= 0:
            return 0
        return sum(self.costs[: min(level, self.max_level)])

    def effect_at_level(self, level: int) -> dict[str, float | int]:
        """Retourne {effect_type: value_at_this_level} pour un niveau donné."""
        result: dict[str, float | int] = {}
        if level <= 0:
            return result
        for effect in self.effects:
            idx = min(level, len(effect.values)) - 1
            if idx < 0:
                continue
            result[effect.type] = effect.values[idx]
        return result
