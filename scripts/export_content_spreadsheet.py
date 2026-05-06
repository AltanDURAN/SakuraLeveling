"""Génère un tableur XLSX consolidant tout le contenu du jeu.

Une feuille par type :
    - Mobs (avec power score et rang calculés)
    - Une feuille par catégorie d'item (Armes, Casques, Plastrons, …)
    - Crafts (recettes)
    - Shop (prix d'achat / vente)
    - Classes
    - Skill Tree (nœuds)
    - World Bosses

Format XLSX = importable directement dans Google Sheets (Fichier > Importer).
Lancement :
    .venv/bin/python scripts/export_content_spreadsheet.py
Sortie :
    docs/sakura_content.xlsx
"""

from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.domain.entities.mob_definition import MobDefinition
from app.domain.services.power_score_service import PowerScoreService
from datetime import UTC, datetime


ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = ROOT / "app" / "infrastructure" / "content"
OUTPUT = ROOT / "docs" / "sakura_content.xlsx"


HEADER_FILL = PatternFill(start_color="2E7D32", end_color="2E7D32", fill_type="solid")
HEADER_FONT = Font(bold=True, color="FFFFFF")
ZEBRA_FILL = PatternFill(start_color="F1F8E9", end_color="F1F8E9", fill_type="solid")


# Mapping catégorie d'item → label de feuille FR + emoji.
ITEM_CATEGORY_SHEETS = [
    ("weapon", "⚔️ Armes"),
    ("shield", "🛡️ Boucliers"),
    ("helmet", "🪖 Casques"),
    ("chest", "🥋 Plastrons"),
    ("legs", "👖 Jambières"),
    ("boots", "🥾 Bottes"),
    ("necklace", "📿 Colliers"),
    ("bracelet", "🪢 Bracelets"),
    ("ring", "💍 Bagues"),
    ("belt", "🧵 Ceintures"),
    ("cape", "🧥 Capes"),
    ("earring", "🦻 Boucles d'oreilles"),
    ("consumable", "🧪 Consommables"),
    ("resource", "📦 Ressources"),
]


def _load(name: str):
    return json.loads((CONTENT_DIR / name).read_text(encoding="utf-8"))


def _autosize(ws, max_width: int = 40) -> None:
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        longest = max((len(str(c.value)) for c in col if c.value is not None), default=10)
        ws.column_dimensions[col_letter].width = min(max(longest + 2, 10), max_width)


def _apply_header_style(ws, row: int = 1) -> None:
    for cell in ws[row]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")


def _zebra(ws, header_row: int = 1) -> None:
    for idx, row in enumerate(ws.iter_rows(min_row=header_row + 1), start=header_row + 1):
        if idx % 2 == 0:
            for cell in row:
                cell.fill = ZEBRA_FILL


def write_mobs_sheet(wb: Workbook) -> None:
    mobs = _load("mobs.json")
    ws = wb.create_sheet("👹 Mobs")
    headers = [
        "Code", "Nom", "Famille",
        "PV max", "Atk", "Def", "Vit", "Crit %", "Crit dmg %", "Esquive %", "Regen",
        "XP récomp.", "Or récomp.", "Poids spawn",
        "Power score", "Rang",
        "Drops", "Image", "Description",
    ]
    ws.append(headers)
    _apply_header_style(ws)

    pss = PowerScoreService()
    now = datetime.now(UTC)
    for mob in mobs:
        # Construire un MobDefinition pour réutiliser le calcul de score
        mob_def = MobDefinition(
            id=0,
            code=mob["code"],
            name=mob["name"],
            description=mob.get("description", ""),
            image_name=mob.get("image_name", ""),
            family=mob.get("family", ""),
            max_hp=mob["max_hp"],
            current_hp=mob.get("current_hp", mob["max_hp"]),
            attack=mob["attack"],
            defense=mob["defense"],
            speed=mob["speed"],
            crit_chance=mob["crit_chance"],
            crit_damage=mob["crit_damage"],
            dodge=mob["dodge"],
            hp_regeneration=mob.get("hp_regeneration", 0),
            xp_reward=mob.get("xp_reward", 0),
            gold_reward=mob.get("gold_reward", 0),
            spawn_weight=mob.get("spawn_weight", 1),
            loot_table=mob.get("loot_table"),
            created_at=now,
            updated_at=now,
        )
        score = pss.calculate_from_mob(mob_def)
        rank = pss.compute_rank(score)

        drops_str = "\n".join(
            f"{d['item_code']} ×{d.get('min_quantity',1)}-{d.get('max_quantity',1)} ({int(float(d['drop_rate'])*100)}%)"
            for d in (mob.get("loot_table") or [])
        )

        ws.append([
            mob["code"], mob["name"], mob.get("family", ""),
            mob["max_hp"], mob["attack"], mob["defense"], mob["speed"],
            mob["crit_chance"], mob["crit_damage"], mob["dodge"],
            mob.get("hp_regeneration", 0),
            mob.get("xp_reward", 0), mob.get("gold_reward", 0),
            mob.get("spawn_weight", 1),
            score, rank,
            drops_str, mob.get("image_name", ""), mob.get("description", ""),
        ])
    # Wrap les lignes drops/description
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            if isinstance(cell.value, str) and "\n" in cell.value:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
    _autosize(ws, max_width=50)
    _zebra(ws)
    ws.freeze_panes = "C2"


