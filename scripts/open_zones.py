"""Ouvre une ou plusieurs zones prévues (C, B, A, S) — en UNE commande.

Usage :
    .venv/bin/python -m scripts.open_zones C=<id du salon> B=<id> A=<id>            # aperçu
    .venv/bin/python -m scripts.open_zones C=<id du salon> B=<id> A=<id> --write    # applique

Ce que fait `--write` (décidé avec l'auteur, 24/10 et 26/10/2026) :
  1. `farm_zones.json` : la zone prévue de chaque rang passe dans `zones`, avec
     son salon ; ses monstres se mettent à apparaître, ses familles entrent
     dans les bestiaires et les quêtes adaptées ;
  2. RECALAGE des familles existantes dans leur tranche (F 1–20, E 21–33,
     D 34–45 — `restat_mobs.ZONES_V2_LEVELS`) : il s'applique tout seul dès
     qu'une zone C → S est ouverte (`restat_mobs.zones_v2_open`) ;
  3. ÉLITES recalibrées sur le trio de leur nouveau niveau (`--calibrate-elites`,
     quelques minutes), `ELITE_MULT` réécrit dans restat_mobs.py, puis les
     stats de tous les monstres réécrites dans mobs.json ;
  4. `shop_items.json` : le cor de chasse de chaque zone ouverte s'active, et
     le prix de TOUS les cors = 3 × l'or de leur élite (le recalage le change).

Ensuite : tests, commit, déploiement (le seed applique monstres et prix ; les
articles de Sorn sont « gérés par le contenu »). Le décor de la zone se règle
depuis l'admin web (Zones). ⚠️ Un changement de zone ⇒ redémarrage du bot
(fait par le déploiement).
"""

from __future__ import annotations

import importlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "app/infrastructure/content"
RESTAT = ROOT / "scripts/restat_mobs.py"
HORN_PRICE_FACTOR = 3        # × l'or que l'élite donne au groupe : jamais rentable en or
HORN_ROUND = 50


def _read(name: str):
    return json.loads((CONTENT / name).read_text(encoding="utf-8"))


def _write(name: str, data) -> None:
    (CONTENT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> dict[str, int]:
    channels: dict[str, int] = {}
    for arg in argv:
        if "=" in arg:
            rank, _, channel = arg.partition("=")
            if not channel.isdigit():
                sys.exit(f"❌ {arg} : l'identifiant du salon doit être un nombre.")
            channels[rank.strip().upper()] = int(channel)
    if not channels:
        sys.exit(__doc__)
    return channels


def open_in_content(zones_data: dict, channels: dict[str, int]) -> list[str]:
    """Déplace les zones prévues de ces rangs dans `zones`. Renvoie leurs noms."""
    opened = []
    planned = zones_data.get("planned_zones") or []
    for rank, channel in channels.items():
        zone = next((z for z in planned if z.get("rank") == rank), None)
        if zone is None:
            sys.exit(f"❌ Aucune zone prévue de rang {rank} (déjà ouverte ?).")
        planned.remove(zone)
        zone["channel_id"] = channel
        zones_data["zones"].append(zone)
        opened.append(f"{zone['name']} (rang {rank}, salon {channel})")
    zones_data["planned_zones"] = planned
    return opened


def horn_prices(mobs: list[dict], zones: list[dict]) -> dict[str, int]:
    """Prix de chaque cor : 3 × l'or de l'élite de sa zone, arrondi."""
    from app.domain.services.mob_ability_service import GROUP_ELITES

    prices = {}
    for zone in zones:
        elites = [m for m in mobs if m["code"] in GROUP_ELITES and m.get("family") in zone["families"]]
        if elites and zone.get("rank"):
            gold = max(e["gold_reward"] for e in elites)
            prices[f"cor_chasse_{zone['rank'].lower()}"] = (
                round(HORN_PRICE_FACTOR * gold / HORN_ROUND) * HORN_ROUND)
    return prices


def write_elite_mult(mult: dict[str, tuple[float, float]]) -> None:
    text = RESTAT.read_text(encoding="utf-8")
    block = "ELITE_MULT: dict[str, tuple[float, float]] = {\n" + "".join(
        f'    "{code}": ({hp_x}, {atk_x}),\n' for code, (hp_x, atk_x) in mult.items()) + "}"
    text, count = re.subn(r"ELITE_MULT: dict\[str, tuple\[float, float\]\] = \{.*?\n\}", block, text,
                          count=1, flags=re.S)
    if count != 1:
        sys.exit("❌ Bloc ELITE_MULT introuvable dans restat_mobs.py.")
    RESTAT.write_text(text, encoding="utf-8")


def main() -> None:
    write = "--write" in sys.argv
    channels = parse_args([a for a in sys.argv[1:] if a != "--write"])
    zones_data = _read("farm_zones.json")
    opened = open_in_content(zones_data, channels)
    print("Zones à ouvrir :\n  " + "\n  ".join(opened))
    if not write:
        print("\n(aperçu — relancer avec --write pour appliquer ; le recalibrage des élites prend quelques minutes)")
        return

    _write("farm_zones.json", zones_data)
    print("✅ farm_zones.json : zones ouvertes")

    from scripts import restat_mobs
    restat_mobs = importlib.reload(restat_mobs)          # recalage : zones_v2_open() est vrai
    print("⏳ Recalibrage des élites sur le trio de leur niveau…")
    write_elite_mult(restat_mobs.calibrate_elites())
    restat_mobs = importlib.reload(restat_mobs)          # nouveaux ELITE_MULT
    mobs = restat_mobs.apply(write=True)
    print("✅ mobs.json : familles recalées, élites recalibrées")

    prices = horn_prices(mobs, zones_data["zones"])
    open_ranks = {z.get("rank") for z in zones_data["zones"]}
    shop = _read("shop_items.json")
    for entry in shop:
        if entry["item_code"] in prices:
            entry["buy_price"] = prices[entry["item_code"]]
            rank = entry["item_code"].rsplit("_", 1)[-1].upper()
            entry["enabled"] = rank in open_ranks
    _write("shop_items.json", shop)
    print("✅ shop_items.json : cors " + ", ".join(f"{c[-1].upper()} {p}" for c, p in prices.items()))
    print("\nEnsuite : pytest, commit, déploiement (seed + redémarrage du bot), décors depuis l'admin.")


if __name__ == "__main__":
    main()
