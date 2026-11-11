"""D'où vient un objet — pour la page Objets du site (11/11/2026, demande de
l'auteur : « dire plus simplement quel monstre drop quoi dès le visuel
global », et filtrer par famille de monstre).

Sources lues dans le CONTENU du jeu, jamais saisies à la main :
    • la pièce qu'un monstre PORTE (`mob_definitions.gear_item_code`) ;
    • le matériau de sa FAMILLE (`family_drops.json`, quantité par monstre) ;
    • le butin d'un monstre (`loot_table`) ou d'un world boss ;
    • les potions d'Elna (recettes d'`artisans.json`) et l'étal de Sorn.

`build(...)` est pur (données en entrée) ; `load(session, items)` va les
chercher. Chaque source dit sa famille de monstre (pour le filtre) et son
rang dans la famille (pour ranger les objets du plus faible au plus fort).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.services.gear_service import DROP_RATES_PCT
from app.domain.services.mob_ability_service import is_group_elite
from app.domain.services.quest_generation_service import FAMILY_LABELS
from app.shared.enums import ITEM_RARITY_LABELS

#: Ordre d'une source dans sa famille : le matériau d'abord, puis les monstres.
_MATERIAL_ORDER = 0


@dataclass
class ItemSources:
    by_item: dict[str, list[dict]] = field(default_factory=dict)
    #: Familles proposées au filtre, de la première zone à la dernière.
    families: list[dict] = field(default_factory=list)
    #: item → {famille: ordre} (matériau, puis pièces du monstre le plus faible au plus fort).
    order: dict[str, dict[str, int]] = field(default_factory=dict)

    def families_of(self, code: str) -> list[str]:
        return sorted({s["family"] for s in self.by_item.get(code, []) if s.get("family")})

    def search_text(self, code: str) -> str:
        return " ".join(f"{s['text']} {s.get('family_label', '')}" for s in self.by_item.get(code, []))


def family_label(family: str) -> str:
    """« gobelins », « morts-vivants » (pluriel du jeu), sinon le code."""
    return FAMILY_LABELS.get(family, family.replace("_", " "))


def _gear_odds() -> str:
    total = sum(DROP_RATES_PCT.values())
    detail = " · ".join(f"{ITEM_RARITY_LABELS.get(r, r)} {pct:g} %" for r, pct in DROP_RATES_PCT.items())
    return f"≈ {total:.1f} % par victoire ({detail})"


def _qty(lo: int, hi: int) -> str:
    return f"{lo}" if lo == hi else f"{lo} à {hi}"


def build(*, mobs: list, zones: list[dict], planned: list[dict], family_drops: dict,
          item_names: dict[str, str], recipes: list = (), shop: list = (), bosses: list = (),
          seasonal: dict | None = None) -> ItemSources:
    out = ItemSources()

    # Familles, dans l'ordre des zones (F → S), puis celles hors zone.
    where: dict[str, dict] = {}
    for zone, is_planned in [(z, False) for z in zones] + [(z, True) for z in planned]:
        for fam in zone.get("families") or []:
            where.setdefault(fam, {"zone": zone.get("name", ""), "rank": zone.get("rank", ""), "planned": is_planned})
    for mob in mobs:
        if mob.family and mob.family not in where:
            where[mob.family] = {"zone": "", "rank": "", "planned": False}

    def place(fam: str) -> str:
        w = where.get(fam) or {}
        bits = [w.get("zone", "")]
        if w.get("rank"):
            bits.append(f"rang {w['rank']}")
        if w.get("planned"):
            bits.append("pas encore ouverte")
        return " · ".join(b for b in bits if b)

    out.families = [{"code": f, "label": family_label(f).capitalize(), "place": place(f),
                     "planned": bool(where[f].get("planned"))} for f in where]

    # Dans une famille, du monstre le plus faible au plus fort (ATK × PV).
    by_family: dict[str, list] = {}
    for mob in mobs:
        by_family.setdefault(mob.family, []).append(mob)
    rank_in_family: dict[str, int] = {}
    for fam, members in by_family.items():
        for i, mob in enumerate(sorted(members, key=lambda m: (m.attack * m.max_hp, m.code)), start=1):
            rank_in_family[mob.code] = i

    def add(code: str, source: dict, order: int | None = None) -> None:
        if not code:
            return
        out.by_item.setdefault(code, []).append(source)
        fam = source.get("family")
        if fam and order is not None:
            current = out.order.setdefault(code, {}).get(fam)
            out.order[code][fam] = order if current is None else min(current, order)

    odds = _gear_odds()
    for mob in mobs:
        fam = mob.family or ""
        elite = is_group_elite(mob.code)
        common = {"family": fam, "family_label": family_label(fam), "mob": mob.name, "place": place(fam)}
        add(getattr(mob, "gear_item_code", "") or "",
            {**common, "kind": "porte", "icon": "⭐" if elite else "👹",
             "text": f"Porté par {mob.name}" + (" (élite de groupe)" if elite else ""),
             "detail": place(fam), "tip": f"La pièce que porte ce monstre : {odds}."},
            rank_in_family.get(mob.code, 99))
        for entry in mob.loot_table or []:
            rate = float(entry.get("drop_rate", 0) or 0) * 100
            lo, hi = int(entry.get("min_quantity", 1) or 1), int(entry.get("max_quantity", 1) or 1)
            add(entry.get("item_code", ""),
                {**common, "kind": "butin", "icon": "🎲",
                 "text": f"Butin de {mob.name}", "detail": f"{rate:g} % par victoire, ×{_qty(lo, hi)} · {place(fam)}",
                 "tip": "Tiré à chaque victoire, pour chaque survivant."},
                50 + rank_in_family.get(mob.code, 0))

    for fam, cfg in (family_drops or {}).items():
        if not isinstance(cfg, dict) or not cfg.get("item_code"):
            continue
        ranges = [(int(v.get("min", 1)), int(v.get("max", 1))) for v in (cfg.get("mobs") or {}).values()
                  if isinstance(v, dict)]
        lo = min((r[0] for r in ranges), default=1)
        hi = max((r[1] for r in ranges), default=1)
        add(cfg["item_code"],
            {"kind": "famille", "icon": "🧺", "family": fam, "family_label": family_label(fam), "place": place(fam),
             "text": f"Tous les {family_label(fam)}", "detail": f"{_qty(lo, hi)} par victoire · {place(fam)}",
             "tip": "Matériau de famille : chaque monstre de la famille en lâche, plus il est fort, plus il en donne "
                    "(fusion chez Borak, potions chez Elna)."},
            _MATERIAL_ORDER)

    for boss in bosses:
        for entry in getattr(boss, "loot_table", None) or []:
            rate = float(entry.get("drop_rate", 0) or 0) * 100
            add(entry.get("item_code", ""),
                {"kind": "boss", "icon": "🐉", "family": "", "text": f"Butin du world boss {boss.name}",
                 "detail": f"{rate:g} % par participant", "tip": "Tiré pour chaque participant à sa défaite."})

    for recipe in recipes:
        parts = ", ".join(f"{qty} {item_names.get(code, code)}" for code, qty in recipe.ingredients)
        add(recipe.item_code,
            {"kind": "elna", "icon": "⚗️", "family": "", "text": "Préparée par Elna",
             "detail": parts, "tip": "Recette de l'alchimiste (/alchimiste) : ces ingrédients + de l'or."})

    for entry in shop:
        per_level = int(getattr(entry, "price_per_level", 0) or 0)
        price = (f"{per_level} or × niveau" if per_level
                 else f"{int(entry.buy_price):,} or".replace(",", " ") if getattr(entry, "buy_price", 0) else "")
        add(entry.item_definition.code,
            {"kind": "sorn", "icon": "🏪", "family": "", "text": "Vendu par Sorn", "detail": price,
             "tip": "À l'étal du marchand (/marchand)."})

    _seasonal(add, seasonal or {}, item_names)

    # Les monstres d'abord (ce que l'auteur cherche), puis Elna, Sorn et les fêtes.
    rank = {"famille": 0, "porte": 1, "butin": 2, "boss": 3, "fete": 4, "elna": 5, "sorn": 6, "avent": 7, "noel": 8}
    for sources in out.by_item.values():
        sources.sort(key=lambda s: rank.get(s["kind"], 9))
    return out


def _day(iso: str) -> str:
    """« 2026-12-18 » → « 18/12 »."""
    parts = str(iso or "").split("-")
    return f"{parts[2]}/{parts[1]}" if len(parts) == 3 else str(iso or "")


def _seasonal(add, data: dict, item_names: dict[str, str]) -> None:
    """Fêtes (seasonal_events.json) : objets lâchés par les monstres pendant
    l'événement, boutiques d'événement, calendrier de l'Avent, cadeau de Noël."""
    for drop in data.get("drops") or []:
        if isinstance(drop, dict) and drop.get("enabled", True):
            add(drop.get("item", ""),
                {"kind": "fete", "icon": "🍬", "family": "", "text": "Tous les monstres de zone",
                 "detail": f"{drop.get('per_kill', 1)} par victoire, du {_day(drop.get('start'))} au {_day(drop.get('end'))}",
                 "tip": drop.get("name", "Objet d'événement")})
    for shop in data.get("shops") or []:
        if not isinstance(shop, dict) or not shop.get("enabled", True):
            continue
        currency = item_names.get(shop.get("currency", ""), shop.get("currency", ""))
        for offer in shop.get("offers") or []:
            add(offer.get("item", ""),
                {"kind": "fete", "icon": shop.get("emoji") or "🎁", "family": "", "text": shop.get("name", "Boutique"),
                 "detail": f"{offer.get('price', '?')} {currency} · du {_day(shop.get('opens'))} au {_day(shop.get('closes'))}",
                 "tip": "Boutique d'événement (/evenement)."})
    advent = data.get("advent") or {}
    if advent.get("enabled", True):
        days: dict[str, list[int]] = {}
        for number, rewards in enumerate(advent.get("days") or [], start=1):
            for reward in rewards or []:
                if isinstance(reward, dict) and reward.get("kind") == "item":
                    days.setdefault(reward.get("item", ""), []).append(number)
        for code, numbers in days.items():
            add(code, {"kind": "avent", "icon": "🎄", "family": "", "text": advent.get("name", "Calendrier de l'Avent"),
                       "detail": "case " + ", ".join(str(n) for n in numbers) if len(numbers) == 1
                       else "cases " + ", ".join(str(n) for n in numbers),
                       "tip": "Une case par jour de décembre (/evenement)."})
    christmas = data.get("christmas") or {}
    if christmas.get("enabled", True):
        for reward in christmas.get("rewards") or []:
            if isinstance(reward, dict) and reward.get("kind") == "item":
                add(reward.get("item", ""),
                    {"kind": "noel", "icon": "🎅", "family": "", "text": "Cadeau de Noël",
                     "detail": f"×{reward.get('qty', 1)} de base",
                     "tip": "Cadeau à ouvrir du 25 au 31 décembre."})


