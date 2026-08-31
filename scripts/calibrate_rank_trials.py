"""Calibre les GARDIENS des épreuves de rang par simulation.

Même méthode que `restat_bosses` : on ne devine pas les statistiques, on les
mesure avec le vrai moteur de combat.

Pour chaque rang visé (E → SSS) :
  1. on construit le joueur de référence qui vient TOUT JUSTE d'atteindre le
     seuil de power score de ce rang (recherche dichotomique sur un profil de
     stats équilibré) ;
  2. on fixe la DÉFENSE du gardien à 35 % de l'attaque de ce joueur — la
     règle du projet : la défense d'un adversaire ne doit jamais approcher
     l'attaque du joueur, sinon les dégâts tombent au plancher de 1 ;
  3. on cherche les PV du gardien qui donnent le TAUX DE VICTOIRE visé.

L'épreuve doit se gagner, mais de justesse : un joueur qui vient de franchir
le seuil doit passer environ deux fois sur trois.

Usage : .venv/bin/python -m scripts.calibrate_rank_trials [--write]
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from app.domain.entities.mob_definition import MobDefinition
from app.domain.services.party_combat_service import PartyCombatService
from app.domain.services.power_score_service import PowerScoreService
from app.domain.value_objects.stats import Stats

CONTENT = (
    Path(__file__).resolve().parents[1]
    / "app/infrastructure/content/rank_trials.json"
)

# Rang visé → seuil de power score qui ouvre l'épreuve (entrée du palier,
# c'est-à-dire la variante « - » dans PowerScoreService).
RANK_GATES: dict[str, int] = {
    "E": 1_125,
    "D": 2_450,
    "C": 4_300,
    "B": 6_600,
    "A": 9_500,
    "S": 12_600,
    "SS": 36_000,
    "SSS": 292_000,
}

GUARDIANS: dict[str, tuple[str, str]] = {
    "E": ("Sentinelle Ébréchée", "Une armure vide qui refuse de tomber."),
    "D": ("Veilleur de Cendres", "Il garde la porte depuis que la cendre est chaude."),
    "C": ("Colosse d'Ossements", "Chaque os qu'il porte fut un candidat."),
    "B": ("Héraut du Silence", "Il ne parle pas. Il n'a jamais eu besoin."),
    "A": ("Juge de Fer", "Il pèse ta force et rend son verdict en coups."),
    "S": ("Archonte Déchu", "Il a tenu ce rang. Il te fera mériter le tien."),
    "SS": ("Effigie du Vide", "Ce qui reste quand un rang a été arraché."),
    "SSS": ("Le Dernier Gardien", "Au-delà, il n'y a plus personne pour t'arrêter."),
}

DEF_RATIO = 0.35          # DEF gardien = 35 % de l'ATK du joueur de référence
ATK_RATIO = 0.55          # ATK gardien = 55 % de l'ATK du joueur
TARGET_WIN_RATE = 0.65    # l'épreuve se gagne, mais de justesse
SIMULATIONS = 400
MAX_TURNS = 60


def _reference_stats(k: float) -> Stats:
    """Profil de joueur équilibré paramétré par un scalaire de puissance."""
    return Stats(
        max_hp=int(100 + 12 * k),
        attack=int(10 + 4 * k),
        defense=int(5 + 1.5 * k),
        speed=int(5 + k / 10),
        crit_chance=min(75.0, 5 + k / 4),
        crit_damage=150.0,
        dodge=min(30.0, k / 5),
        hp_regeneration=0,
        mana_max=100,
        mana_regeneration=0,
    )


def _player_for_score(target: int) -> Stats:
    """Dichotomie : le joueur qui atteint tout juste ce power score."""
    power = PowerScoreService()
    lo, hi = 0.0, 5000.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if power.calculate_from_stats(_reference_stats(mid)) < target:
            lo = mid
        else:
            hi = mid
    return _reference_stats(hi)


def _guardian(name: str, hp: int, attack: int, defense: int) -> MobDefinition:
    from datetime import datetime, UTC

    now = datetime.now(UTC)
    return MobDefinition(
        id=0, code="gardien", name=name, description="", image_name="",
        family="gardien", max_hp=hp, current_hp=hp, attack=attack,
        defense=defense, xp_reward=0, gold_reward=0, spawn_weight=0,
        speed=8, crit_chance=10, crit_damage=150, dodge=5, hp_regeneration=0,
        loot_table=None, created_at=now, updated_at=now, element="",
    )


def _win_rate(player: Stats, hp: int, attack: int, defense: int) -> float:
    """Taux de victoire mesuré sur N combats réels contre le gardien."""
    service = PartyCombatService()
    wins = 0
    for seed in range(SIMULATIONS):
        random.seed(seed)
        party = [{
            "player_id": 1, "user_id": 1, "name": "ref", "avatar_url": "",
            "stats": player, "current_hp": player.max_hp,
            "max_hp": player.max_hp, "current_mana": player.mana_max,
            "mana_max": player.mana_max,
        }]
        result = service.fight_party_vs_mob(
            party, _guardian("g", hp, attack, defense), max_turns=MAX_TURNS,
        )
        if result.victory:
            wins += 1
    return wins / SIMULATIONS


def calibrate(rank: str, gate: int) -> dict:
    player = _player_for_score(gate)
    defense = max(1, int(player.attack * DEF_RATIO))
    attack = max(player.defense + 5, int(player.attack * ATK_RATIO))

    # Dichotomie sur les PV : plus le gardien en a, moins on gagne souvent.
    lo, hi = 10, max(200, player.attack * 400)
    for _ in range(18):
        mid = (lo + hi) // 2
        if _win_rate(player, mid, attack, defense) > TARGET_WIN_RATE:
            lo = mid
        else:
            hi = mid
    hp = lo
    rate = _win_rate(player, hp, attack, defense)
    name, lore = GUARDIANS[rank]
    return {
        "rank": rank,
        "required_power": gate,
        "guardian": {
            "name": name, "lore": lore,
            "max_hp": hp, "attack": attack, "defense": defense,
            "speed": 8, "crit_chance": 10, "crit_damage": 150, "dodge": 5,
        },
        "_mesure": {
            "joueur_ref_atk": player.attack,
            "joueur_ref_def": player.defense,
            "joueur_ref_pv": player.max_hp,
            "taux_victoire": round(rate, 3),
        },
    }


def main() -> None:
    write = "--write" in sys.argv
    trials = []
    print(f"{'rang':<5} {'seuil':>8} {'PV gardien':>11} {'ATK':>5} {'DEF':>5} "
          f"{'ATK joueur':>11} {'victoire':>9}")
    for rank, gate in RANK_GATES.items():
        entry = calibrate(rank, gate)
        m = entry["_mesure"]
        g = entry["guardian"]
        print(f"{rank:<5} {gate:>8} {g['max_hp']:>11} {g['attack']:>5} "
              f"{g['defense']:>5} {m['joueur_ref_atk']:>11} "
              f"{m['taux_victoire']*100:>8.0f}%")
        trials.append(entry)

    if write:
        payload = {
            "_comment": (
                "Épreuves de rang. `required_power` ouvre l'épreuve ; le gardien "
                "est calibré par simulation (scripts/calibrate_rank_trials.py) "
                "pour un taux de victoire d'environ 65 % chez un joueur qui vient "
                "d'atteindre le seuil. `retry_cooldown_hours` = attente après un "
                "échec."
            ),
            "retry_cooldown_hours": 6,
            "trials": trials,
        }
        CONTENT.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"\n✅ écrit dans {CONTENT}")
    else:
        print("\n(dry-run — relancer avec --write pour appliquer)")


if __name__ == "__main__":
    main()
