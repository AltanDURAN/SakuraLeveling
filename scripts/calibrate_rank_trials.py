"""Calibre les épreuves de rang par simulation, avec le vrai moteur.

Depuis le 26/10/2026 (décision de l'auteur), l'épreuve reprend les trois
épreuves des défis (`role_trial_service.run_trial`) face au gardien, au NIVEAU
du rang : ⚔️ DPS (dégâts en 40 s), 🛡️ Tank (dégâts encaissés avant de tomber,
sans sort de soin), 💚 Soutien (PV soignés avant la chute de la recrue). Le
joueur choisit son rôle. ⚠️ Avant, il fallait abattre le gardien en 60
actions : une course aux dégâts — un pur soutien restait bloqué au rang D, un
pur tank au rang B (mesuré : 0 % ensuite).

Pour chaque rang visé (E → SSS) :
  1. le SEUIL de power score = la puissance du GÉNÉRALISTE au niveau du rang
     (`reference_roles.gate_power`, kit de soutien compris) — inchangé ;
  2. pour chaque rôle, le score requis = le PLUS BAS de ceux qu'atteignent,
     dans `TARGET_WIN_RATE` de leurs essais, le GÉNÉRALISTE au niveau du rang
     et le SPÉCIALISTE de ce rôle au niveau où il franchit le seuil. Les deux
     doivent pouvoir passer : calé sur le spécialiste seul, un généraliste
     échouait PARTOUT (0 %) ; sur le généraliste seul, un tank qui franchit le
     seuil dix niveaux plus tôt échouait son propre rôle ;
  3. un rôle que personne ne sait encore jouer à ce rang (score nul : pas de
     soin avant le Clerc) n'est pas proposé.

Mesuré le 26/10/2026 : chaque spécialiste réussit SON rôle (~100 %), le
généraliste 60-87 % en DPS, 72-85 % en soutien, 100 % en tank ; le soutien des
rangs E-D (qui ne soigne pas encore) passe par l'épreuve tank. Les scores
varient peu d'un essai à l'autre : c'est surtout le build qui décide.

Usage : .venv/bin/python -m scripts.calibrate_rank_trials [--write]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CONTENT = (
    Path(__file__).resolve().parents[1]
    / "app/infrastructure/content/rank_trials.json"
)

#: Rang visé → NIVEAU auquel un joueur équilibré l'obtient (celui du gardien,
#: de la recrue et du seuil de puissance).
RANK_LEVELS: dict[str, int] = {
    "E": 12, "D": 25, "C": 38, "B": 50,
    "A": 63, "S": 75, "SS": 88, "SSS": 100,
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

TARGET_WIN_RATE = 0.65    # l'épreuve se gagne, mais de justesse
SIMULATIONS = 200
#: Rôle d'épreuve → build de `reference_roles` qui le joue.
SPECIALIST: dict[str, str] = {"dps": "dps", "tank": "tank", "soutien": "support"}


def _roles():
    import importlib.util

    module = sys.modules.get("reference_roles")
    if module is None:
        spec = importlib.util.spec_from_file_location(
            "reference_roles", Path(__file__).resolve().parent / "reference_roles.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["reference_roles"] = module
        spec.loader.exec_module(module)
    return module


def _power(build) -> int:
    from app.domain.services.power_score_service import PowerScoreService

    return PowerScoreService().calculate_from_stats(build.stats, build.passives)


def gate_level(build_role: str, gate: int, fallback: int) -> int:
    """Premier niveau où ce build atteint le seuil de puissance."""
    roles = _roles()
    return next((lvl for lvl in range(1, 101) if _power(roles.build(build_role, lvl)) >= gate), fallback)


def trial_scores(build, role: str, level: int, n: int = SIMULATIONS) -> list[int]:
    """Scores de `n` essais de ce build à l'épreuve `role` du rang de ce niveau."""
    from app.domain.services.role_trial_service import VARIANTS, run_trial

    return sorted(
        run_trial(role, VARIANTS[role][0], player_id=1, name="p", stats=build.stats,
                  passives=build.passives, tactic=build.tactic, seed=seed, level=level).score
        for seed in range(n)
    )


def pass_rate(scores: list[int], threshold: int) -> float:
    return sum(1 for s in scores if threshold and s >= threshold) / max(1, len(scores))


def _quantile(scores: list[int]) -> int:
    """Score atteint dans TARGET_WIN_RATE des essais."""
    return scores[int(len(scores) * (1 - TARGET_WIN_RATE))]


BUILDS = ("dps", "tank", "support", "general")


def calibrate(rank: str, level: int) -> dict:
    roles = _roles()
    gate = roles.gate_power(level)
    at = {b: gate_level(b, gate, level) for b in BUILDS}
    at["general"] = level
    thresholds = {}
    for role, build_role in SPECIALIST.items():
        candidates = [q for q in (_quantile(trial_scores(roles.build("general", level), role, level)),
                                  _quantile(trial_scores(roles.build(build_role, at[build_role]), role, level)))
                      if q > 0]
        thresholds[role] = min(candidates) if candidates else 0
    measure = {
        b: {"niveau": at[b], **{role: round(pass_rate(trial_scores(roles.build(b, at[b]), role, level, 100),
                                                      thresholds[role]), 2) for role in SPECIALIST}}
        for b in BUILDS
    }
    name, lore = GUARDIANS[rank]
    return {
        "rank": rank, "required_power": gate, "level": level,
        "guardian": {"name": name, "lore": lore},
        "thresholds": thresholds, "_mesure": measure,
    }


def main() -> None:
    write = "--write" in sys.argv
    trials = []
    print(f"{'rang':<5} {'seuil':>7} {'niv':>4} | score requis dps / tank / soutien "
          f"| réussite (dps / tank / soutien) de chaque profil au niveau où il franchit le seuil")
    for rank, level in RANK_LEVELS.items():
        entry = calibrate(rank, level)
        t, m = entry["thresholds"], entry["_mesure"]
        cells = " | ".join(f"{b} niv {m[b]['niveau']}: " + "/".join(f"{m[b][r]:.0%}" for r in SPECIALIST)
                           for b in BUILDS)
        print(f"{rank:<5} {entry['required_power']:>7} {level:>4} | {t['dps']} / {t['tank']} / {t['soutien']} | {cells}")
        trials.append(entry)

    if write:
        payload = {
            "_comment": (
                "Épreuves de rang. `required_power` ouvre l'épreuve ; le joueur choisit "
                "son rôle et doit atteindre le score `thresholds[rôle]` face au gardien "
                "(mêmes épreuves que /defi, au niveau `level` du rang). Calibré par "
                "simulation (scripts/calibrate_rank_trials.py) : le spécialiste qui vient "
                "d'atteindre le seuil réussit environ deux fois sur trois. "
                "`retry_cooldown_hours` = attente après un échec."
            ),
            "retry_cooldown_hours": 6,
            "trials": trials,
        }
        CONTENT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\n✅ écrit dans {CONTENT}")
    else:
        print("\n(dry-run — relancer avec --write pour appliquer)")


if __name__ == "__main__":
    main()
