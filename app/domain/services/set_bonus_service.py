"""Bonus de panoplie — SAISON 1 (octobre 2026), règle décidée avec l'auteur.

Plus de familles d'objets : la panoplie, c'est l'HARMONIE des raretés portées.

  • Paliers à 2 / 4 / 7 pièces (`TIERS`), ×1 / ×1,5 / ×3 du bonus simple.
  • Comptage CUMULATIF : une pièce compte pour sa rareté ET toutes les raretés
    en dessous. 5 rares + 1 épique + 1 légendaire = 7 « commun ou mieux »,
    7 « peu commun ou mieux », 7 « rare ou mieux », 2 « épique ou mieux »,
    1 « légendaire ». Chaque rareté atteint son propre palier, et les bonus
    s'additionnent. Améliorer une pièce ne peut donc JAMAIS faire baisser le
    bonus (avec des groupes stricts, 7 rares → 6 rares + 1 épique le divisait
    par deux).
  • Chaque rareté n'apporte que sa MARCHE (`RARITY_STEP`, l'écart entre son
    multiplicateur de stat principale et celui de la rareté du dessous) : un
    set d'une seule rareté vaut donc exactement « bonus simple × rareté ×
    palier » (7 légendaires en attaque : 2 % × 4 × 3 = +24 %).
  • Une pièce à DEUX MAINS compte pour 2 (une seule pièce à farmer et à
    fusionner pour deux places) — c'est aussi ce qui permet d'atteindre 7
    pièces avec elle.
  • UN SEUL type de bonus, choisi par le joueur (`/panoplie`) : tous les
    paliers atteints s'additionnent dans ce type.

Dérivé, jamais persisté (seul le TYPE choisi l'est : `players.panoplie_bonus`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.services.gear_service import RARITY_ORDER, rarity_index

#: (pièces minimum, multiplicateur du bonus simple), du plus haut au plus bas.
TIERS: tuple[tuple[int, float], ...] = ((7, 3.0), (4, 1.5), (2, 1.0))

#: Marche de chaque rareté (somme cumulée = multiplicateur de stat principale
#: de la rareté : 1 / 1,5 / 2 / 3 / 4 / 5,5).
RARITY_STEP: dict[str, float] = {
    "common": 1.0, "uncommon": 0.5, "rare": 0.5,
    "epic": 1.0, "legendary": 1.0, "mythic": 1.5,
}


@dataclass(frozen=True)
class PanoplieType:
    code: str
    label: str
    emoji: str
    #: Champ de `SetBonuses` alimenté.
    field: str
    #: Bonus SIMPLE (palier 2, en commun).
    base: float
    #: "%" (ATK/DEF/PV, en % du socle) ou "" (stat plate).
    unit: str


#: Ordre = ordre d'affichage. Ni vitesse (+1 = énorme), ni or / XP (économie).
PANOPLIE_TYPES: dict[str, PanoplieType] = {t.code: t for t in (
    PanoplieType("attack", "Attaque", "⚔️", "attack_percent", 2.0, "%"),
    PanoplieType("defense", "Défense", "🛡️", "defense_percent", 2.0, "%"),
    PanoplieType("max_hp", "PV", "❤️", "max_hp_percent", 2.0, "%"),
    PanoplieType("crit_chance", "Chance de critique", "🎯", "crit_chance_flat", 1.0, ""),
    PanoplieType("crit_damage", "Dégâts critiques", "💥", "crit_damage_flat", 4.0, ""),
    PanoplieType("dodge", "Esquive", "🌀", "dodge_flat", 1.0, ""),
    PanoplieType("hp_regeneration", "Régénération", "✨", "hp_regeneration_flat", 3.0, ""),
)}
DEFAULT_PANOPLIE_TYPE = "attack"


def panoplie_type(code: str | None) -> PanoplieType:
    return PANOPLIE_TYPES.get(code or "", PANOPLIE_TYPES[DEFAULT_PANOPLIE_TYPE])


@dataclass(frozen=True)
class RarityTier:
    """Une rareté et ce qu'elle apporte (pour l'affichage)."""
    rarity: str
    pieces: int                 # pièces de cette rareté OU MIEUX (2 mains = 2)
    multiplier: float           # 0 si sous le premier palier
    next_tier: int | None       # pièces nécessaires au palier suivant
    value: float                # contribution au bonus, dans le type choisi


@dataclass
class SetBonuses:
    """Bonus de panoplie à appliquer (lus par StatsService)."""

    dodge_flat: int = 0
    crit_chance_flat: int = 0
    crit_damage_flat: int = 0
    hp_regeneration_flat: int = 0
    speed_flat: int = 0
    attack_percent: float = 0.0
    defense_percent: float = 0.0
    max_hp_percent: float = 0.0
    mana_max_flat: int = 0
    mana_regeneration_flat: int = 0
    bonus_type: str = DEFAULT_PANOPLIE_TYPE
    #: Bonus total dans l'unité du type (en % pour ATK/DEF/PV), pour l'affichage.
    total: float = 0.0
    tiers: list[RarityTier] = field(default_factory=list)


def tier_for(pieces: int) -> tuple[float, int | None]:
    """(multiplicateur, pièces du palier suivant) pour un nombre de pièces."""
    reached = next((mult for need, mult in TIERS if pieces >= need), 0.0)
    nxt = next((need for need, _ in reversed(TIERS) if pieces < need), None)
    return reached, nxt


def piece_weight(item) -> int:
    return 2 if getattr(item.item_definition, "requires_two_hands", False) else 1


class SetBonusService:
    def aggregate(self, equipped_items, bonus_type: str | None = None) -> SetBonuses:
        kind = panoplie_type(bonus_type)
        rarities = [
            (getattr(item, "rarity", "common") or "common", piece_weight(item))
            for item in equipped_items or []
        ]
        bonuses = SetBonuses(bonus_type=kind.code)
        total = 0.0
        for rarity in RARITY_ORDER:
            idx = rarity_index(rarity)
            pieces = sum(w for r, w in rarities if rarity_index(r) >= idx)
            if pieces == 0:
                break
            mult, nxt = tier_for(pieces)
            value = kind.base * RARITY_STEP[rarity] * mult
            total += value
            bonuses.tiers.append(RarityTier(rarity.value, pieces, mult, nxt, value))

        if kind.unit == "%":
            # StatsService lit des FRACTIONS (0,02 = +2 %), comme l'arbre.
            total = round(total, 1)
            setattr(bonuses, kind.field, total / 100.0)
        else:
            total = round(total)
            setattr(bonuses, kind.field, int(total))
        bonuses.total = total
        return bonuses


def format_panoplie_value(kind: PanoplieType, value: float) -> str:
    v = int(value) if float(value).is_integer() else value
    return f"+{v}{' %' if kind.unit else ''} {kind.emoji}"
