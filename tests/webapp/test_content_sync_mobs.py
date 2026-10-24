"""mobs.json écrit par l'admin : les champs que le formulaire ignore survivent,
et supprimer une pièce la retire des monstres qui la portaient."""

from webapp.admin import content_sync


def _store(monkeypatch, files):
    monkeypatch.setattr(content_sync.json_writer, "load_json",
                        lambda name, default=None: files.get(name, default))
    monkeypatch.setattr(content_sync.json_writer, "atomic_write_json",
                        lambda name, data: files.__setitem__(name, data))


def test_editer_un_monstre_garde_sa_piece(monkeypatch):
    files = {"mobs.json": [{"code": "gobelin", "name": "Gobelin", "gear_item_code": "surin_dentele",
                            "future_field": 1}]}
    _store(monkeypatch, files)
    content_sync.upsert_mob_json({"code": "gobelin", "name": "Gobelin vert"})
    mob = files["mobs.json"][0]
    assert mob["name"] == "Gobelin vert"
    assert mob["gear_item_code"] == "surin_dentele" and mob["future_field"] == 1


def test_build_mob_dict_porte_la_piece():
    stats = dict(max_hp=1, current_hp=1, attack=1, defense=1, crit_chance=0, crit_damage=100,
                 dodge=0, hp_regeneration=0, speed=5, xp_reward=1, gold_reward=1, spawn_weight=1)
    d = content_sync.build_mob_dict(code="x", name="X", family="f", description="",
                                    loot_table=[], image_name="", element="",
                                    gear_item_code="surin_dentele", **stats)
    assert d["gear_item_code"] == "surin_dentele"


def test_supprimer_une_piece_la_retire_des_monstres(monkeypatch):
    files = {"items.json": [{"code": "surin_dentele"}],
             "mobs.json": [{"code": "gobelin", "gear_item_code": "surin_dentele", "loot_table": []}]}
    _store(monkeypatch, files)
    touched = content_sync.delete_item_json("surin_dentele")
    assert files["mobs.json"][0]["gear_item_code"] == "" and "mobs.json" in touched
