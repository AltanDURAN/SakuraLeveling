from dataclasses import dataclass

from app.domain.entities.skill_node import SkillNode


@dataclass
class SkillTreeDefinition:
    """Représentation en mémoire de l'arbre complet (chargé depuis le JSON)."""

    root: str  # code du nœud racine
    skills: dict[str, SkillNode]  # skill_code -> SkillNode

    def get(self, code: str) -> SkillNode | None:
        return self.skills.get(code)

    def __iter__(self):
        return iter(self.skills.values())

    @property
    def root_node(self) -> SkillNode:
        return self.skills[self.root]
