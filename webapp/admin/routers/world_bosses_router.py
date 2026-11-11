"""Admin : WORLD BOSS (boss_definitions.json) — galerie, images, création,
édition, suppression. Les capacités se recalculent avec
`scripts/restat_bosses.py`. Découpé de `content_router.py` le 26/10/2026
(roadmap N6).

Images (11/11/2026, demande de l'auteur : « que je dépose les images des
boss ») : la page montre chaque boss tel que les joueurs le voient — une
image de la VIDÉO de l'assaut et la BANNIÈRE du raid, rendues par le code du
bot — et l'on y GLISSE l'image du boss (détourée si elle est sur fond blanc,
rangée en `assets/mobs/boss_<code>.png`) ou son ARÈNE (le décor de la vidéo,
`assets/landscapes/arene_<code>.png` ; sinon la salle commune
`arene_boss.png`). Le fichier des boss et le boss en cours (base) suivent
tout de suite : pas de redémarrage du bot.
"""

from __future__ import annotations

import io
import logging
import math
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from PIL import Image
from sqlalchemy import update

from app.bot.rendering import boss_fight_video as bfv
from app.bot.rendering import fight_scene
from app.infrastructure.db.models.world_boss_model import WorldBossModel
from app.infrastructure.db.session import get_db_session
from app.shared.enums import ALL_ELEMENTS, ELEMENT_EMOJIS, ELEMENT_LABELS
from app.shared.image_tools import MOB_MAX_SIDE, cut_out_white, has_white_background, shrink
from webapp.admin import git_sync, scene_helpers
from webapp.admin._shared import get_templates
from webapp.admin.auth import AdminUser, require_admin
from webapp.admin.json_writer import append_to_list, load_json as _writer_load
from webapp.admin.routers._content_common import _load_json, _parse_int, _parse_kv_pairs, _fmt_kv_pairs, _delete_from_list
from webapp.admin.uploads import MAX_UPLOAD_BYTES

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin-world-bosses"])

_FILE = "boss_definitions.json"
#: PV du boss sur les aperçus (entamé : on voit la barre et ses phases).
PREVIEW_HP_PCT = 0.62
#: En dessous, une arène en paysage est trop rognée : on prévient.
ARENA_VISIBLE_WARN = 0.75
#: Au-delà de cet agrandissement, l'arène devient floue : on prévient.
ARENA_UPSCALE_WARN = 1.15


def own_image_name(code: str) -> str:
    """L'image PROPRE d'un boss (celle que dépose l'auteur)."""
    return f"boss_{code}.png"


def _mobs_dir() -> Path:
    return fight_scene.MOBS_ASSETS_DIR          # là où le bot lit les images (patchable en test)


def _arena_dir() -> Path:
    return bfv.LANDSCAPES_ASSETS_DIR


def _mtime(path: Path | None) -> int:
    try:
        return int(path.stat().st_mtime) if path is not None else 0
    except OSError:
        return 0


def _bosses() -> list[dict]:
    data = _load_json(_FILE) or []
    return sorted(data, key=lambda b: (int(b.get("level", 0) or 0), b.get("name", "")))


def _boss(code: str) -> dict | None:
    return next((b for b in _load_json(_FILE) or [] if b.get("code") == code), None)


def _mob_names_by_image() -> dict[str, str]:
    raw = _writer_load("mobs.json", default=[]) or []
    mobs = raw if isinstance(raw, list) else raw.get("mobs", [])
    return {m.get("image_name"): m.get("name", "") for m in mobs if m.get("image_name")}


def _card_codes() -> set[str]:
    raw = _writer_load("cards.json", default={}) or {}
    return {c.get("code") for c in raw.get("cards", [])} if isinstance(raw, dict) else set()


def _guards_label(guards: list[dict]) -> str:
    counts: dict[str, int] = {}
    for g in guards or []:
        counts[g.get("name", "Garde")] = counts.get(g.get("name", "Garde"), 0) + 1
    return " · ".join(f"{name} ×{n}" if n > 1 else name for name, n in counts.items())


ELEMENT_CODES = [e.value for e in ALL_ELEMENTS]


def _element_label(element: str) -> str:
    return f"{ELEMENT_EMOJIS.get(element, '')} {ELEMENT_LABELS.get(element, element)}".strip() if element else ""


def elements() -> list[dict]:
    """Les 8 éléments, pour choisir la teinte des aperçus."""
    return [{"code": e, "emoji": ELEMENT_EMOJIS.get(e, ""), "label": ELEMENT_LABELS.get(e, e)}
            for e in ELEMENT_CODES]


