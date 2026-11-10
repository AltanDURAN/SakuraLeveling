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

Les chiffres ci-dessous sont les réglages PAR DÉFAUT : le site admin
(Objets › Cartes) les change dans la section `params` de `cards.json`
(`CardParams`, relue par le bot sans redémarrage). Les chapitres de l'album
(`chapters`) y sont aussi.

Simulé (`simulate_album`, `tests/content/test_card_balance.py`) : la moitié de
l'album en ~10 boosters, l'album complet en ~190 (médiane, ~380 000 or ; 10 %
des joueurs au-delà de 530 boosters, faute de mythique), l'album tout brillant
en ~3 400 boosters seul : il se complète à l'échange.
"""

from __future__ import annotations

import random
import statistics
from collections.abc import Iterable, Mapping
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

#: Fixe : la mise en page du résultat et l'animation d'ouverture en dépendent.
BOOSTER_SIZE = 5
# ------------------------------------------------- réglages par défaut --
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
CRAFT_MULT = 20
#: Titres de l'album (% des cartes possédées).
ALBUM_MILESTONES: tuple[int, ...] = (25, 50, 75, 100)
#: Au plus, d'un coup (le message de résultat doit rester lisible).
MAX_PER_OPENING = 10


@dataclass(frozen=True)
class CardParams:
    """Réglages des boosters : section `params` de `cards.json`, modifiée par
    le site admin (Objets › Cartes). Les défauts sont les décisions de
    l'auteur du 09/11/2026."""
    booster_price: int = BOOSTER_PRICE
    #: Le premier booster de chaque joueur est offert.
    first_free: bool = True
    #: Cartes 1 à 4 d'un booster (en %, total 100).
    normal_rates: Mapping[str, float] = field(default_factory=lambda: dict(NORMAL_RATES))
    #: La dernière carte (en %, total 100).
    hit_rates: Mapping[str, float] = field(default_factory=lambda: dict(HIT_RATES))
    brillante_pct: float = BRILLANTE_PCT
    #: Légendaire garanti au plus tard au N-ième booster sans légendaire ni
    #: mythique (0 = pas de garantie).
    pity_boosters: int = PITY_BOOSTERS
    petals: Mapping[str, int] = field(default_factory=lambda: dict(PETALS))
    brillante_petal_mult: int = BRILLANTE_PETAL_MULT
    #: Fabriquer = ce multiple du recyclage de la carte.
    craft_mult: int = CRAFT_MULT


DEFAULT_PARAMS = CardParams()


def _number(value, default, cast):
    try:
        return cast(value)
    except (TypeError, ValueError):
        return default


def _rates(raw, default: Mapping[str, float]) -> dict[str, float]:
    if not isinstance(raw, Mapping):
        return dict(default)
    return {r: max(0.0, _number(raw.get(r, 0) or 0, 0.0, float)) for r in RARITIES
            if _number(raw.get(r, 0) or 0, 0.0, float) > 0}


def params_from_dict(raw: Mapping | None) -> CardParams:
    """Les réglages lus dans `cards.json` (un champ absent ou illisible garde
    sa valeur par défaut)."""
    raw = raw if isinstance(raw, Mapping) else {}
    d = DEFAULT_PARAMS
    petals = raw.get("petals")
    return CardParams(
        booster_price=_number(raw.get("booster_price", d.booster_price), d.booster_price, int),
        first_free=bool(raw.get("first_free", d.first_free)),
        normal_rates=_rates(raw.get("normal_rates"), d.normal_rates),
        hit_rates=_rates(raw.get("hit_rates"), d.hit_rates),
        brillante_pct=_number(raw.get("brillante_pct", d.brillante_pct), d.brillante_pct, float),
        pity_boosters=_number(raw.get("pity_boosters", d.pity_boosters), d.pity_boosters, int),
        petals=({r: _number(petals.get(r, d.petals[r]), d.petals[r], int) for r in RARITIES}
                if isinstance(petals, Mapping) else dict(d.petals)),
        brillante_petal_mult=_number(raw.get("brillante_petal_mult", d.brillante_petal_mult),
                                     d.brillante_petal_mult, int),
        craft_mult=_number(raw.get("craft_mult", d.craft_mult), d.craft_mult, int),
    )


