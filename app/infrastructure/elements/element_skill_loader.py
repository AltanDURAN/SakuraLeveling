"""Loader du catalogue de compétences élémentaires (cache module-level).

24 compétences (8 éléments × 3 rôles). Code = '<element>_<role>'.
"""

import json
from pathlib import Path

from app.domain.entities.element_skill import ElementSkill, SkillEffect


CONTENT_PATH = (
    Path(__file__).resolve().parents[1]
    / "content"
    / "element_skills.json"
)


_cache: dict[str, ElementSkill] | None = None


def _parse_effect(raw: dict) -> SkillEffect:
    return SkillEffect(
        name=raw["name"],
        kind=raw["kind"],
        value=float(raw.get("value", 1.0)),
        proc_chance=float(raw.get("proc_chance", 0.0)),
    )


def _load() -> dict[str, ElementSkill]:
    with CONTENT_PATH.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    skills: dict[str, ElementSkill] = {}
    for code, data in raw.get("skills", {}).items():
        skills[code] = ElementSkill(
            code=code,
            element=data["element"],
            role=data["role"],
            emoji=data.get("emoji", ""),
            basic=_parse_effect(data["basic"]),
            special=_parse_effect(data["special"]),
        )
    return skills


def all_skills() -> dict[str, ElementSkill]:
    global _cache
    if _cache is None:
        _cache = _load()
    return _cache


def get_skill(code: str) -> ElementSkill | None:
    return all_skills().get(code)


def skills_for_element(element: str) -> list[ElementSkill]:
    return [s for s in all_skills().values() if s.element == element]


def default_skill_code(element: str, role: str = "offensive") -> str:
    return f"{element}_{role}"


def clear_cache() -> None:
    global _cache
    _cache = None
