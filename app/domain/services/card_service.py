"""Cartes à collectionner — règles pures (09/11/2026, décisions de l'auteur).

  • Série 1 « Le Grand Cerisier » : 61 cartes (`cards.json`) — les 43
    monstres des zones F → A, 5 personnages, les 7 divinités de l'offrande,
    les 5 world boss et le Grand Cerisier. La rareté suit la puissance dans le
    jeu : les plus faibles d'une famille sont communs, l'élite est épique ;
  • 6 raretés, celles de l'équipement (mêmes couleurs) ;
  • un booster = 5 cartes : 4 tirées sur `NORMAL_RATES`, la 5e « rare ou
    mieux » sur `HIT_RATES`. Elles se révèlent de la moins rare à la plus
    rare : la meilleure arrive toujours en dernier ;
  • BRILLANTE : chaque carte a `BRILLANTE_PCT` % de chances de sortir
    brillante (même effet, pur prestige). La mythique l'est TOUJOURS, et le
    légendaire donné par la pitié aussi ;
  • pitié : un légendaire au plus tard au `PITY_BOOSTERS`e booster sans
    légendaire ni mythique ;
  • `BOOSTER_PRICE` or le booster, le premier offert ;
  • doublons : gardés (échange, brocante) ou recyclés en pétales
    (`PETALS`, ×`BRILLANTE_PETAL_MULT` pour une brillante). Fabriquer une
    carte manquante coûte `CRAFT_MULT` fois son recyclage — jamais une
    brillante, donc jamais la mythique (elle n'existe qu'en brillante) ;
  • effets : actifs dès qu'on possède la carte (normale ou brillante, une
    seule fois), en combat de zone et au world boss — jamais à la tour, aux
    défis, aux épreuves de rang ni dans la puissance affichée.

Simulé (`tests/content/test_card_balance.py`) : la moitié de l'album en ~10
boosters, l'album complet en ~190 (médiane, ~380 000 or ; 10 % des joueurs
au-delà de 530 boosters, faute de mythique), l'album tout brillant en ~3 400
boosters seul : il se complète à l'échange.
"""

from __future__ import annotations

import random
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.domain.services.gear_service import RARITY_COLORS, RARITY_EMOJIS

RARITIES: tuple[str, ...] = ("common", "uncommon", "rare", "epic", "legendary", "mythic")
#: Au féminin : une carte.
RARITY_LABELS: dict[str, str] = {
    "common": "Commune", "uncommon": "Peu commune", "rare": "Rare",
    "epic": "Épique", "legendary": "Légendaire", "mythic": "Mythique",
}
CARD_RARITY_EMOJIS = RARITY_EMOJIS
CARD_RARITY_COLORS = RARITY_COLORS
#: Ce qui remet le compteur de la pitié à zéro.
TOP_RARITIES = frozenset({"legendary", "mythic"})

BOOSTER_SIZE = 5
BOOSTER_PRICE = 2000
#: Les 4 premières cartes d'un booster (en %).
NORMAL_RATES: dict[str, float] = {
    "common": 68.0, "uncommon": 24.0, "rare": 6.0, "epic": 1.6, "legendary": 0.38, "mythic": 0.02,
}
#: La 5e carte, « rare ou mieux » (en %).
HIT_RATES: dict[str, float] = {"rare": 72.7, "epic": 22.0, "legendary": 5.0, "mythic": 0.3}
BRILLANTE_PCT = 4.0
PITY_BOOSTERS = 40

#: Pétales du recyclage d'un doublon ; une brillante en vaut 5 fois plus.
PETALS: dict[str, int] = {
    "common": 5, "uncommon": 10, "rare": 25, "epic": 80, "legendary": 400, "mythic": 2000,
}
BRILLANTE_PETAL_MULT = 5
CRAFT_MULT = 10
#: Titres de l'album (% des cartes possédées).
ALBUM_MILESTONES: tuple[int, ...] = (25, 50, 75, 100)

