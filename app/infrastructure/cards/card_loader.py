"""Cartes à collectionner : `cards.json` (une série), relu quand il change.

Chaque carte existe en deux OBJETS d'inventaire (catégorie `carte`) — la
normale `carte_<code>` et la brillante `carte_<code>_brillante` ; la mythique
n'a que la brillante. Comme des objets, elles s'échangent (/echange) et se
vendent à la brocante sans code de plus. `seed_content` les crée.

Image d'une carte (`art_path`) : pour un monstre, son image (`assets/mobs`,
d'après `mobs.json`), sinon l'ébauche `assets/cards/<code>.png` ; pour les
autres, `assets/cards/<code>.png` — c'est là que se remplacent leurs visuels —
sinon le portrait du personnage (`assets/npcs`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.domain.services.card_service import RARITIES, CardDef

CONTENT_PATH = Path(__file__).resolve().parents[1] / "content" / "cards.json"
MOBS_PATH = Path(__file__).resolve().parents[1] / "content" / "mobs.json"
ASSETS = Path(__file__).resolve().parents[3] / "assets"
CARD_ART = ASSETS / "cards"

ITEM_PREFIX = "carte_"
BRILLANTE_SUFFIX = "_brillante"


@dataclass(frozen=True)
class CardSeries:
    number: int
    name: str
    cards: tuple[CardDef, ...]


_cache: dict[str, tuple[float, object]] = {}


def _cached(path: Path, key: str, build):
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    hit = _cache.get(key)
    if hit is None or hit[0] != mtime:
        hit = (mtime, build())
        _cache[key] = hit
    return hit[1]


def _card(raw: dict) -> CardDef:
    return CardDef(
        code=raw["code"], number=int(raw["number"]), name=raw["name"],
        category=raw.get("category", ""), rarity=raw.get("rarity", "common"),
        chapter=raw.get("chapter", ""), effect=dict(raw.get("effect") or {}),
        flavor=raw.get("flavor", ""), element=raw.get("element", "") or "",
        source=raw.get("source", "") or "", title=raw.get("title", "") or "",
    )


def _load() -> CardSeries:
    data = json.loads(CONTENT_PATH.read_text(encoding="utf-8"))
    cards = tuple(sorted((_card(raw) for raw in data.get("cards", [])), key=lambda c: c.number))
    return CardSeries(int(data.get("series", 1)), data.get("name", ""), cards)


def get_series() -> CardSeries:
    return _cached(CONTENT_PATH, "series", _load)


def list_cards() -> list[CardDef]:
    return list(get_series().cards)


def get_card(code: str) -> CardDef | None:
    return next((c for c in get_series().cards if c.code == code), None)


def by_rarity() -> dict[str, list[str]]:
    """Codes des cartes par rareté (le tirage d'un booster)."""
    out: dict[str, list[str]] = {r: [] for r in RARITIES}
    for card in get_series().cards:
        out.setdefault(card.rarity, []).append(card.code)
    return out


# ------------------------------------------------------- objets d'inventaire --
def item_code(code: str, brillante: bool = False) -> str:
    return f"{ITEM_PREFIX}{code}{BRILLANTE_SUFFIX if brillante else ''}"


def parse_item_code(code: str) -> tuple[str, bool] | None:
    """`carte_<code>[_brillante]` → (code de la carte, brillante ?)."""
    if not code.startswith(ITEM_PREFIX):
        return None
    rest = code[len(ITEM_PREFIX):]
    brillante = rest.endswith(BRILLANTE_SUFFIX)
    if brillante:
        rest = rest[: -len(BRILLANTE_SUFFIX)]
    return rest, brillante


def variants(card: CardDef) -> list[bool]:
    """Les versions d'une carte : normale et brillante (la mythique : brillante)."""
    return [True] if card.always_brillante else [False, True]


def item_name(card: CardDef, brillante: bool = False) -> str:
    return f"Carte {card.name}" + (" ✨" if brillante else "")


# --------------------------------------------------------------- images --
def _mob_images() -> dict[str, str]:
    def build():
        try:
            data = json.loads(MOBS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        mobs = data if isinstance(data, list) else data.get("mobs", [])
        return {m.get("code", ""): m.get("image_name", "") or "" for m in mobs}
    return _cached(MOBS_PATH, "mob_images", build)


def art_path(card: CardDef) -> Path | None:
    """L'image de la carte (None : pas encore d'image)."""
    own = CARD_ART / f"{card.code}.png"
    candidates: list[Path] = []
    if card.category == "monstre":
        # L'image du monstre d'abord : quand l'auteur dessine le monstre, la
        # carte la prend (l'ébauche de assets/cards ne sert qu'en attendant).
        image = _mob_images().get(card.source, "")
        if image:
            candidates.append(ASSETS / "mobs" / image)
        candidates.append(own)
    else:
        candidates.append(own)
        if card.category == "personnage":
            candidates.append(ASSETS / "npcs" / f"{card.source}.png")
    return next((p for p in candidates if p.is_file()), None)
