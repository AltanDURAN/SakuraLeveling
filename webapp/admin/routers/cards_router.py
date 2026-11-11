"""Admin : CARTES À COLLECTIONNER (`cards.json` + images `assets/cards`).

Demande de l'auteur (10/11/2026) : régler les boosters depuis le site (prix,
premier offert, taux, brillantes, légendaire garanti, pétales), gérer les
cartes (texte, rareté, chapitre, effet, images normale et pleine carte), les
chapitres de l'album et le dos des cartes, et voir où en est le serveur.

Le bot relit `cards.json` dès qu'il change (cache par date de modification) :
pas de redémarrage. Chaque enregistrement recrée aussi les OBJETS des cartes
en base (`seed_card_items`) : une carte ajoutée se tire tout de suite.
"""

from __future__ import annotations

import io
import logging
import re
import unicodedata
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from PIL import Image

from app.domain.services import card_service as cs
from app.infrastructure.cards import card_loader
from app.infrastructure.db.session import get_db_session
from app.shared.enums import ELEMENT_LABELS
from app.shared.image_tools import shrink
from webapp.admin import git_sync, json_writer, scene_helpers, uploads
from webapp.admin._shared import get_templates
from webapp.admin.auth import AdminUser, require_admin

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/cards", tags=["admin-cards"])

_FILE = "cards.json"
#: Côté le plus long d'une image de carte (la carte fait 360 × 504).
ART_MAX_SIDE = 1024
NAME_MAX, TITLE_MAX, FLAVOR_MAX = 40, 60, 240
BONUS_SLOTS = 3
SIMULATION_RUNS = 150
ART_KINDS = {"carte": "l'image de la carte", "fullart": "l'illustration pleine carte", "dos": "le dos"}
ORIGINS = {
    "carte": "🖼️ Image de la carte", "monstre": "👹 Image du monstre", "portrait": "👤 Portrait du personnage",
    "boss": "🐉 Image du boss",
    "ebauche": "✏️ Ébauche générée", "aucune": "❌ Aucune image",
}


# ------------------------------------------------------------------ données --
def _data() -> dict:
    data = json_writer.load_json(_FILE, {}) or {}
    data.setdefault("cards", [])
    return data


def _seed_items() -> None:
    """Les objets d'inventaire des cartes (normale et brillante) en base."""
    from app.infrastructure.db.seeders.seed_content import seed_card_items

    try:
        with get_db_session() as session:
            seed_card_items(session)
    except Exception:  # noqa: BLE001 - le contenu est écrit, la base suivra au prochain seed
        _logger.exception("objets des cartes non mis à jour en base")


def _save(data: dict) -> None:
    json_writer.atomic_write_json(_FILE, data)      # versionné sur git
    card_loader.clear_cache()
    _seed_items()


def _content_list(name: str, key: str) -> list[dict]:
    data = json_writer.load_json(name, []) or []
    if isinstance(data, dict):
        data = data.get(key, list(data.values()))
    return [d for d in data if isinstance(d, dict) and d.get("code")]


def _mobs() -> list[dict]:
    return sorted(_content_list("mobs.json", "mobs"), key=lambda m: (m.get("family", ""), m.get("name", "")))


def _bosses() -> list[dict]:
    return _content_list("boss_definitions.json", "bosses")


def _npcs() -> list[str]:
    folder = card_loader.ASSETS / "npcs"
    return sorted(p.stem for p in folder.glob("*.png")) if folder.is_dir() else []


def _chapters(data: dict) -> list[dict]:
    chapters = data.get("chapters")
    if isinstance(chapters, list) and chapters:
        return chapters
    return [{"code": c.code, "name": c.name, "emoji": c.emoji, "decor": c.decor} for c in cs.DEFAULT_CHAPTERS]


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _int(form, key: str, default: int | None = None) -> int | None:
    raw = str(form.get(key, "")).strip().replace(" ", "").replace(" ", "")
    if not raw:
        return default
    try:
        return int(float(raw.replace(",", ".")))
    except ValueError:
        return None


