"""Le boss de la semaine suit le niveau des joueurs actifs (audit d'ouverture :
le Titan sortait 88 % des semaines, même contre des joueurs de niveau 100)."""

import random
from collections import Counter
from datetime import UTC, datetime
from types import SimpleNamespace

from app.domain.services import boss_selection_service as bs
from app.domain.services import pacing_service as ps
from app.domain.services.pacing_service import RaidPacing

BOSSES = [SimpleNamespace(code=code, level=level) for code, level in
          (("titan", 20), ("seigneur", 40), ("colosse", 60), ("spectre", 80), ("dragon", 100))]


def draws(levels: list[int], previous: str = "", n: int = 3000) -> Counter:
    rng = random.Random(4)
    return Counter(bs.pick(BOSSES, levels, rng, previous).code for _ in range(n))


def test_pas_de_raid_tant_qu_aucune_equipe_ne_peut_entamer_le_premier_boss():
    assert bs.pick(BOSSES, []) is None
    assert bs.pick(BOSSES, [14, 14, 14, 14, 30]) is None         # le 4e meilleur est à 14
    assert bs.pick(BOSSES, [15, 15, 15, 15]) is not None


def test_une_equipe_prete_lance_le_raid_meme_si_la_mediane_est_basse():
    levels = [30, 30, 30, 30, 2, 2, 2, 2, 2, 2]
    assert bs.server_level(levels) == 2 and bs.team_level(levels) == 30
    assert set(draws(levels)) == {"titan"}


def test_un_serveur_de_niveau_100_voit_surtout_les_gros_boss():
    counts = draws([100] * 10)
    assert counts.most_common(1)[0][0] == "dragon"
    assert counts["dragon"] > 0.6 * sum(counts.values()) and counts["titan"] < 0.03 * sum(counts.values())


def test_aucun_boss_hors_de_portee():
    assert set(draws([20] * 10)) == {"titan"}
    assert set(draws([36] * 10)) == {"titan", "seigneur"}
    assert "colosse" not in draws([50] * 10)


def test_jamais_deux_fois_de_suite_le_meme_quand_il_y_a_le_choix():
    assert "dragon" not in draws([100] * 10, previous="dragon")
    assert set(draws([20] * 10, previous="titan")) == {"titan"}     # pas le choix


def test_un_joueur_seul_compte_pour_equipe():
    assert bs.team_level([40]) == 40


def test_le_dernier_jour_du_raid_est_la_veille_de_l_arrivee():
    sunday = datetime(2026, 11, 8, 21, 0, tzinfo=ps.PARIS)
    assert ps.raid_ends_today(RaidPacing(), sunday)
    assert not ps.raid_ends_today(RaidPacing(), datetime(2026, 11, 7, 21, 0, tzinfo=ps.PARIS))
    assert ps.raid_ends_today(RaidPacing(spawn_weekday=3), datetime(2026, 11, 11, 21, 0, tzinfo=ps.PARIS))


def test_la_date_limite_est_l_arrivee_du_boss_suivant():
    monday = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
    assert ps.raid_deadline(RaidPacing(), monday) == datetime(2026, 11, 16, 13, 0, tzinfo=ps.PARIS)
    wednesday = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
    assert ps.raid_deadline(RaidPacing(), wednesday) == datetime(2026, 11, 16, 13, 0, tzinfo=ps.PARIS)
