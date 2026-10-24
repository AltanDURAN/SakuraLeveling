"""Équipement — SAISON 1, refonte d'octobre 2026. Règles fixes, décidées avec l'auteur.

  • Chaque MONSTRE lâche UNE pièce précise (celle qu'il porte : son arme, son
    armure, son casque, son bouclier — sinon un accessoire).
  • À sa mort : 0 ou 1 pièce, d'une seule rareté (`DROP_RATES_PCT`, simulé :
    première épique vers J30, tenue légendaire vers J180, ~10 % des joueurs
    assidus trouvent un mythique dans l'année).
  • La RARETÉ multiplie les stats de la pièce : la principale (ATK/DEF/PV en %)
    par `PRIMARY_MULTIPLIER`, les secondaires (plates) par
    `SECONDARY_MULTIPLIER`, qui monte moins vite (la vitesse de base est 5 :
    +5 doublerait les actions).
  • FUSION : 2 copies de la MÊME pièce, de la MÊME rareté + or + matériaux de
    la famille du monstre → 1 copie de la rareté suivante, chez le forgeron
    (armes, boucliers, tête, corps) ou l'artisane (accessoires). Le légendaire
    ne se fusionne pas, le mythique ne s'obtient QU'au drop.
  • PASSIF : un par pièce, une pièce par passif ; il n'apparaît qu'à partir de
    l'ÉPIQUE et n'évolue pas avec la rareté.
  • FORGE SACRÉE (événement) : niveau 0 → 10 par copie, +1 % des stats de la
    pièce par niveau ; une fusion garde le niveau le plus haut des deux copies.
  • Une même pièce ne se porte qu'UNE fois (armes et accessoires compris).
  • Aucun niveau requis : tout est en % du socle du joueur, une pièce reste
    utile toute l'aventure.
"""

from __future__ import annotations

import math
import random
from enum import StrEnum


class Rarity(StrEnum):
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    EPIC = "epic"
    LEGENDARY = "legendary"
    MYTHIC = "mythic"


RARITY_ORDER: tuple[Rarity, ...] = tuple(Rarity)

RARITY_LABELS: dict[str, str] = {
    "common": "Commun", "uncommon": "Peu commun", "rare": "Rare",
    "epic": "Épique", "legendary": "Légendaire", "mythic": "Mythique",
}
RARITY_EMOJIS: dict[str, str] = {
    "common": "⚪", "uncommon": "🟢", "rare": "🔵",
    "epic": "🟣", "legendary": "🟠", "mythic": "🔴",
}
RARITY_COLORS: dict[str, tuple[int, int, int]] = {
    "common": (176, 176, 186), "uncommon": (96, 200, 120), "rare": (80, 150, 240),
    "epic": (170, 100, 230), "legendary": (240, 160, 60), "mythic": (235, 70, 90),
}

PRIMARY_MULTIPLIER: dict[str, float] = {
    "common": 1.0, "uncommon": 1.5, "rare": 2.0,
    "epic": 3.0, "legendary": 4.0, "mythic": 5.5,
}
SECONDARY_MULTIPLIER: dict[str, float] = {
    "common": 1.0, "uncommon": 1.25, "rare": 1.5,
    "epic": 2.0, "legendary": 2.5, "mythic": 3.0,
}

#: Chance (%) qu'un monstre tué lâche sa pièce DANS CETTE rareté. Un seul
#: tirage : au plus une pièce par mort (total ≈ 9,5 %).
DROP_RATES_PCT: dict[str, float] = {
    "common": 6.0, "uncommon": 2.5, "rare": 0.8,
    "epic": 0.2, "legendary": 0.03, "mythic": 0.004,
}

#: Les bonus de chance de drop (arbre « Chance Drop », titres Chasseur
#: légendaire) comptent pour l'équipement, mais BRIDÉS : plafonnés à ×1,5 et
#: seulement jusqu'à l'épique. Légendaire et mythique gardent leurs taux (seul
#: le passif Trouvaille les touche) — simulé : un joueur qui investit gagne ~30 %
#: de temps en milieu de partie, sans multiplier les mythiques. Non bridés
#: (×2 de l'arbre sur toutes les raretés), ils doublaient presque les
#: mythiques (14 % → 25 % des assidus par an).
GEAR_DROP_BONUS_CAP = 1.5
GEAR_DROP_BONUS_MAX_RARITY = Rarity.EPIC

#: Fusion vers cette rareté : or et matériaux de la famille du monstre.
FUSION_GOLD: dict[str, int] = {
    "uncommon": 200, "rare": 1_000, "epic": 6_000, "legendary": 40_000,
}
FUSION_MATERIALS: dict[str, int] = {
    "uncommon": 5, "rare": 15, "epic": 40, "legendary": 100,
}