def _float(form, key: str, default: float | None = None) -> float | None:
    raw = str(form.get(key, "")).strip().replace(" ", "").replace(" ", "").replace(",", ".")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return None


def _holdings() -> dict[str, tuple[int, int, int]]:
    """carte → (joueurs qui l'ont, joueurs qui ont la brillante, exemplaires)."""
    from app.application.use_cases.cards import server_cards

    try:
        with get_db_session() as session:
            return server_cards(session).by_card
    except Exception:  # noqa: BLE001
        _logger.warning("cartes en circulation illisibles", exc_info=True)
        return {}


# ------------------------------------------------------------ la liste --
@router.get("", response_class=HTMLResponse)
async def cards_page(request: Request, saved: str = "", user: AdminUser = Depends(require_admin)):
    from app.application.use_cases.cards import server_cards
    from app.bot.rendering import card_render
    from app.infrastructure.db.repositories.player_repository import PlayerRepository

    card_loader.clear_cache()
    series = card_loader.get_series()
    stats = best = None
    with get_db_session() as session:
        try:
            stats = server_cards(session)
            if stats.best_album:
                profile = PlayerRepository(session).get_profile_by_player_id(stats.best_album[0])
                best = (profile.player.display_name if profile else "?", stats.best_album[1])
        except Exception:  # noqa: BLE001
            _logger.warning("état des cartes illisible", exc_info=True)
    rows = []
    for card in series.cards:
        owners, shiny_owners, copies = stats.by_card.get(card.code, (0, 0, 0)) if stats else (0, 0, 0)
        rows.append({
            "card": card, "effect": cs.effect_text(card), "chapter": card_loader.get_chapter(card.chapter),
            "origin": ORIGINS.get(card_loader.art_origin(card), ""),
            "fullart": card_loader.full_art_path(card) is not None,
            "owners": owners, "shiny_owners": shiny_owners, "copies": copies,
            "version": card_render.render_version(card),
        })
    counts = {r: sum(1 for c in series.cards if c.rarity == r) for r in cs.RARITIES}
    return get_templates().TemplateResponse(
        request, "admin/cards/list.html",
        context={"user": user, "series": series, "rows": rows, "stats": stats, "best": best, "saved": saved,
                 "counts": counts, "rarity_labels": cs.RARITY_LABELS, "rarity_emojis": cs.CARD_RARITY_EMOJIS,
                 "categories": cs.CATEGORIES, "chapters": card_loader.chapters()},
    )


# -------------------------------------------------------------- réglages --
def _params_from_form(form) -> tuple[cs.CardParams | None, list[str]]:
    errors = []
    values = {
        "booster_price": _int(form, "booster_price"), "brillante_pct": _float(form, "brillante_pct"),
        "pity_boosters": _int(form, "pity_boosters", 0), "brillante_petal_mult": _int(form, "brillante_petal_mult"),
        "craft_mult": _int(form, "craft_mult"),
    }
    for key, value in values.items():
        if value is None:
            errors.append(f"« {key} » doit être un nombre.")
    normal = {r: _float(form, f"normal_{r}", 0.0) for r in cs.RARITIES}
    hit = {r: _float(form, f"hit_{r}", 0.0) for r in cs.RARITIES}
    petals = {r: _int(form, f"petals_{r}", 0) for r in cs.RARITIES}
    if any(v is None for v in [*normal.values(), *hit.values(), *petals.values()]):
        errors.append("Les taux et les pétales sont des nombres.")
    if errors:
        return None, errors
    params = cs.CardParams(
        booster_price=values["booster_price"], first_free=bool(form.get("first_free")),
        normal_rates={r: v for r, v in normal.items() if v > 0}, hit_rates={r: v for r, v in hit.items() if v > 0},
        brillante_pct=values["brillante_pct"], pity_boosters=values["pity_boosters"],
        petals=petals, brillante_petal_mult=values["brillante_petal_mult"], craft_mult=values["craft_mult"],
    )
    return params, cs.validate_params(params)