CATEGORIES: dict[str, str] = {
    "monstre": "Monstre", "personnage": "Personnage", "divinite": "Divinité",
    "boss": "World boss", "mythique": "Mythique",
}
#: Les pages de l'album, dans l'ordre.
CHAPTERS: tuple[tuple[str, str], ...] = (
    ("clairiere", "🌿 Clairière sinistre"),
    ("cimetiere", "🪦 Cimetière abandonné"),
    ("berceau", "🔥 Berceau cataclysmique"),
    ("sanctuaire", "🌳 Sanctuaire primordial"),
    ("eclipse", "🌘 Éclipse éternelle"),
    ("cimes", "🐉 Cimes des Wyrms"),
    ("personnages", "🏘️ Personnages"),
    ("divinites", "🙏 Divinités"),
    ("legendes", "👑 Légendes"),
)
CHAPTER_LABELS = dict(CHAPTERS)


def chapter_name(chapter: str) -> str:
    """Le nom du chapitre sans son emoji (les polices des images ne l'ont pas)."""
    label = CHAPTER_LABELS.get(chapter, chapter)
    return label.split(" ", 1)[1] if " " in label else label

#: Effets « bonus » (divinités, personnages, mythique) : clé → texte.
BONUS_TEXTS: dict[str, str] = {
    "materials_pct": "+{v} % de matériaux en zone",
    "xp_pct": "+{v} % d'XP en zone",
    "gold_pct": "+{v} % d'or en zone",
    "gear_drop_pct": "+{v} % de chances de pièce (commun → épique)",
    "regen_pct": "+{v} % de régénération hors combat",
    "essence_pct": "+{v} % d'essences",
    "pack_reward_pct": "+{v} % d'or et d'XP contre les meutes",
    "tower_daily_pct": "+{v} % d'or à la récompense du jour de la tour",
    "fusion_discount_pct": "−{v} % d'or sur les fusions de Borak",
    "brew_bonus_pct": "+{v} % de chances de potion offerte chez Elna",
    "brillante_bonus_pct": "+{v} % de chances de brillante dans tes boosters",
    "seer_discount_pct": "−{v} % sur les lectures d'Ysaline",
    "potion_heal_pct": "+{v} % de PV rendus par les potions de soin",
}


@dataclass(frozen=True)
class CardDef:
    code: str
    number: int
    name: str
    category: str
    rarity: str
    chapter: str
    effect: dict = field(default_factory=dict)
    flavor: str = ""
    element: str = ""
    #: Ce que la carte représente : code du monstre, du boss, du PNJ…
    source: str = ""
    #: Sous-titre (« Forgeron », « Déesse de l'abondance », la zone…).
    title: str = ""

    @property
    def always_brillante(self) -> bool:
        """La mythique n'existe qu'en brillante."""
        return self.rarity == "mythic"


@dataclass(frozen=True)
class Pull:
    code: str
    rarity: str
    brillante: bool
    #: Le légendaire donné par la pitié.
    pity: bool = False


def rarity_index(rarity: str) -> int:
    return RARITIES.index(rarity) if rarity in RARITIES else -1


def _roll(rates: dict[str, float], rng: random.Random) -> str:
    x = rng.random() * sum(rates.values())
    for rarity, weight in rates.items():
        x -= weight
        if x < 0:
            return rarity
    return next(reversed(rates))


def _pool(cards_by_rarity: dict[str, list[str]], rarity: str) -> tuple[str, list[str]]:
    """Les cartes de cette rareté ; à défaut, de la plus proche en dessous."""
    for r in reversed(RARITIES[:rarity_index(rarity) + 1]):
        if cards_by_rarity.get(r):
            return r, cards_by_rarity[r]
    for r in RARITIES:
        if cards_by_rarity.get(r):
            return r, cards_by_rarity[r]
    raise ValueError("aucune carte à tirer")