def params_to_dict(params: CardParams) -> dict:
    """Pour `cards.json` (taux dans l'ordre des raretés, sans les zéros)."""
    def rates(values):
        return {r: values[r] for r in RARITIES if values.get(r, 0) > 0}
    return {
        "booster_price": int(params.booster_price),
        "first_free": bool(params.first_free),
        "normal_rates": rates(params.normal_rates),
        "hit_rates": rates(params.hit_rates),
        "brillante_pct": params.brillante_pct,
        "pity_boosters": int(params.pity_boosters),
        "petals": {r: int(params.petals.get(r, 0)) for r in RARITIES},
        "brillante_petal_mult": int(params.brillante_petal_mult),
        "craft_mult": int(params.craft_mult),
    }


def validate_params(params: CardParams) -> list[str]:
    """Problèmes d'un réglage (vide = valable)."""
    problems = []
    if not 0 <= params.booster_price <= 10_000_000:
        problems.append("Le prix d'un booster va de 0 à 10 000 000 or.")
    for label, rates in (("des cartes 1 à 4", params.normal_rates), ("de la dernière carte", params.hit_rates)):
        if any(v < 0 for v in rates.values()):
            problems.append(f"Les taux {label} sont positifs.")
        total = sum(rates.values())
        if abs(total - 100) > 0.01:
            problems.append(f"Les taux {label} font {total:g} % : il faut 100 %.")
    if not 0 <= params.brillante_pct <= 100:
        problems.append("La chance de brillante va de 0 à 100 %.")
    if not 0 <= params.pity_boosters <= 1000:
        problems.append("Le légendaire garanti arrive au plus tard au 1 000e booster (0 : jamais garanti).")
    if any(not 0 <= params.petals.get(r, 0) <= 10_000_000 for r in RARITIES):
        problems.append("Les pétales d'une carte vont de 0 à 10 000 000.")
    if not 1 <= params.brillante_petal_mult <= 100:
        problems.append("Une brillante vaut de 1 à 100 fois une normale en pétales.")
    if not 1 <= params.craft_mult <= 1000:
        problems.append("Fabriquer coûte de 1 à 1 000 fois le recyclage.")
    return problems


CATEGORIES: dict[str, str] = {
    "monstre": "Monstre", "personnage": "Personnage", "divinite": "Divinité",
    "boss": "World boss", "mythique": "Mythique",
}


@dataclass(frozen=True)
class Chapter:
    """Une page de l'album (section `chapters` de `cards.json`)."""
    code: str
    name: str
    emoji: str = ""
    #: Décor (`assets/landscapes`) derrière l'image des cartes du chapitre.
    decor: str = ""

    @property
    def label(self) -> str:
        return f"{self.emoji} {self.name}".strip()


#: Les pages de l'album, dans l'ordre (si `cards.json` n'en donne pas).
DEFAULT_CHAPTERS: tuple[Chapter, ...] = (
    Chapter("clairiere", "Clairière sinistre", "🌿", "clairiere_sinistre.png"),
    Chapter("cimetiere", "Cimetière abandonné", "🪦", "cimetiere_abandonne_lumiere.png"),
    Chapter("berceau", "Berceau cataclysmique", "🔥", "berceau_cataclysmique.png"),
    Chapter("sanctuaire", "Sanctuaire primordial", "🌳"),
    Chapter("eclipse", "Éclipse éternelle", "🌘"),
    Chapter("cimes", "Cimes des Wyrms", "🐉"),
    Chapter("personnages", "Personnages", "🏘️"),
    Chapter("divinites", "Divinités", "🙏", "horizon_celeste.png"),
    Chapter("legendes", "Légendes", "👑", "fracture_elementaire.png"),
)
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