def _settings(request: Request, user: AdminUser, *, params: cs.CardParams | None = None,
              errors: list[str] | None = None, saved: str = "", code: int = 200):
    from app.bot.rendering import card_render

    card_loader.clear_cache()
    series = card_loader.get_series()
    data = _data()
    used = {}
    for card in series.cards:
        used[card.chapter] = used.get(card.chapter, 0) + 1
    back = card_loader.BACK_FILE
    return get_templates().TemplateResponse(
        request, "admin/cards/settings.html", status_code=code,
        context={"user": user, "params": params or series.params, "series": series, "errors": errors or [],
                 "saved": saved, "rarities": cs.RARITIES, "rarity_labels": cs.RARITY_LABELS,
                 "rarity_emojis": cs.CARD_RARITY_EMOJIS, "booster_size": cs.BOOSTER_SIZE,
                 "chapters": _chapters(data), "chapter_cards": used, "decors": scene_helpers.list_backgrounds(),
                 "back_version": card_render._stamp(back)[1] if back.is_file() else 0,
                 "back_exists": back.is_file()},
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, saved: str = "", user: AdminUser = Depends(require_admin)):
    return _settings(request, user, saved=saved)


@router.post("/settings/params")
async def save_params(request: Request, user: AdminUser = Depends(require_admin)):
    form = await request.form()
    params, errors = _params_from_form(form)
    if errors:
        return _settings(request, user, params=params, errors=errors, code=400)
    data = _data()
    data["params"] = cs.params_to_dict(params)
    _save(data)
    _logger.info("Admin %s a réglé les boosters : %s", user.discord_id, data["params"])
    return RedirectResponse("/admin/cards/settings?saved=params", status_code=303)


@router.post("/settings/simulate", response_class=HTMLResponse)
async def simulate(request: Request, user: AdminUser = Depends(require_admin)):
    """Simulation d'un joueur seul avec les réglages DU FORMULAIRE (pas encore
    enregistrés) : boosters pour la moitié de l'album, l'album complet…"""
    form = await request.form()
    params, errors = _params_from_form(form)
    result = None
    if not errors:
        cards = card_loader.list_cards()
        result = await run_in_threadpool(cs.simulate_album, cards, params, runs=SIMULATION_RUNS)
    return get_templates().TemplateResponse(
        request, "admin/cards/_simulation.html",
        context={"user": user, "errors": errors, "sim": result, "params": params,
                 "free": 1 if params and params.first_free else 0},
    )


@router.post("/settings/series")
async def save_series(request: Request, user: AdminUser = Depends(require_admin)):
    form = await request.form()
    number = _int(form, "series")
    name = str(form.get("name", "")).strip()
    if number is None or number < 1 or not name or len(name) > 60:
        return _settings(request, user, errors=["La série a un numéro (1 ou plus) et un nom (60 caractères au plus)."],
                         code=400)
    data = _data()
    data["series"], data["name"] = number, name
    _save(data)
    return RedirectResponse("/admin/cards/settings?saved=series", status_code=303)


def _chapter_from_form(form, code: str) -> tuple[dict | None, list[str]]:
    name = str(form.get("name", "")).strip()
    decor = str(form.get("decor", "")).strip()
    errors = []
    if not name or len(name) > 40:
        errors.append("Un chapitre a un nom (40 caractères au plus).")
    if decor and decor not in scene_helpers.list_backgrounds():
        errors.append(f"Décor inconnu : « {decor} ».")
    if errors:
        return None, errors
    return {"code": code, "name": name, "emoji": str(form.get("emoji", "")).strip()[:8], "decor": decor}, []


def _move(items: list, index: int, position: int | None) -> list:
    if position is None:
        return items
    item = items.pop(index)
    items.insert(max(0, min(position - 1, len(items))), item)
    return items


