"""Convertit l'équipement du format PLAT vers le format POURCENTAGE (saison 1).

Les anciennes valeurs (`{"attack": 12}`) étaient calibrées pour un socle
CONSTANT. Les reporter telles quelles n'aurait aucun sens : on les
**re-dérive** à partir de la rareté, en conservant la FORME de chaque pièce
(un objet défensif reste défensif, un objet offensif reste offensif).

Budget retenu : un équipement complet de 7 pièces d'une rareté donnée double
à peu près les stats du joueur au palier correspondant.

    commune      → +8 %      niveau 1 requis
    peu commune  → +12 %     niveau 10
    rare         → +18 %     niveau 25
    épique       → +25 %     niveau 45
    légendaire   → +35 %     niveau 70

Les stats SECONDAIRES (crit, esquive, vitesse, régénérations, mana) restent en
valeurs plates : elles n'ont jamais été des pourcentages du socle.

Usage : .venv/bin/python -m scripts.migrate_items_to_percent [--write]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.shared.enums import EQUIPABLE_CATEGORIES

CONTENT = Path(__file__).resolve().parents[1] / "app/infrastructure/content/items.json"

#: rareté → (budget total de pourcentage, niveau requis)
RARITY_BUDGET: dict[str, tuple[int, int]] = {
    "common": (8, 1),
    "uncommon": (12, 10),
    "rare": (18, 25),
    "epic": (25, 45),
    "legendary": (35, 70),
}

#: Stats plates de l'ancien format → clé de pourcentage correspondante.
STRUCTURAL = {"attack": "attack_pct", "defense": "defense_pct", "max_hp": "max_hp_pct"}

#: Poids relatif pour comparer des stats plates entre elles (1 DEF ≈ 25 PV,
#: cf. le power score). Sert UNIQUEMENT à retrouver la forme de la pièce.
SHAPE_WEIGHT = {"attack": 1.0, "defense": 1.0, "max_hp": 0.04}

#: Stats secondaires conservées telles quelles.
FLAT_KEEP = (
    "speed", "crit_chance", "crit_damage", "dodge",
    "hp_regeneration", "mana_max", "mana_regeneration",
)


def convert(item: dict) -> dict | None:
    """Renvoie les nouveaux `stat_bonuses`, ou None si l'item n'est pas équipable."""
    if item.get("category") not in EQUIPABLE_CATEGORIES:
        return None

    old = item.get("stat_bonuses") or {}
    budget, _ = RARITY_BUDGET.get(item.get("rarity", "common"), RARITY_BUDGET["common"])

    # Forme de la pièce : poids signé de chaque stat structurelle.
    raw = {
        key: float(old.get(key, 0) or 0) * SHAPE_WEIGHT[key] for key in STRUCTURAL
    }
    gains = {k: v for k, v in raw.items() if v > 0}
    malus = {k: -v for k, v in raw.items() if v < 0}
    total_gain = sum(gains.values())
    total_malus = sum(malus.values())

    new: dict = {}
    if total_gain > 0:
        for key, weight in gains.items():
            value = round(budget * weight / total_gain)
            if value > 0:
                new[STRUCTURAL[key]] = value
        # L'arrondi peut tout annihiler sur une pièce très déséquilibrée :
        # on garantit au moins un point sur la stat dominante.
        if not new:
            dominant = max(gains, key=lambda k: gains[k])
            new[STRUCTURAL[dominant]] = max(1, budget // 2)

    # Les MALUS font partie du design (l'espadon lourd coûte de la défense) :
    # on les reporte en pourcentages négatifs, plafonnés à un tiers du budget
    # pour que la pièce reste nettement gagnante.
    if total_malus > 0:
        malus_budget = max(1, round(budget / 3))
        for key, weight in malus.items():
            value = round(malus_budget * weight / total_malus)
            if value > 0:
                new[STRUCTURAL[key]] = new.get(STRUCTURAL[key], 0) - value

    for key in FLAT_KEEP:
        flat_value = old.get(key)
        if flat_value:
            new[key] = flat_value

    return new


def main() -> None:
    write = "--write" in sys.argv
    items = json.loads(CONTENT.read_text(encoding="utf-8"))

    touched = 0
    print(f"{'objet':<36} {'rareté':<11} {'avant':<28} {'après':<30} niv.")
    for item in items:
        new_bonuses = convert(item)
        if new_bonuses is None:
            continue
        _, level = RARITY_BUDGET.get(
            item.get("rarity", "common"), RARITY_BUDGET["common"],
        )
        before = json.dumps(item.get("stat_bonuses") or {}, ensure_ascii=False)
        after = json.dumps(new_bonuses, ensure_ascii=False)
        print(
            f"  {item['code'][:34]:<34} {item.get('rarity',''):<11} "
            f"{before[:26]:<28} {after[:28]:<30} {level}"
        )
        item["stat_bonuses"] = new_bonuses
        item["level_requirement"] = level
        touched += 1

    # Les non-équipables ont un niveau requis de 1 par convention.
    for item in items:
        item.setdefault("level_requirement", 1)

    print(f"\n{touched} pièces d'équipement converties sur {len(items)} items.")
    if write:
        CONTENT.write_text(
            json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        print(f"✅ écrit dans {CONTENT}")
    else:
        print("(dry-run — relancer avec --write pour appliquer)")


if __name__ == "__main__":
    main()
