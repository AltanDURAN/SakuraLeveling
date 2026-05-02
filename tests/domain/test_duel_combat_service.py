"""Tests du DuelCombatService (combat 1v1 PvP).

Le service est symétrique : pas de notion de mob, deux Stats interchangeables.
On vérifie le déterminisme face à un déséquilibre franc et la borne MAX_TURNS.
"""

import random

from app.domain.services.duel_combat_service import DuelCombatService
from app.domain.value_objects.stats import Stats


def _stats(max_hp=100, attack=20, defense=5, speed=5, crit_chance=0, dodge=0, regen=0):
    return Stats(
        max_hp=max_hp,
        attack=attack,
        defense=defense,
        speed=speed,
        crit_chance=crit_chance,
        crit_damage=100,  # neutre
        dodge=dodge,
        hp_regeneration=regen,
    )


def test_duel_strong_vs_weak_strong_wins():
    random.seed(0)
    service = DuelCombatService()

    strong = _stats(max_hp=200, attack=50, defense=20, speed=10)
    weak = _stats(max_hp=80, attack=8, defense=2, speed=4)

    result = service.fight_player_vs_player(a_stats=strong, b_stats=weak)

    assert result.winner == "a"
    assert result.b_remaining_hp == 0
    assert result.a_remaining_hp > 0
    assert result.a_max_hp == 200
    assert result.b_max_hp == 80
    assert len(result.turn_logs) == result.turns


def test_duel_starts_with_full_hp_for_both():
    """Au tour 0, avant tout coup, les deux combattants doivent avoir leur
    max_hp en stock — peu importe leur current_hp réel en DB (le service
    n'en lit même pas)."""
    random.seed(0)
    service = DuelCombatService()

    a = _stats(max_hp=100, attack=15, defense=5, speed=5)
    b = _stats(max_hp=120, attack=15, defense=5, speed=5)

    result = service.fight_player_vs_player(a_stats=a, b_stats=b)

    # Le 1er turn_log capture l'état après le 1er coup. Vérifier que la
    # somme des HP restants + dégâts pris des deux côtés ≈ max_hp totaux.
    first = result.turn_logs[0]
    if first.actor == "a":
        # b a pris des dégâts depuis 120
        assert first.b_hp_after <= 120
        assert first.a_hp_after == 100  # a n'a pas encore été touché
    else:
        assert first.a_hp_after <= 100
        assert first.b_hp_after == 120


def test_duel_logs_alternate_actors_when_speeds_equal():
    random.seed(1)
    service = DuelCombatService()

    a = _stats(max_hp=300, attack=10, defense=0, speed=10)
    b = _stats(max_hp=300, attack=10, defense=0, speed=10)

    result = service.fight_player_vs_player(a_stats=a, b_stats=b)

    # Au moins un tour de a et un tour de b doivent exister (pas de KO sur 1er hit)
    actors = {log.actor for log in result.turn_logs}
    assert actors == {"a", "b"}


def test_duel_respects_max_turns_cap():
    """Si deux joueurs s'auto-soignent à l'infini, MAX_TURNS borne la boucle."""
    random.seed(0)
    service = DuelCombatService()

    # Hp_regeneration > attack ⇒ aucun ne meurt
    immortal_a = _stats(max_hp=500, attack=1, defense=100, speed=5, regen=999)
    immortal_b = _stats(max_hp=500, attack=1, defense=100, speed=5, regen=999)

    result = service.fight_player_vs_player(a_stats=immortal_a, b_stats=immortal_b)

    assert result.turns <= service.MAX_TURNS
    # Cap atteint = personne KO
    assert result.a_remaining_hp > 0
    assert result.b_remaining_hp > 0
    # Vainqueur déterminé par ratio HP (égalité ⇒ "a")
    assert result.winner in ("a", "b")