@router.post("/settings/chapters")
async def add_chapter(request: Request, user: AdminUser = Depends(require_admin)):
    form = await request.form()
    data = _data()
    chapters = _chapters(data)
    code = _slug(str(form.get("code", "")).strip() or str(form.get("name", "")))
    if not code:
        return _settings(request, user, errors=["Un chapitre a un nom."], code=400)
    if any(c.get("code") == code for c in chapters):
        return _settings(request, user, errors=[f"Le chapitre « {code} » existe déjà."], code=400)
    entry, errors = _chapter_from_form(form, code)
    if errors:
        return _settings(request, user, errors=errors, code=400)
    chapters.append(entry)
    data["chapters"] = chapters
    _save(data)
    _logger.info("Admin %s a ajouté le chapitre %s", user.discord_id, code)
    return RedirectResponse("/admin/cards/settings?saved=chapters", status_code=303)


@router.post("/settings/chapters/{code}")
async def edit_chapter(code: str, request: Request, user: AdminUser = Depends(require_admin)):
    form = await request.form()
    data = _data()
    chapters = _chapters(data)
    index = next((i for i, c in enumerate(chapters) if c.get("code") == code), None)
    if index is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Chapitre `{code}` introuvable.")
    entry, errors = _chapter_from_form(form, code)
    if errors:
        return _settings(request, user, errors=errors, code=400)
    chapters[index] = entry
    data["chapters"] = _move(chapters, index, _int(form, "position"))
    _save(data)
    return RedirectResponse("/admin/cards/settings?saved=chapters", status_code=303)


@router.post("/settings/chapters/{code}/delete")
async def delete_chapter(code: str, request: Request, user: AdminUser = Depends(require_admin)):
    data = _data()
    chapters = _chapters(data)
    if not any(c.get("code") == code for c in chapters):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Chapitre `{code}` introuvable.")
    if any(c.get("chapter") == code for c in data["cards"]):
        return _settings(request, user, errors=["Ce chapitre a encore des cartes : change-les de chapitre d'abord."],
                         code=400)
    data["chapters"] = [c for c in chapters if c.get("code") != code]
    _save(data)
    return RedirectResponse("/admin/cards/settings?saved=chapters", status_code=303)


# ---------------------------------------------------------------- images --
def _store_image(data: bytes, filename: str, dest: Path) -> None:
    """Enregistre une image envoyée en PNG (réduite à `ART_MAX_SIDE`)."""
    if not data:
        raise uploads.UploadError("Fichier vide.")
    if len(data) > uploads.MAX_UPLOAD_BYTES:
        raise uploads.UploadError(f"Fichier trop volumineux (max {uploads.MAX_UPLOAD_BYTES // (1024 * 1024)} Mo).")
    ext = Path(filename or "").suffix.lower()
    if ext not in uploads.ALLOWED_EXTENSIONS:
        raise uploads.UploadError(f"Type non autorisé ({ext or 'inconnu'}) : {', '.join(sorted(uploads.ALLOWED_EXTENSIONS))}.")
    try:
        with Image.open(io.BytesIO(data)) as source:
            image = source.convert("RGBA")
    except (OSError, ValueError):
        raise uploads.UploadError("Image illisible.") from None
    image = shrink(image, ART_MAX_SIDE)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.tmp")
    image.save(tmp, format="PNG", optimize=True)
    tmp.replace(dest)


def _repo_path(path: Path) -> str:
    try:
        return path.relative_to(card_loader.ASSETS.parent).as_posix()
    except ValueError:                           # hors du dépôt (tests)
        return path.as_posix()


def _art_target(code: str, kind: str) -> Path:
    if kind == "dos":
        return card_loader.BACK_FILE
    card = card_loader.get_card(code)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Carte `{code}` introuvable.")
    return card_loader.own_full_art_path(card) if kind == "fullart" else card_loader.own_art_path(card)


async def _upload(request: Request, code: str, kind: str) -> str:
    """Enregistre l'image envoyée ; renvoie l'erreur (vide = c'est fait)."""
    form = await request.form()
    upload = form.get("image")
    if upload is None or not getattr(upload, "filename", ""):
        return "Choisis une image."
    target = _art_target(code, kind)
    try:
        _store_image(await upload.read(), upload.filename, target)
    except uploads.UploadError as exc:
        return str(exc)
    await run_in_threadpool(git_sync.push_content, [_repo_path(target)], f"admin: {ART_KINDS[kind]} de {code or 'la série'}")
    return ""


