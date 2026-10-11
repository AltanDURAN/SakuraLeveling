from dataclasses import dataclass, field

from app.domain.entities.skill_node import SkillNode


@dataclass(frozen=True)
class SkillLink:
    """Lien dessiné entre deux nœuds.

    Un lien EST un prérequis : le nœud source doit être monté au MAXIMUM pour
    que la cible devienne déblocable. Le `type` ne change que l'apparence —
    il permet à l'auteur de distinguer visuellement une branche majeure d'un
    embranchement secondaire.
    """

    source: str
    target: str
    type: str = "simple"


@dataclass
class SkillTreeDefinition:
    """Représentation en mémoire de l'arbre complet (chargé depuis le JSON)."""

    root: str  # racine historique (compatibilité)
    skills: dict[str, SkillNode]  # skill_code -> SkillNode
    #: Toutes les racines déjà débloquées au départ. L'arbre de la saison 1 en
    #: a deux : le centre des trois voies de combat, et celui de l'utilité.
    roots: list[str] = field(default_factory=list)
    #: Palettes définies par l'auteur dans le builder (forme → réglages).
    shapes: dict[str, dict] = field(default_factory=dict)
    node_types: dict[str, dict] = field(default_factory=dict)
    link_types: dict[str, dict] = field(default_factory=dict)
    links: list[SkillLink] = field(default_factory=list)

    def get(self, code: str) -> SkillNode | None:
        return self.skills.get(code)

    def __iter__(self):
        return iter(self.skills.values())

    @property
    def root_node(self) -> SkillNode:
        return self.skills[self.root]

    @property
    def all_roots(self) -> list[str]:
        return self.roots or ([self.root] if self.root in self.skills else [])

    def children_of(self, code: str) -> list[str]:
        return [n.code for n in self.skills.values() if code in n.prerequisites]