def open_booster(cards_by_rarity: dict[str, list[str]], rng: random.Random, since_top: int,
                 brillante_pct: float = BRILLANTE_PCT) -> tuple[list[Pull], int]:
    """Ouvre UN booster. `since_top` = boosters déjà ouverts sans légendaire
    ni mythique. Renvoie les cartes (de la moins rare à la plus rare) et le
    nouveau compteur de la pitié."""
    rarities = [_roll(NORMAL_RATES, rng) for _ in range(BOOSTER_SIZE - 1)] + [_roll(HIT_RATES, rng)]
    pity = since_top + 1 >= PITY_BOOSTERS and not TOP_RARITIES.intersection(rarities)
    if pity:
        rarities[-1] = "legendary"
    pulls = []
    for index, wanted in enumerate(rarities):
        rarity, pool = _pool(cards_by_rarity, wanted)
        code = rng.choice(pool)
        forced = pity and index == len(rarities) - 1
        brillante = rarity == "mythic" or forced or rng.random() * 100 < brillante_pct
        pulls.append(Pull(code, rarity, brillante, forced))
    pulls.sort(key=lambda p: rarity_index(p.rarity))           # la meilleure en dernier
    since = 0 if any(p.rarity in TOP_RARITIES for p in pulls) else since_top + 1
    return pulls, since


def boosters_before_pity(since_top: int) -> int:
    """Le légendaire garanti arrive au plus tard dans N boosters."""
    return max(1, PITY_BOOSTERS - since_top)


# ------------------------------------------------------------- doublons --
def petals_for(rarity: str, brillante: bool = False) -> int:
    return PETALS.get(rarity, 0) * (BRILLANTE_PETAL_MULT if brillante else 1)


def craftable(card: CardDef) -> bool:
    """Jamais une brillante : la mythique, toujours brillante, ne se fabrique pas."""
    return not card.always_brillante


def craft_cost(rarity: str) -> int:
    return CRAFT_MULT * PETALS.get(rarity, 0)


def duplicates(quantity: int) -> int:
    """Exemplaires recyclables : on garde toujours le premier."""
    return max(0, int(quantity) - 1)


# --------------------------------------------------------------- album --
@dataclass(frozen=True)
class Album:
    total: int
    owned: int
    brillantes: int
    #: rareté → (possédées, total)
    by_rarity: dict[str, tuple[int, int]]

    @property
    def percent(self) -> int:
        return 100 * self.owned // self.total if self.total else 0

    @property
    def complete(self) -> bool:
        return self.total > 0 and self.owned == self.total

    @property
    def brillante_complete(self) -> bool:
        return self.total > 0 and self.brillantes == self.total


def album(cards: Iterable[CardDef], normal: dict[str, int], brillante: dict[str, int]) -> Album:
    """`normal` / `brillante` : code de carte → exemplaires. Une carte compte
    comme possédée en normale OU en brillante."""
    cards = list(cards)
    by_rarity: dict[str, list[int]] = {r: [0, 0] for r in RARITIES}
    owned = shiny = 0
    for card in cards:
        has = normal.get(card.code, 0) > 0 or brillante.get(card.code, 0) > 0
        owned += has
        shiny += brillante.get(card.code, 0) > 0
        entry = by_rarity.setdefault(card.rarity, [0, 0])
        entry[0] += has
        entry[1] += 1
    return Album(len(cards), owned, shiny,
                 {r: (v[0], v[1]) for r, v in by_rarity.items() if v[1]})


def milestones_reached(percent: int) -> list[int]:
    return [m for m in ALBUM_MILESTONES if percent >= m]


# --------------------------------------------------------------- effets --
@dataclass
class CardBonuses:
    """Ce que rapportent les cartes possédées (chacune une fois)."""
    damage_vs_mob: dict[str, int] = field(default_factory=dict)
    drop_vs_mob: dict[str, int] = field(default_factory=dict)
    boss_damage: dict[str, int] = field(default_factory=dict)
    materials_pct: int = 0
    xp_pct: int = 0
    gold_pct: int = 0
    gear_drop_pct: int = 0
    regen_pct: int = 0
    essence_pct: int = 0
    pack_reward_pct: int = 0
    tower_daily_pct: int = 0
    fusion_discount_pct: int = 0
    brew_bonus_pct: int = 0
    brillante_bonus_pct: int = 0
    seer_discount_pct: int = 0
    potion_heal_pct: int = 0


NO_CARD_BONUSES = CardBonuses()


