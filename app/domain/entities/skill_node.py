from dataclasses import dataclass


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
    #: Forme dessinée (cercle, carré, hexagone…) — purement visuelle, définie
    #: par l'auteur de l'arbre dans le builder.
    shape: str = "cercle_stat"
    #: Nature du nœud (stat, passif, actif, classe, utilité…). Sert au rendu
    #: ET à la lecture : un nœud « classe » accorde une classe, par exemple.
    node_type: str = "stat"
    #: Déjà débloqué au début de l'aventure (les racines).
    start: bool = False
    #: Comment les cases reliées EN AMONT ouvrent celle-ci :
    #:   "all" — toutes doivent être montées au maximum (jonction de classe) ;
    #:   "any" — une seule suffit (deux chemins qui mènent au même nœud).
    unlock_rule: str = "all"
    #: Groupe EXCLUSIF : une seule case du groupe par joueur (ex. les trois
    #: spécialisations, « specialisation »). Vide = aucune exclusivité.
    exclusive_group: str = ""
    #: Seuil de VOIE : {"voie": <code de la case d'entrée>, "points": N} —
    #: il faut avoir investi N points dans les cases de cette voie (tout ce qui
    #: descend de sa case d'entrée, jonctions comprises) pour l'ouvrir.
    voie_requirement: dict | None = None

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