def load(session, item_names: dict[str, str]) -> ItemSources:
    """Les sources de tous les objets, lues dans le jeu (base + contenu)."""
    from app.infrastructure.artisans.artisan_loader import get_alchemist
    from app.infrastructure.db.repositories.mob_repository import MobRepository
    from app.infrastructure.db.repositories.shop_repository import ShopRepository
    from app.infrastructure.encounters import farm_zone_loader
    from app.infrastructure.loot.family_drop_loader import get_family_drops
    from app.infrastructure.seasonal import seasonal_loader
    from app.infrastructure.world_boss.boss_definition_loader import list_definitions

    def safe(fn, default):
        try:
            return fn()
        except Exception:  # noqa: BLE001 — une source illisible n'empêche pas la page
            return default

    return build(
        mobs=safe(lambda: MobRepository(session).list_all(), []),
        zones=safe(farm_zone_loader.list_zones, []),
        planned=safe(farm_zone_loader.planned_zones, []),
        family_drops=safe(get_family_drops, {}),
        item_names=item_names,
        recipes=safe(lambda: list(get_alchemist().recipes), []),
        shop=safe(lambda: ShopRepository(session).list_all(only_enabled=True), []),
        bosses=safe(list_definitions, []),
        seasonal=safe(seasonal_loader.raw, {}),
    )
