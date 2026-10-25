"""Recalcule les paliers des RANGS AFFICHÉS (F- → SSS+, puis Ω) sur la
puissance d'un joueur TYPIQUE (`reference_roles.typical_power`).

Règle (25/10/2026) : un sous-rang tous les 5 niveaux — F- au niveau 1, F au
niveau 6… S au niveau 96 —, donc un joueur typique de niveau 100 affiche S.
S+ et la queue (SS-, SS, SS+, SSS-, SSS, SSS+, puis Ω) récompensent ce qui va
AU-DELÀ du joueur typique du niveau maximum (raretés hautes, mythiques,
affinités…) ; leurs écarts gardent les rapports de l'ancienne table.

Usage : .venv/bin/python -m scripts.calibrate_power_ranks [--write]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "app/domain/services/power_score_service.py"

LABELS = ["F-", "F", "F+", "E-", "E", "E+", "D-", "D", "D+", "C-", "C", "C+",
          "B-", "B", "B+", "A-", "A", "A+", "S-", "S", "S+",
          "SS-", "SS", "SS+", "SSS-", "SSS", "SSS+"]
LEVEL_STEP = 5
#: Au-delà du joueur typique du niveau 100 : S+ commence à ×1,25, puis les
#: rapports de l'ancienne table (13,6 k → 21,7 k → 36 k → 64 k → 130 k →
#: 292 k → 650 k → 1,4 M) pour S+, SS-, SS, SS+, SSS-, SSS, SSS+ ; Ω au-delà.
TAIL_RATIOS = (1.25, 1.6, 1.66, 1.78, 2.03, 2.25, 2.23, 2.15)


def thresholds() -> list[tuple[int, str]]:
    """[(borne, rang)] : le rang s'applique tant que le score est < borne."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "reference_roles", Path(__file__).resolve().parent / "reference_roles.py")
    roles = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("reference_roles", roles)
    spec.loader.exec_module(roles)

    bounds: list[int] = []
    # Bornes des sous-rangs F- … S (le suivant commence au niveau 1 + 5·i).
    for i in range(1, LABELS.index("S") + 1):
        bounds.append(roles.typical_power(1 + LEVEL_STEP * i))
    value = roles.typical_power(100)
    for ratio in TAIL_RATIOS:
        value = value * ratio
        bounds.append(int(round(value, -2)) if value > 10_000 else round(value))
    # Strictement croissantes (les petites bornes du début peuvent coïncider).
    for i in range(1, len(bounds)):
        bounds[i] = max(bounds[i], bounds[i - 1] + 1)
    return list(zip(bounds, LABELS))


def main() -> None:
    table = thresholds()
    lines = []
    for i in range(0, len(table), 3):
        chunk = table[i:i + 3]
        lines.append("    " + " ".join(f'({b:_}, "{label}"),' for b, label in chunk))
    block = "_RANK_THRESHOLDS: list[tuple[int, str]] = [\n" + "\n".join(lines) + "\n]"
    print(block)
    if "--write" in sys.argv:
        source = TARGET.read_text(encoding="utf-8")
        new = re.sub(r"_RANK_THRESHOLDS: list\[tuple\[int, str\]\] = \[\n.*?\n\]", block, source,
                     count=1, flags=re.S)
        TARGET.write_text(new, encoding="utf-8")
        print(f"\n✅ écrit dans {TARGET}")


if __name__ == "__main__":
    main()
