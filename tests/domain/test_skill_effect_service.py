"""Moteur d'effets de compétence active.

Le CATALOGUE de compétences élémentaires a disparu en saison 1 : les
compétences viennent de l'arbre. Le moteur, lui, reste — c'est lui que l'arbre
alimentera. Ces tests portent donc sur son COMPORTEMENT, plus sur un contenu
particulier.
"""

import random

import pytest

from app.domain.entities.element_skill import (
    SKILL_KIND_DAMAGE,
    SKILL_KIND_SHIELD_TEAM,
    ElementSkill,
    SkillEffect,
)
from app.domain.services.skill_effect_service import SkillEffectService


def _skill(proc_chance: float = 0.10, basic_value: float = 0.5,
           special_value: float = 1.5) -> ElementSkill:
    return ElementSkill(
        code="test", element="feu", role="offensive", emoji="🔥",
        basic=SkillEffect(name="basique", kind=SKILL_KIND_DAMAGE,
                          value=basic_value, proc_chance=0.0, mana_cost=20),
        special=SkillEffect(name="spéciale", kind=SKILL_KIND_SHIELD_TEAM,
                            value=special_value, proc_chance=proc_chance,
                            mana_cost=40),
    )


@pytest.fixture
def svc():
    return SkillEffectService()


def test_sans_proc_c_est_la_basique_qui_sort(svc):
    class NeverProcs(random.Random):
        def random(self): return 0.99

    assert svc.roll_effect(_skill(), NeverProcs()).name == "basique"


def test_avec_proc_la_speciale_REMPLACE_la_basique(svc):
    """Jamais cumulées : la spéciale prend la place du tour, elle ne s'ajoute
    pas — sinon un proc vaudrait double effet."""
    class AlwaysProcs(random.Random):
        def random(self): return 0.0

    effect = svc.roll_effect(_skill(), AlwaysProcs())
    assert effect.name == "spéciale"
    assert effect.kind == SKILL_KIND_SHIELD_TEAM


def test_une_proc_a_zero_ne_sort_jamais(svc):
    skill = _skill(proc_chance=0.0)
    noms = {svc.roll_effect(skill, random.Random(s)).name for s in range(50)}
    assert noms == {"basique"}


def test_une_proc_a_un_sort_toujours(svc):
    skill = _skill(proc_chance=1.0)
    noms = {svc.roll_effect(skill, random.Random(s)).name for s in range(50)}
    assert noms == {"spéciale"}


def test_la_frequence_de_proc_suit_la_chance_annoncee(svc):
    """Mesure empirique : une spéciale à 10 % doit sortir ~10 % du temps."""
    skill = _skill(proc_chance=0.10)
    rng = random.Random(0)
    procs = sum(
        svc.roll_effect(skill, rng).name == "spéciale" for _ in range(4000)
    )
    assert 0.07 <= procs / 4000 <= 0.13


def test_chaque_effet_porte_son_cout_en_mana():
    """Invariant : un effet qui se déclenche en combat consomme du mana, et le
    mana ne se régénère jamais pendant le combat."""
    skill = _skill()
    assert skill.basic.mana_cost > 0
    assert skill.special.mana_cost >= skill.basic.mana_cost