@router.post("/settings/back")
async def upload_back(request: Request, user: AdminUser = Depends(require_admin)):
    error = await _upload(request, "", "dos")
    if error:
        return _settings(request, user, errors=[error], code=400)
    _logger.info("Admin %s a changé le dos des cartes", user.discord_id)
    return RedirectResponse("/admin/cards/settings?saved=back", status_code=303)


@router.get("/back.png")
def back_png(v: str = "", user: AdminUser = Depends(require_admin)):
    from app.bot.rendering import card_render

    buffer = io.BytesIO()
    card_render.card_back((240, 336)).save(buffer, format="PNG")
    return Response(buffer.getvalue(), media_type="image/png", headers={"Cache-Control": "no-cache"})


# ------------------------------------------------------------ une carte --
def _form_context(request: Request, user: AdminUser, entry: dict, *, is_new: bool, errors: list[str] | None = None,
                  saved: str = "", code: int = 200):
    from app.bot.rendering import card_render

    data = _data()
    card = card_loader.get_card(entry.get("code", "")) if not is_new else None
    images = {}
    if card is not None:
        origin = card_loader.art_origin(card)
        images = {
            "origin": ORIGINS.get(origin, ""), "own": card_loader.own_art_path(card).is_file(),
            "fullart": card_loader.full_art_path(card) is not None,
            "path": _repo_path(card_loader.art_path(card)) if card_loader.art_path(card) else "",
            "version": card_render.render_version(card), "shiny_version": card_render.render_version(card, True),
        }
    holdings = _holdings().get(entry.get("code", ""), (0, 0, 0)) if card is not None else (0, 0, 0)
    effect = entry.get("effect") or {}
    bonuses = [(k, v) for k, v in effect.items() if k in cs.BONUS_TEXTS]
    bonuses += [("", "")] * (BONUS_SLOTS - len(bonuses))
    return get_templates().TemplateResponse(
        request, "admin/cards/form.html", status_code=code,
        context={"user": user, "entry": entry, "effect": effect, "bonuses": bonuses[:BONUS_SLOTS], "is_new": is_new,
                 "errors": errors or [], "saved": saved, "images": images, "holdings": holdings,
                 "count": len(data["cards"]), "rarities": cs.RARITIES, "rarity_labels": cs.RARITY_LABELS,
                 "rarity_emojis": cs.CARD_RARITY_EMOJIS, "categories": cs.CATEGORIES,
                 "chapters": _chapters(data), "elements": ELEMENT_LABELS, "mobs": _mobs(), "bosses": _bosses(),
                 "npcs": _npcs(), "bonus_texts": cs.BONUS_TEXTS},
    )


def _entry_from_form(form, code: str) -> tuple[dict, list[str]]:
    errors = []
    name = str(form.get("name", "")).strip()
    title = str(form.get("title", "")).strip()
    flavor = re.sub(r"\s+", " ", str(form.get("flavor", ""))).strip()
    source = str(form.get("source", "")).strip()
    if not name or len(name) > NAME_MAX:
        errors.append(f"Le nom va de 1 à {NAME_MAX} caractères.")
    if len(title) > TITLE_MAX:
        errors.append(f"Le sous-titre fait {TITLE_MAX} caractères au plus.")
    if len(flavor) > FLAVOR_MAX:
        errors.append(f"Le texte d'ambiance fait {FLAVOR_MAX} caractères au plus (il en tient deux lignes sur la carte).")
    kind = str(form.get("effect_type", "monstre"))
    if kind == "monstre":
        effect = {"type": "monstre", "mob": str(form.get("mob", "")).strip() or source,
                  "damage_pct": _int(form, "damage_pct", 0), "drop_pct": _int(form, "drop_pct", 0)}
    elif kind == "boss":
        guards = [g for g in form.getlist("guards") if str(g).strip()] if hasattr(form, "getlist") else []
        effect = {"type": "boss", "boss": str(form.get("boss", "")).strip() or source,
                  "guards": [str(g).strip() for g in guards], "damage_pct": _int(form, "boss_damage_pct", 0)}
    else:
        effect = {"type": "bonus"}
        for i in range(BONUS_SLOTS):
            key = str(form.get(f"bonus_key_{i}", "")).strip()
            if key:
                effect[key] = _int(form, f"bonus_value_{i}", 0)
    if any(v is None for v in effect.values()):
        errors.append("Les valeurs de l'effet sont des nombres entiers.")
    entry = {
        "number": _int(form, "number", 0) or 0, "code": code, "name": name, "title": title,
        "category": str(form.get("category", "")), "rarity": str(form.get("rarity", "")),
        "chapter": str(form.get("chapter", "")), "element": str(form.get("element", "")).strip(),
        "source": source, "effect": effect, "flavor": flavor,
    }
    return entry, errors