def _roll(rates: Mapping[str, float], rng: random.Random) -> str:
    weighted = [(r, w) for r, w in rates.items() if w > 0]
    x = rng.random() * sum(w for _, w in weighted)
    for rarity, weight in weighted:
        x -= weight
        if x < 0:
            return rarity
    return weighted[-1][0] if weighted else RARITIES[0]


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
                 brillante_pct: float | None = None, *,
                 params: CardParams = DEFAULT_PARAMS) -> tuple[list[Pull], int]:
    """Ouvre UN booster. `since_top` = boosters déjà ouverts sans légendaire
    ni mythique. `brillante_pct` (défaut : celui des réglages) compte déjà la
    carte de Sorn. Renvoie les cartes (de la moins rare à la plus rare) et le
    nouveau compteur de la pitié."""
    if brillante_pct is None:
        brillante_pct = params.brillante_pct
    rarities = [_roll(params.normal_rates, rng) for _ in range(BOOSTER_SIZE - 1)] + [_roll(params.hit_rates, rng)]
    pity = (params.pity_boosters > 0 and since_top + 1 >= params.pity_boosters
            and not TOP_RARITIES.intersection(rarities))
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


def boosters_before_pity(since_top: int, params: CardParams = DEFAULT_PARAMS) -> int | None:
    """Le légendaire garanti arrive au plus tard dans N boosters (None : pas
    de garantie)."""
    if params.pity_boosters <= 0:
        return None
    return max(1, params.pity_boosters - since_top)


def per_booster(rarity: str, params: CardParams = DEFAULT_PARAMS) -> float:
    """Chance d'avoir au moins une carte de cette rareté dans un booster (hors
    pitié)."""
    def share(rates):
        total = sum(rates.values())
        return rates.get(rarity, 0) / total if total else 0.0
    return 1 - (1 - share(params.normal_rates)) ** (BOOSTER_SIZE - 1) * (1 - share(params.hit_rates))


def lowest_hit(params: CardParams = DEFAULT_PARAMS) -> str:
    """La rareté minimale de la dernière carte (« rare ou mieux »)."""
    return next((r for r in RARITIES if params.hit_rates.get(r, 0) > 0), RARITIES[0])


def expected_petals(params: CardParams = DEFAULT_PARAMS) -> float:
    """Pétales moyens d'un booster dont TOUTES les cartes sont des doublons
    recyclés (la mythique est toujours brillante)."""
    shiny = params.brillante_pct / 100
    total = 0.0
    for rates, slots in ((params.normal_rates, BOOSTER_SIZE - 1), (params.hit_rates, 1)):
        weight = sum(rates.values())
        for rarity, rate in rates.items():
            if not weight:
                continue
            if rarity == "mythic":
                value = petals_for(rarity, True, params)
            else:
                value = petals_for(rarity, False, params) * (1 - shiny) + petals_for(rarity, True, params) * shiny
            total += slots * rate / weight * value
    return total


# ------------------------------------------------------------- doublons --
def petals_for(rarity: str, brillante: bool = False, params: CardParams = DEFAULT_PARAMS) -> int:
    return int(params.petals.get(rarity, 0)) * (params.brillante_petal_mult if brillante else 1)


def craftable(card: CardDef) -> bool:
    """Jamais une brillante : la mythique, toujours brillante, ne se fabrique pas."""
    return not card.always_brillante


