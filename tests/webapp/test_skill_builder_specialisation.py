"""Builder : les règles de spécialisation survivent à l'aller-retour et sont
validées à l'enregistrement."""

from app.infrastructure.skill_tree.skill_tree_loader import get_definition
from webapp.admin.routers.skill_builder_router import _serialise, validate


def test_le_builder_transporte_les_regles_de_specialisation():
    payload = _serialise(get_definition())
    assassin = payload["nodes"]["passif_25"]
    assert assassin["exclusive_group"] == "spécialisation"
    assert assassin["voie_requirement"] == {"voie": "voie_attaque", "points": 27}
    assert validate(payload) == []


def test_seuil_de_voie_incomplet_refuse():
    payload = _serialise(get_definition())
    payload["nodes"]["passif_25"]["voie_requirement"] = {"voie": "voie_attaque", "points": 0}
    assert any("seuil de voie incomplet" in p for p in validate(payload))
    payload["nodes"]["passif_25"]["voie_requirement"] = {"voie": "inconnue", "points": 5}
    assert any("voie inconnue" in p for p in validate(payload))