def write_item_sheets(wb: Workbook) -> None:
    items = _load("items.json")
    by_cat: dict[str, list] = {}
    for item in items:
        by_cat.setdefault(item.get("category", "?"), []).append(item)

    for category, sheet_label in ITEM_CATEGORY_SHEETS:
        rows = by_cat.get(category, [])
        if not rows:
            continue

        ws = wb.create_sheet(sheet_label)

        if category == "consumable":
            ws.append([
                "Code", "Nom", "Rareté", "Effet", "Valeur",
                "Prix vente", "Prix achat", "Description",
            ])
            _apply_header_style(ws)
            for it in rows:
                bonuses = it.get("stat_bonuses") or {}
                ws.append([
                    it["code"], it["name"], it.get("rarity", "—"),
                    bonuses.get("effect", ""), bonuses.get("value", ""),
                    it.get("sell_price") or 0, it.get("buy_price") or 0,
                    it.get("description", ""),
                ])
        elif category == "resource":
            ws.append([
                "Code", "Nom", "Rareté", "Stackable", "Stack max",
                "Prix vente", "Prix achat", "Description",
            ])
            _apply_header_style(ws)
            for it in rows:
                ws.append([
                    it["code"], it["name"], it.get("rarity", "—"),
                    "oui" if it.get("stackable") else "non",
                    it.get("max_stack") or "∞",
                    it.get("sell_price") or 0, it.get("buy_price") or 0,
                    it.get("description", ""),
                ])
        else:
            # Tous les équipements : même schéma
            ws.append([
                "Code", "Nom", "Rareté", "Slot", "2-mains",
                "Atk +", "Def +", "PV +", "Crit chance +", "Crit dmg +",
                "Esquive +", "Vitesse +", "Regen +",
                "Prix vente", "Prix achat", "Description",
            ])
            _apply_header_style(ws)
            for it in rows:
                b = it.get("stat_bonuses") or {}
                ws.append([
                    it["code"], it["name"], it.get("rarity", "—"),
                    it.get("equipment_slot") or "—",
                    "oui" if it.get("requires_two_hands") else "non",
                    b.get("attack", 0), b.get("defense", 0), b.get("max_hp", 0),
                    b.get("crit_chance", 0), b.get("crit_damage", 0),
                    b.get("dodge", 0), b.get("speed", 0), b.get("hp_regeneration", 0),
                    it.get("sell_price") or 0, it.get("buy_price") or 0,
                    it.get("description", ""),
                ])

        _autosize(ws, max_width=40)
        _zebra(ws)
        ws.freeze_panes = "C2"