def _place(cards: list[dict], entry: dict, position: int) -> list[dict]:
    """La carte à la place `position` ; les numéros restent 1, 2, 3…"""
    others = [c for c in sorted(cards, key=lambda c: c.get("number", 0)) if c.get("code") != entry["code"]]
    others.insert(max(0, min(position - 1, len(others))), entry)
    for number, card in enumerate(others, 1):
        card["number"] = number
    return others


def _problems(cards: list[dict], data: dict) -> list[str]:
    mobs = {m["code"] for m in _mobs()}
    bosses = {b["code"] for b in _bosses()}
    defs = [card_loader._card(c) for c in cards]
    return cs.validate(defs, mobs, bosses, chapters={c.get("code") for c in _chapters(data)})


@router.get("/new", response_class=HTMLResponse)
async def new_card(request: Request, user: AdminUser = Depends(require_admin)):
    data = _data()
    entry = {"number": len(data["cards"]) + 1, "code": "", "name": "", "title": "", "category": "monstre",
             "rarity": "common", "chapter": _chapters(data)[0]["code"], "element": "", "source": "",
             "effect": {"type": "monstre", "damage_pct": 3, "drop_pct": 5}, "flavor": ""}
    return _form_context(request, user, entry, is_new=True)


@router.post("/new")
async def create_card(request: Request, user: AdminUser = Depends(require_admin)):
    form = await request.form()
    data = _data()
    code = _slug(str(form.get("code", "")).strip() or str(form.get("name", "")))
    entry, errors = _entry_from_form(form, code)
    if not code:
        errors.append("Une carte a un code (minuscules, chiffres et _).")
    elif any(c.get("code") == code for c in data["cards"]):
        errors.append(f"Le code « {code} » est déjà pris.")
    if not errors:
        cards = _place(data["cards"], entry, entry["number"] or len(data["cards"]) + 1)
        errors = _problems(cards, data)
    if errors:
        return _form_context(request, user, entry, is_new=True, errors=errors, code=400)
    data["cards"] = cards
    _save(data)
    _logger.info("Admin %s a créé la carte %s", user.discord_id, code)
    return RedirectResponse(f"/admin/cards/{code}?saved=created", status_code=303)


def _preview_png(card: cs.CardDef) -> bytes:
    """Les deux faces côte à côte : normale | brillante (sans passer par la
    mémoire des faces : un aperçu n'est pas une carte)."""
    from app.bot.rendering import card_render

    normal = card_render._normal_face(card)
    shiny = card_render._brillante_face(card, card_render.STILL_PHASE, card_render._full_art(card))
    sheet = Image.new("RGBA", (card_render.W * 2 + 16, card_render.H), (0, 0, 0, 0))
    sheet.alpha_composite(normal, (0, 0))
    sheet.alpha_composite(shiny, (card_render.W + 16, 0))
    buffer = io.BytesIO()
    sheet.save(buffer, format="PNG")
    return buffer.getvalue()


