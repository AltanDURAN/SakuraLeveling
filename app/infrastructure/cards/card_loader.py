"""Cartes à collectionner : `cards.json` (une série), relu quand il change.

Chaque carte existe en deux OBJETS d'inventaire (catégorie `carte`) — la
normale `carte_<code>` et la brillante `carte_<code>_brillante` ; la mythique
n'a que la brillante. Comme des objets, elles s'échangent (/echange) et se
vendent à la brocante sans code de plus. `seed_content` les crée.

Le fichier porte aussi les RÉGLAGES des boosters (`params` → `CardParams`)
et les CHAPITRES de l'album (`chapters`), modifiés depuis le site admin
(Objets › Cartes) : le bot les relit dès que le fichier change.

Image d'une carte (`art_path`), dans cet ordre :
  1. `assets/cards/<code>.png` — l'image de l'auteur (déposée à la main ou
     envoyée depuis le site), elle passe avant tout ;
  2. pour un monstre, son image de jeu (`assets/mobs`, d'après `mobs.json`) ;
     pour un personnage, son portrait (`assets/npcs/<source>.png`) ;
  3. l'ébauche générée (`assets/cards/ebauches/<code>.png`), en attendant.
La BRILLANTE est « pleine carte » : `assets/cards/<code>_fullart.png` si
l'auteur en a fait une, sinon elle est composée à partir de l'image.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.domain.services.card_service import (
    DEFAULT_CHAPTERS,
    RARITIES,
    CardDef,
    CardParams,
    Chapter,
    params_from_dict,
)

CONTENT_PATH = Path(__file__).resolve().parents[1] / "content" / "cards.json"
MOBS_PATH = Path(__file__).resolve().parents[1] / "content" / "mobs.json"
ASSETS = Path(__file__).resolve().parents[3] / "assets"
CARD_ART = ASSETS / "cards"
#: Les ébauches générées (Cloudflare, 09/11/2026), en attendant les images de l'auteur.
DRAFT_ART = CARD_ART / "ebauches"
LANDSCAPES = ASSETS / "landscapes"
FULL_ART_SUFFIX = "_fullart"
BACK_FILE = CARD_ART / "_dos.png"

ITEM_PREFIX = "carte_"
BRILLANTE_SUFFIX = "_brillante"


@dataclass(frozen=True)
class CardSeries:
    number: int
    name: str
    cards: tuple[CardDef, ...]
    params: CardParams = CardParams()
    chapters: tuple[Chapter, ...] = DEFAULT_CHAPTERS

    @property
    def total(self) -> int:
        return len(self.cards)


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


def _chapter(raw: dict) -> Chapter:
    return Chapter(code=str(raw.get("code", "")), name=str(raw.get("name", "") or raw.get("code", "")),
                   emoji=str(raw.get("emoji", "") or ""), decor=str(raw.get("decor", "") or ""))


def _load() -> CardSeries:
    try:
        data = json.loads(CONTENT_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    cards = tuple(sorted((_card(raw) for raw in data.get("cards", [])), key=lambda c: c.number))
    raw_chapters = data.get("chapters")
    chapters = (tuple(_chapter(c) for c in raw_chapters if c.get("code"))
                if isinstance(raw_chapters, list) and raw_chapters else DEFAULT_CHAPTERS)
    return CardSeries(int(data.get("series", 1)), data.get("name", ""), cards,
                      params_from_dict(data.get("params")), chapters)


def get_series() -> CardSeries:
    return _cached(CONTENT_PATH, "series", _load)


def clear_cache() -> None:
    _cache.clear()


def params() -> CardParams:
    """Les réglages des boosters (prix, taux, brillantes, pitié, pétales)."""
    return get_series().params


def chapters() -> list[Chapter]:
    """Les pages de l'album, dans l'ordre (seulement celles qui ont des cartes)."""
    series = get_series()
    used = {c.chapter for c in series.cards}
    return [c for c in series.chapters if c.code in used]


def get_chapter(code: str) -> Chapter:
    return next((c for c in get_series().chapters if c.code == code), Chapter(code, code))


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


def _art_candidates(card: CardDef) -> list[tuple[str, Path]]:
    """(origine, chemin) des images possibles d'une carte, par priorité."""
    candidates = [("carte", CARD_ART / f"{card.code}.png")]
    if card.category == "monstre":
        image = _mob_images().get(card.source, "")
        if image:
            candidates.append(("monstre", ASSETS / "mobs" / image))
    elif card.category == "personnage" and card.source:
        candidates.append(("portrait", ASSETS / "npcs" / f"{card.source}.png"))
    elif card.category == "boss" and card.source:
        # L'image PROPRE du boss (déposée sur le site, World Bosses) ; pas
        # celle qu'il emprunte à un monstre en attendant.
        candidates.append(("boss", ASSETS / "mobs" / f"boss_{card.source}.png"))
    candidates.append(("ebauche", DRAFT_ART / f"{card.code}.png"))
    return candidates


def art_path(card: CardDef) -> Path | None:
    """L'image de la carte (None : pas encore d'image)."""
    return next((p for _, p in _art_candidates(card) if p.is_file()), None)


def art_origin(card: CardDef) -> str:
    """D'où vient l'image : carte, monstre, portrait, ebauche ou aucune."""
    return next((origin for origin, p in _art_candidates(card) if p.is_file()), "aucune")


def own_art_path(card: CardDef) -> Path:
    """Où va l'image de l'auteur (celle qui passe avant tout)."""
    return CARD_ART / f"{card.code}.png"


def full_art_path(card: CardDef) -> Path | None:
    """L'illustration « pleine carte » de la brillante, si l'auteur en a fait une."""
    path = own_full_art_path(card)
    return path if path.is_file() else None


def own_full_art_path(card: CardDef) -> Path:
    return CARD_ART / f"{card.code}{FULL_ART_SUFFIX}.png"


def decor_path(chapter: str) -> Path | None:
    """Le décor du chapitre (derrière l'image des cartes), s'il existe."""
    decor = get_chapter(chapter).decor
    path = LANDSCAPES / decor if decor else None
    return path if path is not None and path.is_file() else None
