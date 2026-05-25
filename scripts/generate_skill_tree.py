"""Génère app/infrastructure/content/skill_tree.json selon le modèle V2.

Modèle (cf. discussion d'équilibrage) :
- 3 branches depuis le centre : Attaque / Défense / Utilitaire.
- Chaîne unique stricte : on prend les nœuds dans l'ordre (un nœud doit être
  maxé pour débloquer le suivant). Le build = comment on répartit ses points
  entre les 3 branches et jusqu'où on descend.
- Un anneau = 5 nœuds SIMPLES (1 pt × 3 niveaux, stats plates) + 1 nœud
  SPÉCIAL (3 pts × 1 niveau, %/crit/vitesse/…). Ratio 5:1.
- Effet des nœuds simples légèrement croissant en s'éloignant du centre (ramp).
- Nœuds plats = moteur infini (atk_flat/def_flat/hp_max_flat). % = plafonnés
  en aval (aggregate_bonuses). Vitesse = FINIE (front-loadée).

Pour étendre l'arbre plus tard : augmenter ANNEAUX et relancer le script.
Régénère : .venv/bin/python scripts/generate_skill_tree.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

ANNEAUX = 8          # anneaux par branche (≈ niveau 144 pour un mono-branche)
SIMPLE_PER_RING = 5
OUT = Path(__file__).resolve().parents[1] / "app/infrastructure/content/skill_tree.json"

# Combien de nœuds "vitesse" au total (FINIE — sinon stunlock). Au-delà, le
# slot spécial vitesse de la branche attaque devient crit_damage (tail-safe).
SPEED_NODES_MAX = 6


def simple_values(base: int, ramp: int, anneau: int) -> list[int]:
    """Valeurs cumulatives [v, 2v, 3v] d'un nœud simple, rampées par anneau."""
    v = base + ramp * (anneau - 1)
    return [v, 2 * v, 3 * v]


# Définition des branches : (préfixe, nom, icône racine, angle°,
#   cycle de simples [(effect, base, ramp, icon)], cycle de spéciaux).
BRANCHES = {
    "atq": {
        "name": "Voie de l'Attaque",
        "root_icon": "⚔️",
        "angle": 270,  # vers le haut
        "simples": [("atk_flat", 5, 1, "⚔️", "Force")],
        "speciaux": [
            ("atk_percent", 1, "💥", "Frappe affûtée"),
            ("crit_chance_flat", 1, "🎯", "Œil vif"),
            ("speed_flat", 1, "💨", "Célérité"),
            ("crit_damage_flat", 5, "🔥", "Coup dévastateur"),
        ],
    },
    "def": {
        "name": "Voie de la Défense",
        "root_icon": "🛡️",
        "angle": 30,  # bas-droite
        "simples": [
            ("hp_max_flat", 100, 20, "❤️", "Vitalité"),
            ("def_flat", 5, 1, "🛡️", "Armure"),
        ],
        "speciaux": [
            ("def_percent", 1, "🪨", "Peau de pierre"),
            ("hp_max_percent", 1, "💗", "Endurance"),
            ("dodge_flat", 1, "🌀", "Esquive"),
            ("hp_regeneration_flat", 1, "💚", "Régénération"),
        ],
    },
    "uti": {
        "name": "Voie Utilitaire",
        "root_icon": "🎒",
        "angle": 150,  # bas-gauche
        "simples": [
            ("gold_drop_percent", 1, 0, "💰", "Bourse"),
            ("xp_drop_percent", 1, 0, "✨", "Sagesse"),
            ("drop_rate_multiplier", 1, 0, "🎁", "Chance"),
        ],
        "speciaux": [
            ("gold_drop_percent", 2, "💰", "Fortune"),
            ("xp_drop_percent", 2, "✨", "Érudition"),
            ("drop_rate_multiplier", 2, "🎁", "Pillage"),
        ],
    },
}


def build() -> dict:
    skills: dict[str, dict] = {}

    # Centre
    skills["aventurier"] = {
        "name": "Aventurier",
        "description": "Le commencement de votre voyage. Les trois voies partent d'ici.",
        "icon": "⭐",
        "max_level": 1,
        "costs": [0],
        "effects": [],
        "prerequisites": [],
        "position": {"x": 0, "y": 0},
    }

    for prefix, cfg in BRANCHES.items():
        angle = math.radians(cfg["angle"])
        dx, dy = math.cos(angle), math.sin(angle)
        simples = cfg["simples"]
        speciaux = cfg["speciaux"]

        # Racine de branche (passerelle)
        root_code = f"voie_{prefix}"
        skills[root_code] = {
            "name": cfg["name"],
            "description": f"Entrée de la {cfg['name'].lower()}.",
            "icon": cfg["root_icon"],
            "max_level": 1,
            "costs": [1],
            "effects": [],
            "prerequisites": ["aventurier"],
            "position": {"x": round(140 * dx), "y": round(140 * dy)},
        }

        prev = root_code
        seq = 0
        speed_count = 0
        for anneau in range(1, ANNEAUX + 1):
            # 5 simples
            for n in range(SIMPLE_PER_RING):
                effect, base, ramp, icon, label = simples[(anneau * SIMPLE_PER_RING + n) % len(simples)]
                seq += 1
                code = f"{prefix}_{seq}"
                radius = 140 + seq * 78
                skills[code] = {
                    "name": f"{label} {anneau}",
                    "description": f"+{base + ramp*(anneau-1)} par niveau (cumulatif, max 3).",
                    "icon": icon,
                    "max_level": 3,
                    "costs": [1, 1, 1],
                    "effects": [{"type": effect, "values": simple_values(base, ramp, anneau)}],
                    "prerequisites": [prev],
                    "position": {"x": round(radius * dx), "y": round(radius * dy)},
                }
                prev = code

            # 1 spécial
            spec = speciaux[(anneau - 1) % len(speciaux)]
            effect, val, icon, label = spec
            # Vitesse FINIE : au-delà du quota, on bascule sur crit_damage (attaque)
            if effect == "speed_flat":
                if speed_count >= SPEED_NODES_MAX:
                    effect, val, icon, label = "crit_damage_flat", 5, "🔥", "Coup dévastateur"
                else:
                    speed_count += 1
            seq += 1
            code = f"{prefix}_{seq}"
            radius = 140 + seq * 78
            skills[code] = {
                "name": label,
                "description": f"Nœud spécial : +{val} {effect.replace('_', ' ')} (1 amélioration).",
                "icon": icon,
                "max_level": 1,
                "costs": [3],
                "effects": [{"type": effect, "values": [val]}],
                "prerequisites": [prev],
                "position": {"x": round(radius * dx), "y": round(radius * dy)},
            }
            prev = code

    return {"root": "aventurier", "skills": skills}


def main() -> None:
    tree = build()
    OUT.write_text(json.dumps(tree, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✅ {OUT} — {len(tree['skills'])} nœuds ({ANNEAUX} anneaux × 3 branches)")


if __name__ == "__main__":
    main()