@router.post("/preview")
async def preview(request: Request, user: AdminUser = Depends(require_admin)):
    """Aperçu du formulaire, AVANT d'enregistrer (les images déjà envoyées
    comptent ; l'image d'un monstre suit la « source » choisie)."""
    form = await request.form()
    code = (str(form.get("current_code", "")).strip()
            or _slug(str(form.get("code", "")).strip() or str(form.get("name", ""))) or "apercu")
    entry, _ = _entry_from_form(form, code)
    entry["number"] = entry["number"] or 1
    entry["name"] = entry["name"] or "Sans nom"
    entry["effect"] = {k: (0 if v is None else v) for k, v in entry["effect"].items()}
    if entry["rarity"] not in cs.RARITIES:
        entry["rarity"] = "common"
    png = await run_in_threadpool(_preview_png, card_loader._card(entry))
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/{code}", response_class=HTMLResponse)
async def edit_card(code: str, request: Request, saved: str = "", user: AdminUser = Depends(require_admin)):
    card_loader.clear_cache()
    entry = next((c for c in _data()["cards"] if c.get("code") == code), None)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Carte `{code}` introuvable.")
    return _form_context(request, user, entry, is_new=False, saved=saved)


@router.post("/{code}")
async def save_card(code: str, request: Request, user: AdminUser = Depends(require_admin)):
    form = await request.form()
    data = _data()
    old = next((c for c in data["cards"] if c.get("code") == code), None)
    if old is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Carte `{code}` introuvable.")
    entry, errors = _entry_from_form(form, code)
    owners = _holdings().get(code, (0, 0, 0))[0]
    if owners and (old.get("rarity") == "mythic") != (entry["rarity"] == "mythic"):
        errors.append("Des joueurs ont cette carte : elle ne peut pas devenir (ou cesser d'être) une mythique, "
                      "qui n'existe qu'en brillante.")
    if not errors:
        cards = _place(data["cards"], entry, entry["number"] or old.get("number", 1))
        errors = _problems(cards, data)
    if errors:
        return _form_context(request, user, entry, is_new=False, errors=errors, code=400)
    data["cards"] = cards
    _save(data)
    _logger.info("Admin %s a modifié la carte %s", user.discord_id, code)
    return RedirectResponse(f"/admin/cards/{code}?saved=card", status_code=303)


def _references(code: str) -> list[str]:
    """Ce qui retient une carte en jeu (on ne supprime pas une carte détenue)."""
    from sqlalchemy import func, select

    from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel
    from app.infrastructure.db.models.item_model import ItemDefinitionModel
    from app.infrastructure.db.models.marketplace_listing_model import MarketplaceListingModel
    from app.infrastructure.db.models.trade_model import TradeItemModel, TradeModel

    item_codes = [card_loader.item_code(code, False), card_loader.item_code(code, True)]
    reasons = []
    with get_db_session() as session:
        ids = list(session.execute(select(ItemDefinitionModel.id).where(ItemDefinitionModel.code.in_(item_codes)))
                   .scalars())
        if not ids:
            return []
        owned = session.execute(select(func.coalesce(func.sum(PlayerInventoryItemModel.quantity), 0)).where(
            PlayerInventoryItemModel.item_definition_id.in_(ids))).scalar_one()
        if owned:
            reasons.append(f"{owned} exemplaire(s) dans les inventaires")
        listed = session.execute(select(func.count()).select_from(MarketplaceListingModel).where(
            MarketplaceListingModel.item_definition_id.in_(ids), MarketplaceListingModel.status == "active")).scalar_one()
        if listed:
            reasons.append(f"{listed} annonce(s) à la brocante")
        traded = session.execute(select(func.count()).select_from(TradeItemModel).join(
            TradeModel, TradeModel.id == TradeItemModel.trade_id).where(
            TradeItemModel.item_definition_id.in_(ids), TradeModel.status == "pending")).scalar_one()
        if traded:
            reasons.append(f"{traded} échange(s) en cours")
    return reasons