def craft_cost(rarity: str, params: CardParams = DEFAULT_PARAMS) -> int:
    return params.craft_mult * int(params.petals.get(rarity, 0))


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
             boss_codes: set[str] | None = None, chapters: Iterable[str] | None = None) -> list[str]:
    """Problèmes d'une série de cartes (vide = tout va bien)."""
    problems = []
    chapter_codes = set(chapters) if chapters is not None else {c.code for c in DEFAULT_CHAPTERS}
    codes = [c.code for c in cards]
    if len(set(codes)) != len(codes):
        problems.append("codes de carte en double")
    numbers = sorted(c.number for c in cards)
    if numbers != list(range(1, len(cards) + 1)):
        problems.append("numéros non consécutifs depuis 1")
    for card in cards:
        if not card.code or not card.code.replace("_", "").isalnum() or card.code != card.code.lower():
            problems.append(f"« {card.code} » : un code de carte n'a que des minuscules, chiffres et _")
        if not card.name.strip():
            problems.append(f"{card.code} : carte sans nom")
        if card.rarity not in RARITIES:
            problems.append(f"{card.code} : rareté inconnue « {card.rarity} »")
        if card.chapter not in chapter_codes:
            problems.append(f"{card.code} : chapitre inconnu « {card.chapter} »")
        if card.category not in CATEGORIES:
            problems.append(f"{card.code} : catégorie inconnue « {card.category} »")
        effect = card.effect or {}
        kind = effect.get("type")
        if kind == "monstre" and mob_codes is not None and (effect.get("mob") or card.source) not in mob_codes:
            problems.append(f"{card.code} : monstre inconnu")
        elif kind == "boss" and boss_codes is not None and (effect.get("boss") or card.source) not in boss_codes:
            problems.append(f"{card.code} : boss inconnu")
        elif kind == "boss" and mob_codes is not None and any(g not in mob_codes for g in effect.get("guards", [])):
            problems.append(f"{card.code} : garde inconnu")
        elif kind == "bonus" and not any(key in BONUS_TEXTS for key in effect):
            problems.append(f"{card.code} : effet sans bonus connu")
        elif kind not in ("monstre", "boss", "bonus"):
            problems.append(f"{card.code} : type d'effet inconnu « {kind} »")
        for key, value in effect.items():
            if key in ("type", "mob", "boss", "guards"):
                continue
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 1000:
                problems.append(f"{card.code} : « {key} » doit être un nombre entier de 0 à 1 000")
    return problems


# ----------------------------------------------------------- simulation --
@dataclass(frozen=True)
class AlbumSimulation:
    """Boosters ouverts par un joueur seul (sans échange), qui recycle tous
    ses doublons et fabrique la carte manquante la plus chère dès qu'il peut."""
    runs: int
    half: int                 # médiane : la moitié de l'album
    full: int                 # médiane : l'album complet
    full_p90: int             # 10 % des joueurs vont au-delà
    mythic: int | None        # médiane : la première mythique (None : aucune dans la série)
    capped: int               # parcours arrêtés à `max_boosters` (album impossible ?)


def simulate_album(cards: Iterable[CardDef], params: CardParams = DEFAULT_PARAMS, *, runs: int = 200,
                   rng: random.Random | None = None, max_boosters: int = 3000) -> AlbumSimulation:
    cards = list(cards)
    rng = rng or random.Random()
    pool: dict[str, list[str]] = {r: [] for r in RARITIES}
    for card in cards:
        pool.setdefault(card.rarity, []).append(card.code)
    rarity_of = {c.code: c.rarity for c in cards}
    by_cost = sorted((c.code for c in cards if craftable(c)), key=lambda code: -craft_cost(rarity_of[code], params))
    has_mythic = any(c.rarity == "mythic" for c in cards)
    total = len(cards)
    halves, fulls, mythics = [], [], []
    capped = 0
    for _ in range(runs):
        owned: set[str] = set()
        petals = since = cursor = 0
        half = mythic = None
        opened = 0
        while opened < max_boosters and len(owned) < total:
            opened += 1
            pulls, since = open_booster(pool, rng, since, params=params)
            for pull in pulls:
                if pull.code in owned:
                    petals += petals_for(pull.rarity, pull.brillante, params)
                else:
                    owned.add(pull.code)
                if mythic is None and pull.rarity == "mythic":
                    mythic = opened
            while True:
                while cursor < len(by_cost) and by_cost[cursor] in owned:
                    cursor += 1
                if cursor >= len(by_cost):
                    break
                cost = craft_cost(rarity_of[by_cost[cursor]], params)
                if petals < cost:
                    break
                petals -= cost
                owned.add(by_cost[cursor])
            if half is None and 2 * len(owned) >= total:
                half = opened
        capped += len(owned) < total
        halves.append(half or max_boosters)
        fulls.append(opened)
        mythics.append(mythic or max_boosters)
    fulls.sort()
    return AlbumSimulation(
        runs=runs, half=int(statistics.median(halves)), full=int(statistics.median(fulls)),
        full_p90=fulls[min(len(fulls) - 1, int(0.9 * len(fulls)))],
        mythic=int(statistics.median(mythics)) if has_mythic else None, capped=capped,
    )
