"""Tests du catalogue de compétences élémentaires + résolution par tour."""

import random

from app.domain.entities.element_skill import (
    SKILL_KIND_DAMAGE,
    SKILL_KIND_HEAL_ALLY,
    SKILL_KIND_SHIELD_SELF,
    SKILL_KIND_SHIELD_TEAM,
)
from app.domain.services.skill_effect_service import SkillEffectService, offensive_element
from app.infrastructure.elements import element_skill_loader as L


def test_catalog_has_24_skills_with_kinds():
    L.clear_cache()
    skills = L.all_skills()
    assert len(skills) == 24
    assert L.get_skill("feu_offensive").basic.kind == SKILL_KIND_DAMAGE
    assert L.get_skill("feu_defensive").basic.kind == SKILL_KIND_SHIELD_SELF
    assert L.get_skill("feu_support").basic.kind == SKILL_KIND_HEAL_ALLY
    assert L.get_skill("feu_support").special.kind == SKILL_KIND_SHIELD_TEAM


def test_each_element_has_three_roles():
    L.clear_cache()
    for element in ("feu", "eau", "plante", "glace", "vent", "terre", "tenebre", "lumiere"):
        codes = {s.code for s in L.skills_for_element(element)}
        assert codes == {f"{element}_offensive", f"{element}_defensive", f"{element}_support"}


def test_roll_effect_basic_when_no_proc():
    svc = SkillEffectService()
    skill = L.get_skill("feu_offensive")
    # rng.random() = 0.99 → pas de proc (>0.1) → basique
    rng = random.Random()
    rng.random = lambda: 0.99  # type: ignore
    assert svc.roll_effect(skill, rng).value == 1.0


def test_roll_effect_special_when_proc():
    svc = SkillEffectService()
    skill = L.get_skill("feu_offensive")
    rng = random.Random()
    rng.random = lambda: 0.0  # type: ignore  # < 0.1 → proc → spéciale
    assert svc.roll_effect(skill, rng).value == 1.5


def test_offensive_element_resolution():
    off = L.get_skill("eau_offensive")
    sup = L.get_skill("feu_support")
    assert offensive_element([off, sup]) == "eau"
    assert offensive_element([sup]) is None  # aucune offensive
    assert offensive_element([]) is None