#: Le passif d'une pièce n'est actif qu'à partir de cette rareté.
PASSIVE_MIN_RARITY = Rarity.EPIC

FORGE_MAX_LEVEL = 10
FORGE_BONUS_PER_LEVEL = 0.01

#: Clés de stats PRINCIPALES (en % du socle) ; tout le reste est secondaire.
PRIMARY_KEYS = frozenset({"attack_pct", "defense_pct", "max_hp_pct"})


#: Référence d'un EXEMPLAIRE dans les autocomplétions et menus (« gear:42 »),
#: là où les objets ordinaires passent leur code.
GEAR_REF_PREFIX = "gear:"


def gear_ref(gear_id: int) -> str:
    return f"{GEAR_REF_PREFIX}{gear_id}"


def parse_gear_ref(value: str | None) -> int | None:
    if value and value.startswith(GEAR_REF_PREFIX) and value[len(GEAR_REF_PREFIX):].isdigit():
        return int(value[len(GEAR_REF_PREFIX):])
    return None


def gear_label(name: str, rarity: str, forge_level: int = 0) -> str:
    """« 🟣 Surin dentelé — Épique +3 »."""
    forge = f" +{forge_level}" if forge_level else ""
    return f"{RARITY_EMOJIS.get(rarity, '')} {name} — {RARITY_LABELS.get(rarity, rarity)}{forge}"


def rarity_index(rarity: str) -> int:
    return RARITY_ORDER.index(Rarity(rarity))


def next_rarity(rarity: str) -> Rarity | None:
    """Rareté obtenue par fusion (None : légendaire et mythique ne fusionnent pas)."""
    r = Rarity(rarity)
    if r in (Rarity.LEGENDARY, Rarity.MYTHIC):
        return None
    return RARITY_ORDER[rarity_index(r) + 1]


def passive_active(rarity: str) -> bool:
    return rarity_index(rarity) >= rarity_index(PASSIVE_MIN_RARITY)


def clamp_forge(level: int) -> int:
    return max(0, min(FORGE_MAX_LEVEL, int(level or 0)))


def _round_secondary(key: str, value: float) -> float:
    # La vitesse reste ENTIÈRE et arrondie vers zéro : +1 ×2,5 = +2, pas +3.
    if key == "speed":
        return float(math.trunc(value))
    return round(value, 1)


def gear_stats(base: dict | None, rarity: str, forge_level: int = 0) -> dict[str, float]:
    """Stats effectives d'une copie : base (valeurs du COMMUN) × rareté × forge."""
    if not base:
        return {}
    forge = 1 + FORGE_BONUS_PER_LEVEL * clamp_forge(forge_level)
    out: dict[str, float] = {}
    for key, value in base.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        if key in PRIMARY_KEYS:
            v = round(value * PRIMARY_MULTIPLIER[rarity] * forge, 1)
        else:
            v = _round_secondary(key, value * SECONDARY_MULTIPLIER[rarity] * forge)
        # Entier quand la valeur tombe juste : « +32 % », pas « +32.0 % ».
        out[key] = int(v) if float(v).is_integer() else v
    return out


def roll_drop(rng: random.Random | None = None, drop_rate_multiplier: float = 1.0,
              drop_bonus: float = 1.0) -> Rarity | None:
    """Tirage à la mort d'un monstre : la rareté lâchée, ou None.

    `drop_rate_multiplier` (passif Trouvaille) multiplie CHAQUE taux : +10 %
    ⇒ 1 % devient 1,1 %. `drop_bonus` (arbre, titres) est bridé : plafonné à
    `GEAR_DROP_BONUS_CAP`, appliqué jusqu'à `GEAR_DROP_BONUS_MAX_RARITY`."""
    rng = rng or random
    bonus = min(max(1.0, drop_bonus), GEAR_DROP_BONUS_CAP)
    cutoff = rarity_index(GEAR_DROP_BONUS_MAX_RARITY)
    roll = rng.random() * 100
    acc = 0.0
    for rarity in reversed(RARITY_ORDER):  # le plus rare d'abord
        mult = max(0.0, drop_rate_multiplier) * (bonus if rarity_index(rarity) <= cutoff else 1.0)
        acc += DROP_RATES_PCT[rarity] * mult
        if roll < acc:
            return rarity
    return None


def fusion_cost(rarity: str) -> tuple[int, int] | None:
    """(or, matériaux) pour fusionner 2 copies de cette rareté (None si impossible)."""
    target = next_rarity(rarity)
    if target is None:
        return None
    return FUSION_GOLD[target], FUSION_MATERIALS[target]
