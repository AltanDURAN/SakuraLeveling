import json
from pathlib import Path

from app.domain.entities.skill_node import SkillEffect, SkillNode, SkillPosition
from app.domain.entities.skill_tree_definition import SkillTreeDefinition


_CONTENT_PATH = (
    Path(__file__).resolve().parents[1] / "content" / "skill_tree.json"
)

_cached_definition: SkillTreeDefinition | None = None


def _parse_node(code: str, raw: dict) -> SkillNode:
    effects = [
        SkillEffect(type=e["type"], values=e.get("values", []))
        for e in raw.get("effects", [])
    ]
    pos_raw = raw.get("position") or {}
    position = SkillPosition(
        x=int(pos_raw.get("x", 0)),
        y=int(pos_raw.get("y", 0)),
    )
    return SkillNode(
        code=code,
        name=raw["name"],
        description=raw.get("description", ""),
        icon=raw.get("icon", ""),
        max_level=int(raw.get("max_level", 1)),
        costs=list(raw.get("costs", [])),
        effects=effects,
        prerequisites=list(raw.get("prerequisites", [])),
        position=position,
    )


def get_definition() -> SkillTreeDefinition:
    """Charge l'arbre depuis le JSON. Cache module-level (chargé une fois)."""
    global _cached_definition
    if _cached_definition is None:
        with _CONTENT_PATH.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        skills = {code: _parse_node(code, data) for code, data in raw["skills"].items()}
        _cached_definition = SkillTreeDefinition(
            root=raw["root"],
            skills=skills,
        )
    return _cached_definition


def reset_cache() -> None:
    """Force un rechargement du JSON (utile pour les tests et le hot-reload)."""
    global _cached_definition
    _cached_definition = None