def card_bonuses(cards: Iterable[CardDef]) -> CardBonuses:
    """Agrège les effets des cartes POSSÉDÉES (une fois chacune)."""
    out = CardBonuses()
    seen: set[str] = set()
    for card in cards:
        if card.code in seen:
            continue
        seen.add(card.code)
        effect = card.effect or {}
        kind = effect.get("type")
        if kind == "monstre":
            mob = effect.get("mob") or card.source
            out.damage_vs_mob[mob] = out.damage_vs_mob.get(mob, 0) + int(effect.get("damage_pct", 0))
            out.drop_vs_mob[mob] = out.drop_vs_mob.get(mob, 0) + int(effect.get("drop_pct", 0))
        elif kind == "boss":
            for code in [effect.get("boss") or card.source, *effect.get("guards", [])]:
                out.boss_damage[code] = out.boss_damage.get(code, 0) + int(effect.get("damage_pct", 0))
        elif kind == "bonus":
            for key, value in effect.items():
                if key in BONUS_TEXTS:
                    setattr(out, key, getattr(out, key) + int(value))
    return out


def with_card_bonuses(titles, cards: CardBonuses, *, boss: bool = False):
    """Les bonus de titres d'un joueur, plus ceux de ses cartes qui jouent
    DANS CE COMBAT : contre chaque monstre en zone (dégâts et butin), contre le
    boss et ses gardes au world boss (les gardes portent des codes de
    monstres : leurs cartes ne s'appliquent pas au raid). Jamais ailleurs."""
    from dataclasses import replace

    damage = dict(titles.damage_bonus_vs_mob)
    drops = dict(titles.drop_rate_bonus_vs_mob)
    for code, pct in (cards.boss_damage if boss else cards.damage_vs_mob).items():
        damage[code] = damage.get(code, 0) + pct
    if not boss:
        for code, pct in cards.drop_vs_mob.items():
            drops[code] = drops.get(code, 0) + pct
    return replace(titles, damage_bonus_vs_mob=damage, drop_rate_bonus_vs_mob=drops)


def stochastic_round(value: float, rng: random.Random | None = None) -> int:
    """Arrondi qui garde la moyenne : 1,05 → 1 (95 %) ou 2 (5 %)."""
    base = int(value)
    return base + (1 if (rng or random).random() < value - base else 0)


def effect_text(card: CardDef) -> str:
    """L'effet de la carte, pour la carte elle-même et l'album."""
    effect = card.effect or {}
    kind = effect.get("type")
    if kind == "monstre":
        return (f"Contre {card.name} : +{effect.get('damage_pct', 0)} % de dégâts, "
                f"+{effect.get('drop_pct', 0)} % de butin")
    if kind == "boss":
        return f"Au raid contre {card.name} : +{effect.get('damage_pct', 0)} % de dégâts, gardes compris"
    if kind == "bonus":
        parts = [BONUS_TEXTS[key].format(v=value) for key, value in effect.items() if key in BONUS_TEXTS]
        return " · ".join(parts)
    return ""


def validate(cards: list[CardDef], mob_codes: set[str] | None = None,
             boss_codes: set[str] | None = None) -> list[str]:
    """Problèmes d'une série de cartes (vide = tout va bien)."""
    problems = []
    codes = [c.code for c in cards]
    if len(set(codes)) != len(codes):
        problems.append("codes de carte en double")
    numbers = sorted(c.number for c in cards)
    if numbers != list(range(1, len(cards) + 1)):
        problems.append("numéros non consécutifs depuis 1")
    for card in cards:
        if card.rarity not in RARITIES:
            problems.append(f"{card.code} : rareté inconnue « {card.rarity} »")
        if card.chapter not in CHAPTER_LABELS:
            problems.append(f"{card.code} : chapitre inconnu « {card.chapter} »")
        effect = card.effect or {}
        kind = effect.get("type")
        if kind == "monstre" and mob_codes is not None and (effect.get("mob") or card.source) not in mob_codes:
            problems.append(f"{card.code} : monstre inconnu")
        elif kind == "boss" and boss_codes is not None and (effect.get("boss") or card.source) not in boss_codes:
            problems.append(f"{card.code} : boss inconnu")
        elif kind == "bonus" and not any(key in BONUS_TEXTS for key in effect):
            problems.append(f"{card.code} : effet sans bonus connu")
        elif kind not in ("monstre", "boss", "bonus"):
            problems.append(f"{card.code} : type d'effet inconnu « {kind} »")
    return problems
