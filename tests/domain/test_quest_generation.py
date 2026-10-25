"""Quêtes adaptées (25/10/2026) : la cible suit la zone, la quantité le niveau,
l'objectif le rôle — et une quotidienne se fait seul en une journée."""

import random

import pytest

from app.domain.services import quest_generation_service as qgs
from app.infrastructure.daily_quests.quest_loader import list_definitions as daily_templates
from app.infrastructure.weekly_quests.quest_loader import list_definitions as weekly_templates

FAMILIES = (qgs.FamilyChoice("slime", 1, 0.15), qgs.FamilyChoice("gobelin", 6, 0.85),
            qgs.FamilyChoice("mort-vivant", 14, 1.0), qgs.FamilyChoice("demoniaque", 44, 1.0))


def ctx(level, roles=(), families=FAMILIES):
    return qgs.QuestContext(level=level, roles=frozenset(roles), families=families)


def test_la_quantite_suit_le_niveau():
    assert qgs.scaled_quantity("count", 5, 80) == 5
    assert qgs.scaled_quantity("xp", 5, 10) == qgs._nice(5 * 6.25 * 10)
    assert qgs.scaled_quantity("xp", 5, 80) > 7 * qgs.scaled_quantity("xp", 5, 10)
    assert qgs.scaled_quantity("damage", 4, 100) > qgs.scaled_quantity("damage", 4, 20)


def test_la_famille_suit_la_zone_et_le_niveau():
    assert qgs.best_family(ctx(5)).family == "gobelin"          # le slime est trop rare
    assert qgs.best_family(ctx(20)).family == "mort-vivant"
    assert qgs.best_family(ctx(60)).family == "demoniaque"
    # Rang trop bas pour le cimetière : on reste aux gobelins.
    assert qgs.best_family(ctx(60, families=FAMILIES[:2])).family == "gobelin"
    assert qgs.best_family(ctx(60, families=FAMILIES[:1])) is None


def test_l_objectif_suit_le_role():
    soins = next(t for t in daily_templates() if t.target == "soutien")
    degats = next(t for t in daily_templates() if t.objective_type == "damage_dealt")
    assert qgs.eligible(soins, ctx(40, {"soutien"}))
    assert not qgs.eligible(soins, ctx(40, {"dps"}))
    assert qgs.eligible(degats, ctx(40))                       # débutant sans classe
    assert not qgs.eligible(degats, ctx(40, {"tank"}))


def test_trois_quetes_d_objectifs_differents_une_par_difficulte():
    quests = qgs.pick(daily_templates(), ctx(30, {"dps"}), 3, random.Random(1))
    assert len(quests) == 3
    assert len({q.objective_type for q in quests}) == 3
    assert {q.tier for q in quests} == {"easy", "medium", "hard"}
    assert all("{" not in q.description and "{" not in q.name for q in quests)


ROLE_SETS = (set(), {"dps"}, {"tank"}, {"soutien"}, {"dps", "tank", "soutien"})


@pytest.mark.parametrize("level", (1, 5, 15, 30, 60, 100))
def test_une_quotidienne_se_fait_seul_en_une_journee(level):
    """Au plus ~6 victoires à son niveau, rien qui demande un groupe."""
    for template in daily_templates():
        assert template.objective_type not in ("group_kill", "hp_healed"), template.code
        assert template.quantity <= 8, template.code
        for roles in ROLE_SETS:
            if qgs.eligible(template, ctx(level, roles)):
                quest = qgs.concretize(template, ctx(level, roles))
                assert quest.quantity >= 1
    # Chaque profil a toujours ses trois quêtes.
    for roles in ROLE_SETS:
        assert len(qgs.pick(daily_templates(), ctx(level, roles, families=()), 3)) == 3


def test_l_hebdo_a_aussi_trois_quetes_pour_chacun():
    for roles in ROLE_SETS:
        assert len(qgs.pick(weekly_templates(), ctx(50, roles), 3)) == 3