def write_crafts_sheet(wb: Workbook) -> None:
    crafts = _load("crafts.json")
    items = {i["code"]: i for i in _load("items.json")}
    ws = wb.create_sheet("🛠️ Recettes")
    ws.append([
        "Code recette", "Nom", "Résultat (item)", "Catégorie résultat",
        "Slot résultat", "Quantité produite", "Ingrédients",
    ])
    _apply_header_style(ws)
    for r in crafts:
        result = items.get(r["result_item_code"])
        category = result.get("category", "?") if result else "?"
        slot = (result.get("equipment_slot") or "—") if result else "—"
        ingr_lines = "\n".join(
            f"{ing['item_code']} ×{ing['quantity']}" for ing in r.get("ingredients", [])
        )
        ws.append([
            r["code"], r["name"], r["result_item_code"], category, slot,
            r.get("result_quantity", 1), ingr_lines,
        ])
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            if isinstance(cell.value, str) and "\n" in cell.value:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
    _autosize(ws, max_width=45)
    _zebra(ws)
    ws.freeze_panes = "B2"


def write_shop_sheet(wb: Workbook) -> None:
    try:
        shop = _load("shop_items.json")
    except FileNotFoundError:
        return
    items = {i["code"]: i for i in _load("items.json")}
    ws = wb.create_sheet("🏪 Shop")
    ws.append([
        "Code item", "Nom", "Catégorie",
        "Prix achat (joueur paye)",
        "Prix vente max (stock vide)",
        "Prix vente min (stock saturé)",
        "Seuil stock", "Activé",
    ])
    _apply_header_style(ws)
    for entry in shop:
        item = items.get(entry["item_code"])
        ws.append([
            entry["item_code"],
            (item or {}).get("name", "?"),
            (item or {}).get("category", "?"),
            entry.get("buy_price", 0),
            entry.get("max_sell_price", 0),
            entry.get("min_sell_price", 0),
            entry.get("stock_threshold", 0),
            "oui" if entry.get("enabled", True) else "non",
        ])
    _autosize(ws)
    _zebra(ws)
    ws.freeze_panes = "B2"


def write_classes_sheet(wb: Workbook) -> None:
    classes = _load("classes.json")
    ws = wb.create_sheet("🧬 Classes")
    ws.append([
        "Code", "Nom",
        "Atk +", "Def +", "PV +", "Crit chance +", "Crit dmg +",
        "Esquive +", "Vitesse +", "Regen +",
        "Conditions de déblocage", "Description",
    ])
    _apply_header_style(ws)
    for c in classes:
        b = c.get("stat_bonuses") or {}
        reqs = []
        for r in c.get("unlock_requirements", []):
            t = r.get("type", "?")
            if t == "profession_level":
                reqs.append(f"métier {r.get('profession_code')} niv. {r.get('level')}")
            elif t == "item":
                reqs.append(f"item {r.get('item_code')}")
            else:
                reqs.append(json.dumps(r, ensure_ascii=False))
        ws.append([
            c["code"], c["name"],
            b.get("attack", 0), b.get("defense", 0), b.get("max_hp", 0),
            b.get("crit_chance", 0), b.get("crit_damage", 0),
            b.get("dodge", 0), b.get("speed", 0), b.get("hp_regeneration", 0),
            "\n".join(reqs) or "aucune",
            c.get("description", ""),
        ])
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            if isinstance(cell.value, str) and "\n" in cell.value:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
    _autosize(ws, max_width=50)
    _zebra(ws)


def write_skill_tree_sheet(wb: Workbook) -> None:
    try:
        tree = _load("skill_tree.json")
    except FileNotFoundError:
        return
    skills = tree.get("skills", {})
    ws = wb.create_sheet("🌳 Skill Tree")
    ws.append([
        "Code", "Nom", "Niveau max", "Coûts par niveau",
        "Effets", "Prérequis", "Position (x,y)", "Icône", "Description",
    ])
    _apply_header_style(ws)
    for code, node in skills.items():
        effects_lines = []
        for e in node.get("effects", []):
            vals = ",".join(str(v) for v in e.get("values", []))
            effects_lines.append(f"{e.get('type','?')} → [{vals}]")
        ws.append([
            code,
            node.get("name", ""),
            node.get("max_level", 0),
            ",".join(str(c) for c in node.get("costs", [])),
            "\n".join(effects_lines) or "—",
            ", ".join(node.get("prerequisites", [])) or "racine",
            f"{node.get('position', {}).get('x', 0)}, {node.get('position', {}).get('y', 0)}",
            node.get("icon", ""),
            node.get("description", ""),
        ])
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            if isinstance(cell.value, str) and "\n" in cell.value:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
    _autosize(ws, max_width=50)
    _zebra(ws)
    ws.freeze_panes = "B2"


