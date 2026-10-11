"""Builder d'arbre : validation et aller-retour du format v2.

L'arbre est DESSINÉ par l'auteur du jeu. Deux choses doivent être sûres : on
ne doit jamais pouvoir enregistrer un arbre injouable, et ce qu'on enregistre
doit être relu à l'identique par le moteur.
"""

import pytest

from app.infrastructure.skill_tree.skill_tree_loader import parse_definition
from webapp.admin.routers.skill_builder_router import coverage, validate


def _tree(**overrides):
    base = {
        "roots": ["r"],
        "nodes": {
            "r": {"name": "Racine", "start": True, "max_level": 1, "costs": [0],
                  "effects": [], "position": {"x": 0, "y": 0}},
            "a": {"name": "A", "max_level": 2, "costs": [1, 2],
                  "effects": [{"type": "atk_percent", "values": [3, 6]}],
                  "position": {"x": 0, "y": -95}},
        },
        "links": [{"from": "r", "to": "a", "type": "simple"}],
    }
    base.update(overrides)
    return base


# ------------------------------------------------------------ validation --
def test_un_arbre_coherent_passe():
    assert validate(_tree()) == []


def test_un_arbre_sans_racine_est_refuse():
    """Sans racine, personne ne pourrait commencer à investir."""
    problems = validate(_tree(roots=[]))
    assert any("racine" in p for p in problems)


def test_le_nombre_de_couts_doit_suivre_le_nombre_de_niveaux():
    t = _tree()
    t["nodes"]["a"]["costs"] = [1]
    assert any("coût" in p for p in validate(t))


def test_les_valeurs_d_effet_doivent_suivre_le_nombre_de_niveaux():
    t = _tree()
    t["nodes"]["a"]["effects"][0]["values"] = [3]
    assert any("valeur" in p for p in validate(t))


def test_un_noeud_relie_a_rien_est_signale():
    """Un nœud inatteignable est du contenu mort."""
    t = _tree()
    t["nodes"]["orphelin"] = {
        "name": "Orphelin", "max_level": 1, "costs": [1], "effects": [],
        "position": {"x": 300, "y": 0},
    }
    assert any("inatteignable" in p for p in validate(t))


def test_un_lien_vers_un_noeud_inexistant_est_signale():
    t = _tree()
    t["links"].append({"from": "a", "to": "fantome", "type": "simple"})
    assert any("orphelin" in p for p in validate(t))


# -------------------------------------------------------------- lecture --
def test_le_format_du_builder_est_relu_par_le_moteur():
    d = parse_definition(_tree())
    assert set(d.skills) == {"r", "a"}
    assert d.all_roots == ["r"]
    # Un lien EST un prérequis : c'est ce que le moteur de déblocage lit.
    assert d.skills["a"].prerequisites == ["r"]


def test_un_arbre_v1_reste_lisible_et_ses_liens_sont_deduits():
    """Rétrocompatibilité : un arbre écrit avant le builder doit s'ouvrir."""
    v1 = {
        "root": "racine",
        "skills": {
            "racine": {"name": "R", "max_level": 1, "costs": [0], "effects": [],
                       "prerequisites": [], "position": {"x": 0, "y": 0}},
            "fils": {"name": "F", "max_level": 1, "costs": [1], "effects": [],
                     "prerequisites": ["racine"], "position": {"x": 0, "y": -95}},
        },
    }
    d = parse_definition(v1)
    assert d.all_roots == ["racine"]
    assert [(l.source, l.target) for l in d.links] == [("racine", "fils")]


def test_plusieurs_prerequis_sont_conserves():
    """Une classe exige d'avoir monté DEUX voies au maximum."""
    t = _tree()
    t["nodes"]["b"] = {"name": "B", "max_level": 1, "costs": [1], "effects": [],
                       "position": {"x": 95, "y": 0}}
    t["nodes"]["classe"] = {"name": "Classe", "max_level": 1, "costs": [2],
                            "effects": [], "position": {"x": 48, "y": -48}}
    t["links"] += [{"from": "r", "to": "b"},
                   {"from": "a", "to": "classe"}, {"from": "b", "to": "classe"}]
    assert validate(t) == []
    d = parse_definition(t)
    assert sorted(d.skills["classe"].prerequisites) == ["a", "b"]


# ----------------------------------------------------------- couverture --
def test_la_couverture_totalise_la_derniere_valeur_de_chaque_noeud():
    """Les valeurs sont cumulatives : le total d'un nœud est sa DERNIÈRE."""
    rows = {r["type"]: r["total"] for r in coverage(_tree())}
    assert rows["atk_percent"] == 6


def test_la_couverture_expose_les_trous():
    """Une stat secondaire à zéro = une stat que personne n'aura jamais,
    puisque l'arbre en est la seule source."""
    rows = {r["type"]: r["total"] for r in coverage(_tree())}
    assert rows["crit_chance_flat"] == 0
    assert "dodge_flat" in rows


def test_le_squelette_livre_est_valide():
    """Le squelette de départ doit s'ouvrir et s'enregistrer sans erreur."""
    import json
    from app.infrastructure.skill_tree.skill_tree_loader import content_path

    raw = json.loads(content_path().read_text(encoding="utf-8"))
    assert validate(raw) == []
    d = parse_definition(raw)
    assert len(d.all_roots) >= 1