def _live_boss() -> tuple[str, str]:
    """(code, élément) du boss en cours — son élément a été tiré à son
    apparition. ("", "") s'il n'y en a pas (ou pas de base : démo)."""
    try:
        from app.infrastructure.db.repositories.world_boss_repository import WorldBossRepository
        with get_db_session() as session:
            boss = WorldBossRepository(session).get_active()
            return (boss.code, boss.element or "") if boss is not None else ("", "")
    except Exception:  # noqa: BLE001
        return "", ""


def _preview_element(b: dict, requested: str = "", live: tuple[str, str] | None = None) -> str:
    """La teinte d'un aperçu : celle demandée, sinon l'élément imposé par la
    fiche, sinon celui du boss en cours, sinon le premier élément."""
    if requested in ELEMENT_CODES:
        return requested
    forced = b.get("element", "") or ""
    if forced in ELEMENT_CODES:
        return forced
    live_code, live_element = live if live is not None else _live_boss()
    if live_code == b.get("code") and live_element in ELEMENT_CODES:
        return live_element
    return ELEMENT_CODES[0]


def _zone_arenas(code: str) -> dict[str, str]:
    out = {}
    for element in ELEMENT_CODES:
        path = bfv.arena_source(code, element)[1]
        if path.is_file():
            out[element] = f"/assets/landscapes/{path.name}?v={_mtime(path)}"
    return out


def _state(b: dict, mob_names: dict[str, str] | None = None, cards: set[str] | None = None,
           live: tuple[str, str] | None = None) -> dict:
    """Ce que la page montre d'un boss : son image, son arène, d'où elles viennent."""
    code, element = b.get("code", ""), b.get("element", "") or ""
    live = live if live is not None else _live_boss()
    live_element = live[1] if live[0] == code else ""
    preview = _preview_element(b, live=live)
    image = b.get("image_name", "") or ""
    image_path = _mobs_dir() / image if image else None
    has_image = bool(image_path and image_path.is_file())
    if not has_image:
        image_origin = "aucune"
    elif image == own_image_name(code):
        image_origin = "propre"
    else:
        image_origin = "empruntee"
    arena_origin, arena_path = bfv.arena_source(code, preview)
    names = mob_names if mob_names is not None else _mob_names_by_image()
    version = f"{_mtime(image_path)}-{_mtime(arena_path)}"
    return {
        "code": code, "name": b.get("name", code), "level": int(b.get("level", 0) or 0),
        "tier": b.get("tier", ""), "element": element,
        # Vide = tiré au hasard à chaque apparition (11/11/2026, décision de l'auteur).
        "element_label": _element_label(element) or "🎲 Au hasard à chaque apparition",
        "live_element": live_element, "live_label": _element_label(live_element),
        "preview_element": preview,
        "guards": _guards_label(b.get("guards") or []),
        "image": image, "image_origin": image_origin,
        "image_url": f"/assets/mobs/{image}?v={_mtime(image_path)}" if has_image else "",
        "borrowed_from": names.get(image, "") if image_origin == "empruntee" else "",
        "arena_origin": arena_origin, "arena_name": arena_path.name,
        "arena_url": f"/assets/landscapes/{arena_path.name}?v={_mtime(arena_path)}" if arena_path.is_file() else "",
        # Sans arène, le décor de repli dépend de l'élément : un par teinte d'aperçu.
        "zone_arenas": _zone_arenas(code) if arena_origin == bfv.ARENA_ZONE else {},
        "version": version,
        "edit_url": f"/admin/world-bosses/{code}/edit",
        "card_url": f"/admin/cards/{code}" if code in (cards if cards is not None else _card_codes()) else "",
    }


def _common_arena() -> dict:
    path = _arena_dir() / bfv.COMMON_ARENA
    return {"exists": path.is_file(),
            "url": f"/assets/landscapes/{bfv.COMMON_ARENA}?v={_mtime(path)}" if path.is_file() else ""}


