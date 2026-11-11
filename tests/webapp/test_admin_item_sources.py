"""Page Objets du site : d'où vient chaque objet (11/11/2026, demande de
l'auteur : « dire plus simplement quel monstre drop quoi dès le visuel
global » et filtrer par famille de monstre)."""

from __future__ import annotations

from types import SimpleNamespace as NS

from webapp.admin import item_sources
from tests.webapp.test_admin_pages_smoke import client  # noqa: F401  (fixture)


def _mob(code, name, family, gear="", attack=10, max_hp=100, loot=None):
    return NS(code=code, name=name, family=family, gear_item_code=gear, attack=attack, max_hp=max_hp,
              loot_table=loot or [])


def _build(**extra):
    mobs = [_mob("gobelin_geant", "Gobelin géant", "gobelin", "tronc", attack=30, max_hp=900),
            _mob("gobelin", "Gobelin", "gobelin", "surin"),
            _mob("slime", "Slime", "slime", "perle", loot=[{"item_code": "potion_soin", "drop_rate": 0.1}]),
            _mob("ombre", "Ombre", "abyssal", "voile")]
    return item_sources.build(
        mobs=mobs,
        zones=[{"name": "Clairière", "rank": "F", "families": ["slime", "gobelin"]}],
        planned=[{"name": "Faille", "rank": "S", "families": ["abyssal"]}],
        family_drops={"gobelin": {"item_code": "dent", "mobs": {"gobelin": {"min": 1, "max": 1},
                                                               "gobelin_geant": {"min": 2, "max": 4}}}},
        item_names={"dent": "Dent", "gel": "Gelée"},
        recipes=[NS(item_code="potion_soin", ingredients=(("gel", 2),))],
        **extra)


def test_chaque_objet_dit_quel_monstre_le_lache():
    src = _build()
    assert [s["text"] for s in src.by_item["surin"]] == ["Porté par Gobelin"]
    assert "Clairière · rang F" in src.by_item["surin"][0]["detail"]
    dent = src.by_item["dent"][0]
    assert dent["text"] == "Tous les gobelins" and dent["detail"].startswith("1 à 4 par victoire")
    # Butin d'un monstre, puis la recette d'Elna : les monstres d'abord.
    assert [s["kind"] for s in src.by_item["potion_soin"]] == ["butin", "elna"]
    assert "10 % par victoire" in src.by_item["potion_soin"][0]["detail"]
    assert "2 Gelée" in src.by_item["potion_soin"][1]["detail"]
    # Une zone pas encore ouverte le dit.
    assert "pas encore ouverte" in src.by_item["voile"][0]["detail"]


def test_le_filtre_range_une_famille_du_plus_faible_au_plus_fort():
    src = _build()
    assert [f["code"] for f in src.families] == ["slime", "gobelin", "abyssal"]
    assert src.families[2]["planned"] is True
    order = sorted(["dent", "surin", "tronc"], key=lambda code: src.order[code]["gobelin"])
    assert order == ["dent", "surin", "tronc"]          # matériau, Gobelin, puis Gobelin géant
    assert src.families_of("potion_soin") == ["slime"]
    assert "gobelin" in src.search_text("surin").lower()


def test_les_fetes_disent_d_ou_viennent_leurs_objets():
    src = _build(seasonal={
        "drops": [{"item": "sucre", "per_kill": 1, "start": "2026-12-18", "end": "2026-12-24", "enabled": True}],
        "shops": [{"name": "L'atelier des lutins", "emoji": "🎁", "currency": "sucre", "opens": "2026-12-25",
                   "closes": "2026-12-31", "offers": [{"item": "cadre_houx", "price": 80}]}],
        "advent": {"days": [[{"kind": "item", "item": "dent", "qty": 3}], [{"kind": "gold", "amount": 5}]]},
        "christmas": {"rewards": [{"kind": "item", "item": "booster", "qty": 3}]},
    })
    assert "du 18/12 au 24/12" in src.by_item["sucre"][0]["detail"]
    assert src.by_item["cadre_houx"][0]["text"] == "L'atelier des lutins"
    assert [s["kind"] for s in src.by_item["dent"]] == ["famille", "avent"]
    noel = src.by_item["booster"][0]
    assert noel["text"] == "Cadeau de Noël" and "petite fille" not in noel["detail"] + noel["tip"]


def test_la_page_objets_montre_les_sources_et_le_filtre(client):
    r = client.get("/admin/items")
    assert r.status_code == 200
    assert "Famille de monstre" in r.text and 'value="__aucun__"' in r.text
    assert "Porté par" in r.text and "data-families=" in r.text
