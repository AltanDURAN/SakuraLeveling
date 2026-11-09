"""Records du serveur (07/11/2026) : qui détient quoi, qui a les titres, ce
qui a changé dans la nuit, et les exploits d'un combat."""

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.domain.services import records_service as rs

T0 = datetime(2026, 11, 7, 12, 0)


def _e(player, value, minutes=0, detail=""):
    return rs.Entry(player, value, T0 + timedelta(minutes=minutes), detail)


def test_battre_un_record_c_est_faire_strictement_mieux():
    assert rs.holder([_e(1, 50, 0), _e(2, 50, 5)]).player_id == 1          # égalité : le premier arrivé
    assert rs.holder([_e(1, 50, 0), _e(2, 51, 5)]).player_id == 2
    assert rs.holder([_e(1, 0)]) is None and rs.holder([]) is None


def test_les_titres_vont_a_qui_detient_le_plus_de_records():
    held = {"a": _e(1, 9, 0), "b": _e(1, 9, 1), "c": _e(2, 9, 30), "d": _e(3, 9, 10), "e": _e(4, 9, 5)}
    standings = rs.ranking(held)
    # 1 a deux records ; 2, 3 et 4 en ont un : le record le plus récent passe devant.
    assert [s.player_id for s in standings] == [1, 2, 3, 4]
    assert rs.title_awards(standings) == {"records_1": 1, "records_2": 2, "records_3": 3}
    assert rs.title_awards(standings[:1]) == {"records_1": 1, "records_2": None, "records_3": None}


def test_ce_qui_change_dans_la_nuit():
    coup, chasse = rs.EXPLOITS[0], rs.hunt_record("slime", "slimes")
    before = {"coup": _e(1, 100), "chasse_slime": _e(2, 40)}
    after = {"coup": _e(1, 120), "chasse_slime": _e(2, 55)}
    moved = rs.changes([coup, chasse], before, after)
    assert [(c.record.code, c.taken) for c in moved] == [("coup", False)]   # la chasse grossit tous les jours
    after["chasse_slime"] = _e(3, 60)
    moved = rs.changes([coup, chasse], before, after)
    assert [(c.record.code, c.taken, c.old.player_id) for c in moved][-1] == ("chasse_slime", True, 2)
    assert [c.old for c in rs.changes([coup], {}, after)] == [None]       # premier détenteur


def _log(*events):
    return SimpleNamespace(events=list(events))


def test_les_exploits_d_un_combat():
    logs = [
        _log({"kind": "crit", "target": "e0", "amount": 900, "source": "p1"},
             {"kind": "hit", "target": "e0", "amount": 400, "source": "p2"}),
        _log({"kind": "hit", "target": "p2", "amount": 700, "source": "e0"}),
        _log({"kind": "hit", "target": "p1", "amount": 5000, "source": "e0"},   # coup fatal : ne compte pas
             {"kind": "ko", "target": "p1"}),
        _log({"kind": "hit", "target": "p2", "amount": 9999, "source": "e0", "style": "reflect"}),
        _log({"kind": "heal", "target": "p1", "amount": 300, "source": "p2"},
             {"kind": "heal", "target": "p2", "amount": 800, "source": "p2"},  # sur soi : ne compte pas
             {"kind": "heal", "target": "e0", "amount": 50}),
    ]
    contributions = [SimpleNamespace(player_id=1, damage_dealt=900, damage_tanked=5000, hp_healed=0),
                     SimpleNamespace(player_id=2, damage_dealt=400, damage_tanked=700, hp_healed=300)]
    peaks = rs.fight_peaks(logs, contributions)
    assert peaks[1] == {"coup": 900, "degats_combat": 900, "encaisse_combat": 5000}
    assert peaks[2] == {"coup": 400, "coup_encaisse": 700, "soin": 300, "degats_combat": 400,
                        "encaisse_combat": 700, "soins_combat": 300}


def test_dix_neuf_records_aujourd_hui():
    """18 records au 07/11/2026, plus l'album le plus complet (cartes, 09/11/2026)."""
    families = [("slime", "slimes"), ("gobelin", "gobelins"), ("mort-vivant", "morts-vivants"), ("demoniaque", "démons"),
                ("primordial", "bêtes primordiales"), ("nocturne", "créatures nocturnes"), ("draconique", "dragons")]
    records = rs.all_records(families)
    assert len(records) == 19 and len({r.code for r in records}) == 19
    assert records[-1] == rs.ALBUM
    assert {r.category for r in records} == {code for code, _ in rs.CATEGORIES}