@router.get("/world-bosses", response_class=HTMLResponse)
async def world_bosses_list(request: Request, user: AdminUser = Depends(require_admin)):
    names, cards = _mob_names_by_image(), _card_codes()
    live = _live_boss()
    states = [_state(b, names, cards, live) for b in _bosses()]
    return get_templates().TemplateResponse(
        request, "admin/world_bosses/list.html",
        context={"user": user, "bosses": states, "common": _common_arena(), "elements": elements(),
                 "max_mb": MAX_UPLOAD_BYTES // (1024 * 1024)},
    )


# ------------------------------------------------------------------ images --
def _open(data: bytes) -> Image.Image:
    if not data:
        raise ValueError("Aucune image reçue.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"Image trop lourde ({len(data) // (1024 * 1024)} Mo, "
                         f"max {MAX_UPLOAD_BYTES // (1024 * 1024)} Mo).")
    try:
        with Image.open(io.BytesIO(data)) as source:
            source.seek(0)
            return source.convert("RGBA")
    except (OSError, ValueError, EOFError):
        raise ValueError("Image illisible (formats acceptés : PNG, JPG, WebP, GIF).") from None


def prepare_boss_image(image: Image.Image) -> tuple[Image.Image, list[str]]:
    """L'image d'un boss telle qu'on la range : détourée si elle est sur fond
    blanc, recadrée sur le personnage, au plus `MOB_MAX_SIDE` px."""
    notes: list[str] = []
    image = shrink(image.convert("RGBA"), 2 * MOB_MAX_SIDE)
    if has_white_background(image):
        image = cut_out_white(image)
        notes.append("Fond blanc retiré.")
    box = image.getchannel("A").getbbox()
    if box and box != (0, 0, *image.size):
        image = image.crop(box)
    image = shrink(image, MOB_MAX_SIDE)
    if image.getchannel("A").getextrema()[0] == 255:
        notes.append("⚠️ Pas de fond transparent : le boss apparaîtra dans un rectangle. "
                     "Dépose de préférence un PNG détouré.")
    return image, notes


def prepare_arena(image: Image.Image) -> tuple[Image.Image, list[str]]:
    """L'arène telle qu'on la range : réduite juste assez pour couvrir le
    cadre de la vidéo (portrait, `FRAME_W` × `FRAME_H`), jamais rognée ici."""
    notes: list[str] = []
    image = image.convert("RGB")
    w, h = image.size
    scale = max(fight_scene.FRAME_W / w, fight_scene.FRAME_H / h)
    if scale < 1:
        image = image.resize((math.ceil(w * scale), math.ceil(h * scale)), Image.LANCZOS)
    frame_ratio = fight_scene.FRAME_W / fight_scene.FRAME_H
    visible = min(frame_ratio / (w / h), (w / h) / frame_ratio)
    if visible < ARENA_VISIBLE_WARN:
        notes.append(f"⚠️ La vidéo est en portrait (4:5) : seul le centre de l'image se voit "
                     f"(~{round(visible * 100)} %).")
    if scale > ARENA_UPSCALE_WARN:
        notes.append(f"⚠️ Image petite ({w} × {h}) : elle sera agrandie, donc un peu floue "
                     f"(idéal : au moins {fight_scene.FRAME_W} × {fight_scene.FRAME_H}).")
    return image, notes


def _write_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    image.save(tmp, "PNG", compress_level=6)
    tmp.replace(path)


def _sync_instances(code: str, image_name: str) -> None:
    """Le boss en cours (et l'historique) prend la nouvelle image tout de
    suite : la bannière et la vidéo lisent l'instance en base."""
    try:
        with get_db_session(atomic=True) as session:
            session.execute(update(WorldBossModel).where(WorldBossModel.code == code)
                            .values(image_name=image_name))
    except Exception:  # noqa: BLE001 — base absente (démo) : le fichier suffit
        _logger.warning("image du boss %s non reportée en base", code, exc_info=True)


def _rename_instances(code: str, name: str) -> None:
    """Un boss renommé : le boss en cours et l'historique prennent le nouveau nom."""
    try:
        with get_db_session(atomic=True) as session:
            session.execute(update(WorldBossModel).where(WorldBossModel.code == code).values(name=name))
    except Exception:  # noqa: BLE001
        _logger.warning("nom du boss %s non reporté en base", code, exc_info=True)


def _store(code: str | None, slot: str, data: bytes) -> list[str]:
    """Range l'image (`slot` : boss | arena ; `code` None = salle commune)
    et renvoie les remarques. Lève ValueError si l'image est refusée."""
    image = _open(data)
    if slot == "boss":
        ready, notes = prepare_boss_image(image)
        name = own_image_name(code)
        _write_png(ready, _mobs_dir() / name)
        if (_boss(code) or {}).get("image_name") != name:
            from webapp.admin.json_writer import find_in_list_by_key, update_in_list_by_key
            entry = find_in_list_by_key(_FILE, code)
            if entry is not None:
                update_in_list_by_key(_FILE, code, {**entry, "image_name": name})
        _sync_instances(code, name)
        git_sync.push_content([f"assets/mobs/{name}"], f"admin: image du boss {code}")
        return notes
    ready, notes = prepare_arena(image)
    name = bfv.own_arena_name(code) if code else bfv.COMMON_ARENA
    _write_png(ready, _arena_dir() / name)
    git_sync.push_content([f"assets/landscapes/{name}"],
                          f"admin: arène du boss {code}" if code else "admin: salle commune des boss")
    return notes


async def _upload(request: Request, code: str | None, slot: str):
    form = await request.form()
    upload = form.get("image")
    data = await upload.read() if upload is not None and hasattr(upload, "read") else b""
    try:
        notes = await run_in_threadpool(_store, code, slot, data)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return {"ok": True, "notes": notes, **_after_change(code)}


def _after_change(code: str | None) -> dict:
    """La réponse d'un dépôt : le boss modifié, ou TOUS les boss quand la
    salle commune change (elle est l'arène de ceux qui n'ont pas la leur)."""
    if code:
        return {"common": _common_arena(), "boss": _state(_boss(code))}
    names, cards, live = _mob_names_by_image(), _card_codes(), _live_boss()
    return {"common": _common_arena(), "bosses": [_state(b, names, cards, live) for b in _bosses()]}


@router.post("/world-bosses/arena-commune")
async def common_arena_upload(request: Request, user: AdminUser = Depends(require_admin)):
    """La salle commune : l'arène de tout boss qui n'a pas la sienne."""
    return await _upload(request, None, "arena")


@router.post("/world-bosses/arena-commune/delete")
async def common_arena_delete(user: AdminUser = Depends(require_admin)):
    path = _arena_dir() / bfv.COMMON_ARENA
    if path.is_file():
        path.unlink()
        await run_in_threadpool(git_sync.push_content, [f"assets/landscapes/{bfv.COMMON_ARENA}"],
                                "admin: salle commune des boss retirée")
    return {"ok": True, **_after_change(None)}


@router.post("/world-bosses/{code}/image")
async def boss_image_upload(code: str, request: Request, user: AdminUser = Depends(require_admin)):
    """Dépose l'image du boss (`slot=boss`) ou son arène (`slot=arena`)."""
    if _boss(code) is None:
        return JSONResponse({"ok": False, "error": f"Boss `{code}` introuvable."}, status_code=404)
    slot = str((await request.form()).get("slot") or "boss")
    if slot not in ("boss", "arena"):
        return JSONResponse({"ok": False, "error": "Emplacement inconnu."}, status_code=400)
    return await _upload(request, code, slot)


@router.post("/world-bosses/{code}/arena/delete")
async def boss_arena_delete(code: str, user: AdminUser = Depends(require_admin)):
    """Retire l'arène propre du boss : il reprend la salle commune."""
    boss = _boss(code)
    if boss is None:
        return JSONResponse({"ok": False, "error": f"Boss `{code}` introuvable."}, status_code=404)
    path = _arena_dir() / bfv.own_arena_name(code)
    if path.is_file():
        path.unlink()
        await run_in_threadpool(git_sync.push_content, [f"assets/landscapes/{path.name}"],
                                f"admin: arène du boss {code} retirée")
    return {"ok": True, **_after_change(code)}


# ----------------------------------------------------------------- aperçus --
def _scene_jpeg(b: dict, element: str) -> bytes:
    boss = {"code": b.get("code", ""), "name": b.get("name", ""), "image_name": b.get("image_name", ""),
            "element": element, "max_hp": int(b.get("max_hp", 1) or 1)}
    guards = [{"code": g.get("code", ""), "name": g.get("name", "Garde"), "image_name": g.get("image_name", ""),
               "element": element, "max_hp": int(g.get("max_hp", 1) or 1)} for g in b.get("guards") or []]
    image = bfv.preview_frame(boss=boss, guards=guards, players=scene_helpers.demo_players(),
                              phases=b.get("phases") or [],
                              background_path=bfv.arena_path(boss["code"], element),
                              boss_hp_pct=PREVIEW_HP_PCT)
    buf = io.BytesIO()
    image.convert("RGB").save(buf, "JPEG", quality=86)
    return buf.getvalue()


def _banner_png(b: dict, element: str) -> bytes:
    from app.bot.rendering.world_boss_banner import Contributor, RaidBannerData, compose_raid_banner
    from app.bot.runtime.raid_banner_builder import RAID_DAYS, _weakness_label, next_assault_label

    max_hp = int(b.get("max_hp", 1) or 1)
    data = RaidBannerData(
        boss_name=b.get("name", ""), image_name=b.get("image_name", "") or "",
        current_hp=int(max_hp * PREVIEW_HP_PCT), max_hp=max_hp,
        element_label=ELEMENT_LABELS.get(element, "") if element else "",
        element_emoji=ELEMENT_EMOJIS.get(element, "") if element else "",
        week_label="Semaine 49", day_index=3, day_total=RAID_DAYS, warriors=3, assaults=7,
        next_assault=next_assault_label(),
        contributors=[Contributor("Altan", int(max_hp * 0.17), int(max_hp * 0.02), 0),
                      Contributor("Kaori", int(max_hp * 0.12), int(max_hp * 0.09), 0),
                      Contributor("Rin", int(max_hp * 0.09), int(max_hp * 0.01), int(max_hp * 0.05))],
        attack=int(b.get("attack", 0) or 0), defense=int(b.get("defense", 0) or 0),
        speed=int(b.get("speed", 0) or 0), crit_chance=int(b.get("crit_chance", 0) or 0),
        weaknesses=_weakness_label(element), element_code=element, registered=2)
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder) / "banniere.png"
        compose_raid_banner(str(out), data)
        return out.read_bytes()


async def _preview(code: str, render, media_type: str, element: str = ""):
    boss = _boss(code)
    if boss is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Boss `{code}` introuvable.")
    data = await run_in_threadpool(render, boss, _preview_element(boss, element))
    return Response(data, media_type=media_type, headers={"Cache-Control": "no-store"})


@router.get("/world-bosses/{code}/scene.jpg")
async def boss_scene_preview(code: str, element: str = "", user: AdminUser = Depends(require_admin)):
    """Une image de la VIDÉO de l'assaut (code du bot) : arène, boss, gardes,
    teintés par `element` (le boss en change à chaque apparition)."""
    return await _preview(code, _scene_jpeg, "image/jpeg", element)


@router.get("/world-bosses/{code}/banner.png")
async def boss_banner_preview(code: str, element: str = "", user: AdminUser = Depends(require_admin)):
    """La BANNIÈRE du raid (code du bot), boss entamé et trois combattants d'exemple."""
    return await _preview(code, _banner_png, "image/png", element)


# ------------------------------------------------------------------ fiches --
@router.get("/world-bosses/new", response_class=HTMLResponse)
async def bosses_new_form(request: Request, user: AdminUser = Depends(require_admin)):
    return get_templates().TemplateResponse(
        request, "admin/world_bosses/form.html",
        context={"user": user, "errors": {}, "form_data": {}},
    )


@router.post("/world-bosses")
async def bosses_create(request: Request, user: AdminUser = Depends(require_admin)):
    fd = {k: str(v) for k, v in (await request.form()).items()}
    errors = {}
    code = fd.get("code", "").strip()
    name = fd.get("name", "").strip()
    if not code:
        errors["code"] = "Code requis."
    if not name:
        errors["name"] = "Nom requis."
    existing = _writer_load("boss_definitions.json", default=[]) or []
    if any(b.get("code") == code for b in existing):
        errors["code"] = f"Code `{code}` existe déjà."
    if errors:
        return get_templates().TemplateResponse(
            request, "admin/world_bosses/form.html",
            context={"user": user, "errors": errors, "form_data": fd},
            status_code=400,
        )
    # modifiers format : "damage_immunity_threshold=5, enrage_below_pct=20"
    modifiers = _parse_kv_pairs(fd.get("modifiers", ""))
    entry = {
        "code": code,
        "name": name,
        "description": fd.get("description", "").strip(),
        "image_name": fd.get("image_name", "").strip(),
        "tier": fd.get("tier", "intro").strip() or "intro",
        "spawn_weight": _parse_int(fd.get("spawn_weight"), 100),
        "max_hp": _parse_int(fd.get("max_hp"), 10000),
        "attack": _parse_int(fd.get("attack"), 50),
        "defense": _parse_int(fd.get("defense"), 20),
        "speed": _parse_int(fd.get("speed"), 5),
        "crit_chance": _parse_int(fd.get("crit_chance"), 0),
        "crit_damage": _parse_int(fd.get("crit_damage"), 100),
        "dodge": _parse_int(fd.get("dodge"), 0),
        "modifiers": modifiers,
        "lore": fd.get("lore", "").strip(),
    }
    append_to_list("boss_definitions.json", entry)
    # Tout de suite sur sa fiche : c'est là (ou sur la galerie) qu'on dépose ses images.
    return RedirectResponse(f"/admin/world-bosses/{code}/edit?created=1", status_code=303)


def _scalar_modifiers(modifiers: dict | None) -> dict:
    """Les modifiers éditables en `clé=valeur` (un booléen devient 1 / 0) ;
    les invocations (dict) restent dans le JSON, conservées à l'édition."""
    return {k: int(v) if isinstance(v, bool) else v for k, v in (modifiers or {}).items()
            if not isinstance(v, (dict, list))}


@router.get("/world-bosses/{code}/edit", response_class=HTMLResponse)
async def bosses_edit_form(
    code: str, request: Request, saved: int = 0, created: int = 0,
    user: AdminUser = Depends(require_admin),
):
    from webapp.admin.json_writer import find_in_list_by_key
    entry = find_in_list_by_key("boss_definitions.json", code)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Boss `{code}` introuvable.")
    fd = {
        "code": entry.get("code", ""),
        "name": entry.get("name", ""),
        "description": entry.get("description", ""),
        "image_name": entry.get("image_name", ""),
        "tier": entry.get("tier", ""),
        "spawn_weight": entry.get("spawn_weight", 100),
        "max_hp": entry.get("max_hp", 10000),
        "attack": entry.get("attack", 50),
        "defense": entry.get("defense", 20),
        "speed": entry.get("speed", 5),
        "crit_chance": entry.get("crit_chance", 0),
        "crit_damage": entry.get("crit_damage", 100),
        "dodge": entry.get("dodge", 0),
        "modifiers": _fmt_kv_pairs(_scalar_modifiers(entry.get("modifiers"))),
        "lore": entry.get("lore", ""),
    }
    return get_templates().TemplateResponse(
        request, "admin/world_bosses/form.html",
        context={"user": user, "errors": {}, "form_data": fd, "edit_code": code, "boss": _state(entry),
                 "elements": elements(),
                 "saved": bool(saved), "created": bool(created),
                 "max_mb": MAX_UPLOAD_BYTES // (1024 * 1024)},
    )


@router.post("/world-bosses/{code}")
async def bosses_update(
    code: str, request: Request, user: AdminUser = Depends(require_admin),
):
    from webapp.admin.json_writer import find_in_list_by_key, update_in_list_by_key
    existing = find_in_list_by_key("boss_definitions.json", code)
    if existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Boss `{code}` introuvable.")
    fd = {k: str(v) for k, v in (await request.form()).items()}
    # Ce que le formulaire ne montre pas (élément, butin, phases, ultime,
    # gardes, invocations…) est conservé : avant, éditer un boss l'effaçait.
    nested = {k: v for k, v in (existing.get("modifiers") or {}).items() if isinstance(v, (dict, list))}
    entry = {
        **existing,
        "code": code,
        "name": fd.get("name", "").strip(),
        "description": fd.get("description", "").strip(),
        "image_name": fd.get("image_name", existing.get("image_name", "")).strip(),
        "tier": fd.get("tier", "intro").strip() or "intro",
        "spawn_weight": _parse_int(fd.get("spawn_weight"), 100),
        "max_hp": _parse_int(fd.get("max_hp"), 10000),
        "attack": _parse_int(fd.get("attack"), 50),
        "defense": _parse_int(fd.get("defense"), 20),
        "speed": _parse_int(fd.get("speed"), 5),
        "crit_chance": _parse_int(fd.get("crit_chance"), 0),
        "crit_damage": _parse_int(fd.get("crit_damage"), 100),
        "dodge": _parse_int(fd.get("dodge"), 0),
        "modifiers": {**nested, **_parse_kv_pairs(fd.get("modifiers", ""))},
        "lore": fd.get("lore", "").strip(),
    }
    update_in_list_by_key("boss_definitions.json", code, entry)
    if entry["name"] and entry["name"] != existing.get("name"):
        _rename_instances(code, entry["name"])
    return RedirectResponse(f"/admin/world-bosses/{code}/edit?saved=1", status_code=303)


@router.post("/world-bosses/{code}/delete")
async def bosses_delete(code: str, user: AdminUser = Depends(require_admin)):
    return _delete_from_list("boss_definitions.json", code, "Boss", "/admin/world-bosses")
