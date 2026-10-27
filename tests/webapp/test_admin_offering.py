"""Admin web : offrande commune — formule, prix de la jauge en cours et
divinités réglables depuis le site (demande de l'auteur, 27/10/2026), sur une
copie du contenu."""

import json

import pytest

from app.application.use_cases import offering
from app.domain.services import offering_service as osvc
from app.infrastructure.db.session import get_db_session
from app.infrastructure.offering import offering_loader
from tests.webapp.test_admin_content_crud import _same_origin, content  # noqa: F401  (fixtures)
from tests.webapp.test_admin_pages_smoke import client  # noqa: F401  (fixture)


@pytest.fixture
def offering_copy(content, monkeypatch):
    monkeypatch.setattr(offering_loader, "CONTENT_PATH", content / "offering.json")
    offering_loader.clear_cache()
    yield content / "offering.json"
    offering_loader.clear_cache()


def _saved(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_la_page_s_affiche(client, offering_copy):
    r = client.get("/admin/offering")
    assert r.status_code == 200 and "Formule du prix" in r.text and "Kaïros" in r.text


def test_regler_la_formule(client, offering_copy):
    form = {"base_target": "2000", "step_per_fill": "50", "growth_pct": "3,5", "decay_pct": "4",
            "blessing_hours": "12"}
    assert client.post("/admin/offering/params", data=form, follow_redirects=False).status_code == 303
    assert _saved(offering_copy)["params"] == {"base_target": 2000, "step_per_fill": 50, "growth_pct": 3.5,
                                               "decay_pct": 4.0, "blessing_hours": 12}
    assert offering_loader.get_params() == osvc.OfferingParams(2000, 50, 3.5, 4.0, 12)
    bad = {**form, "decay_pct": "100"}
    assert client.post("/admin/offering/params", data=bad).status_code == 400
    assert _saved(offering_copy)["params"]["decay_pct"] == 4.0          # rien n'a été écrit


def test_corriger_le_prix_de_la_jauge_en_cours(client, offering_copy):
    assert client.post("/admin/offering/gauge", data={"target": "9000"}, follow_redirects=False).status_code == 303
    with get_db_session() as session:
        assert offering.status(session).target == 9000
    assert client.post("/admin/offering/gauge", data={"target": "0"}).status_code == 400


def test_ajouter_modifier_retirer_une_divinite(client, offering_copy):
    new = {"emoji": "⚡", "name": "Zéphyr", "title": "souffle des cimes", "effect": "xp_pct", "value": "5",
           "blessing": ""}
    assert client.post("/admin/offering/deities", data=new, follow_redirects=False).status_code == 303
    zephyr = offering_loader.get_deity("zephyr")
    assert zephyr is not None and zephyr.value == 5 and "5 % d'XP" in zephyr.blessing
    assert client.post("/admin/offering/deities", data=new).status_code == 400            # code déjà pris
    edit = {**new, "effect": "material_bonus", "value": "2", "blessing": "+2 matériaux"}
    assert client.post("/admin/offering/deities/zephyr", data=edit, follow_redirects=False).status_code == 303
    assert offering_loader.get_deity("zephyr").effect == "material_bonus"
    assert client.post("/admin/offering/deities/zephyr", data={**edit, "effect": "gold_pct"}).status_code == 400
    assert client.post("/admin/offering/deities/zephyr/delete", follow_redirects=False).status_code == 303
    assert offering_loader.get_deity("zephyr") is None