def write_world_bosses_sheet(wb: Workbook) -> None:
    try:
        bosses = _load("boss_definitions.json")
    except FileNotFoundError:
        return
    ws = wb.create_sheet("🐉 World Bosses")
    ws.append([
        "Code", "Nom", "Famille",
        "PV max", "Atk", "Def", "Vit", "Crit %", "Crit dmg %", "Esquive %",
        "Modifiers", "Poids spawn", "Lore",
    ])
    _apply_header_style(ws)
    for b in bosses:
        modifiers = b.get("modifiers") or {}
        mod_str = "\n".join(f"{k} = {v}" for k, v in modifiers.items()) or "—"
        ws.append([
            b["code"], b["name"], b.get("family", ""),
            b["max_hp"], b["attack"], b["defense"], b["speed"],
            b["crit_chance"], b["crit_damage"], b["dodge"],
            mod_str,
            b.get("spawn_weight", 1),
            b.get("description", "")[:300],
        ])
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            if isinstance(cell.value, str) and "\n" in cell.value:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
    _autosize(ws, max_width=50)
    _zebra(ws)


def write_summary_sheet(wb: Workbook) -> None:
    """Première feuille : sommaire et notes générales."""
    ws = wb.create_sheet("📋 Sommaire", 0)
    ws.append(["Sakura Leveling V2 — Récap du contenu"])
    ws["A1"].font = Font(bold=True, size=16)
    ws.append([f"Généré le {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}"])
    ws.append([])
    ws.append(["Feuille", "Contenu"])
    _apply_header_style(ws, row=4)
    ws.append(["👹 Mobs", "Tous les monstres avec stats, drops, power score et rang calculés"])
    ws.append(["⚔️ Armes / 🛡️ Boucliers / 🪖 Casques / …", "Une feuille par catégorie d'équipement"])
    ws.append(["🧪 Consommables", "Potions et autres consommables (+ effet)"])
    ws.append(["📦 Ressources", "Ressources brutes (loot, craft inputs)"])
    ws.append(["🛠️ Recettes", "Toutes les recettes /craft et /forge"])
    ws.append(["🏪 Shop", "Prix d'achat et vente min/max du shop"])
    ws.append(["🧬 Classes", "Classes joueur, bonus, conditions de déblocage"])
    ws.append(["🌳 Skill Tree", "Tous les nœuds de l'arbre de compétences"])
    ws.append(["🐉 World Bosses", "Bosses du JSON, avec modifiers"])
    ws.append([])
    ws.append(["Notes :"])
    ws.append(["• Conventions des stats : voir CLAUDE.md (crit_chance/dodge en 0..100, crit_damage en 100=neutre)."])
    ws.append(["• Les rangs sont calculés via PowerScoreService.compute_rank, paliers stricts F- → SSS+."])
    ws.append(["• Pour mettre à jour ce fichier : .venv/bin/python scripts/export_content_spreadsheet.py"])
    _autosize(ws, max_width=80)


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    # On retire la feuille par défaut "Sheet"
    default_sheet = wb.active
    wb.remove(default_sheet)

    write_mobs_sheet(wb)
    write_item_sheets(wb)
    write_crafts_sheet(wb)
    write_shop_sheet(wb)
    write_classes_sheet(wb)
    write_skill_tree_sheet(wb)
    write_world_bosses_sheet(wb)
    write_summary_sheet(wb)  # ajouté en premier via index=0

    wb.save(OUTPUT)
    print(f"✅ Tableur généré : {OUTPUT}")
    print(f"   {len(wb.sheetnames)} feuilles : {', '.join(wb.sheetnames)}")


if __name__ == "__main__":
    main()