def _drop_items(code: str) -> None:
    """Retire les objets d'une carte supprimée (s'ils ne servent plus nulle part)."""
    from sqlalchemy import delete

    from app.infrastructure.db.models.item_model import ItemDefinitionModel

    codes = [card_loader.item_code(code, False), card_loader.item_code(code, True)]
    try:
        with get_db_session(atomic=True) as session:
            session.execute(delete(ItemDefinitionModel).where(ItemDefinitionModel.code.in_(codes)))
    except Exception:  # noqa: BLE001 - encore référencés quelque part : ils restent, sans carte
        _logger.warning("objets de la carte %s gardés en base", code, exc_info=True)


@router.post("/{code}/delete")
async def delete_card(code: str, request: Request, user: AdminUser = Depends(require_admin)):
    data = _data()
    entry = next((c for c in data["cards"] if c.get("code") == code), None)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Carte `{code}` introuvable.")
    reasons = await run_in_threadpool(_references, code)
    if reasons:
        return _form_context(request, user, entry, is_new=False, code=400, errors=[
            "Impossible de supprimer une carte que des joueurs ont : " + ", ".join(reasons) + "."])
    remaining = sorted((c for c in data["cards"] if c.get("code") != code), key=lambda c: c.get("number", 0))
    for number, card in enumerate(remaining, 1):
        card["number"] = number
    data["cards"] = remaining
    _save(data)
    await run_in_threadpool(_drop_items, code)
    _logger.info("Admin %s a supprimé la carte %s", user.discord_id, code)
    return RedirectResponse("/admin/cards?saved=deleted", status_code=303)


@router.post("/{code}/art/{kind}")
async def upload_art(code: str, kind: str, request: Request, user: AdminUser = Depends(require_admin)):
    if kind not in ("carte", "fullart"):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    error = await _upload(request, code, kind)
    if error:
        entry = next((c for c in _data()["cards"] if c.get("code") == code), None) or {"code": code}
        return _form_context(request, user, entry, is_new=False, errors=[error], code=400)
    _logger.info("Admin %s a envoyé %s de %s", user.discord_id, ART_KINDS[kind], code)
    return RedirectResponse(f"/admin/cards/{code}?saved=art", status_code=303)


@router.post("/{code}/art/{kind}/delete")
async def delete_art(code: str, kind: str, request: Request, user: AdminUser = Depends(require_admin)):
    if kind not in ("carte", "fullart"):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    target = _art_target(code, kind)
    if target.is_file():
        target.unlink()
        await run_in_threadpool(git_sync.push_content, [_repo_path(target)],
                                f"admin: {ART_KINDS[kind]} de {code} retirée")
    return RedirectResponse(f"/admin/cards/{code}?saved=art", status_code=303)


# --------------------------------------------------------------- rendus --
def _image_response(data: bytes, media_type: str, cached: bool) -> Response:
    headers = {"Cache-Control": "private, max-age=86400" if cached else "no-cache"}
    return Response(data, media_type=media_type, headers=headers)


@router.get("/{code}/face.png")
def face_png(code: str, brillante: int = 0, w: int = 0, v: str = "", user: AdminUser = Depends(require_admin)):
    """La face de la carte telle que le bot la dessine (`v` : empreinte, pour le cache)."""
    from app.bot.rendering import card_render

    card = card_loader.get_card(code)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Carte `{code}` introuvable.")
    data = card_render.card_png(card, bool(brillante))
    if 0 < w < card_render.W:
        buffer = io.BytesIO()
        image = Image.open(io.BytesIO(data))
        image.resize((w, round(w * card_render.H / card_render.W)), Image.LANCZOS).save(buffer, format="PNG")
        data = buffer.getvalue()
    return _image_response(data, "image/png", bool(v))


@router.get("/{code}/holo.gif")
def holo_gif(code: str, v: str = "", user: AdminUser = Depends(require_admin)):
    """La brillante animée (comme dans l'album du bot)."""
    from app.bot.rendering import card_render

    card = card_loader.get_card(code)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Carte `{code}` introuvable.")
    return _image_response(card_render.card_gif(card), "image/gif", bool(v))
