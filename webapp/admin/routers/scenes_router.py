"""Routes admin : COMPOSITION des scènes de spawn.

Deux éditeurs :
  • SPOT (zone × élément) : décor visible + ligne de sol. Écrit dans le spot
    correspondant de `farm_zones.json`.
  • MONSTRE : placement (taille, décalage, ombre) + poids par élément (quels
    éléments il peut prendre). Écrit dans `mob_placements.json`. Onglets = un
    par élément possible, sprite teinté.

Aperçu « réel » généré par le MÊME code que le bot (`fight_scene.render_scene`).
Tout en fractions, reseed-safe, auto-poussé sur git.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from PIL import Image

from app.bot.rendering import element_visuals, fight_scene
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.elements.element_spawn_weight_loader import get_spawn_weights
from app.infrastructure.encounters import farm_zone_loader, mob_placement_loader
from app.shared.enums import ALL_ELEMENTS, ELEMENT_EMOJIS, ELEMENT_LABELS
from app.shared.paths import LANDSCAPES_ASSETS_DIR, MOBS_ASSETS_DIR
from webapp.admin import json_writer, uploads
from webapp.admin._shared import get_templates
from webapp.admin.auth import AdminUser, require_admin

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/scenes", tags=["admin-scenes"])

_ZONES_FILE = "farm_zones.json"
_MOBS_FILE = "mob_placements.json"
_MOBS_COMMENT = (
    "Placement du monstre dans le cadre (indépendant du décor, qui vient du "
    "spot de la zone) : scale, offset_x, shadow, element_weights (poids par "
    "élément : >0 = éligible). Vide = hérite des éléments de sa zone."
)


def _safe(name: str) -> str:
    return Path(name or "").name


def _f(params, key, default):
    try:
        return float(params.get(key, default))
    except (TypeError, ValueError):
        return default


def _list_backgrounds() -> list[str]:
    if not LANDSCAPES_ASSETS_DIR.exists():
        return []
    return sorted(
        p.name for p in LANDSCAPES_ASSETS_DIR.iterdir()
        if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    )


def _demo_players():
    return [
        {"name": "Altan", "avatar_url": None, "current_hp": 100, "max_hp": 100},
        {"name": "Kaori", "avatar_url": None, "current_hp": 55, "max_hp": 100},
        {"name": "Rin", "avatar_url": None, "current_hp": 22, "max_hp": 100},
    ]


# ------------------------------------------------------------------ vue liste
@router.get("")
async def scenes_home(request: Request, user: AdminUser = Depends(require_admin)):
    farm_zone_loader.clear_cache()
    zones = farm_zone_loader.list_zones()
    with get_db_session() as session:
        mobs = MobRepository(session).list_all()
    zone_rows = [
        {
            "name": z.get("name", "?"),
            "channel_id": int(z.get("channel_id", 0) or 0),
            "spots": [
                {
                    "element": s.get("element"),
                    "label": ELEMENT_LABELS.get(s.get("element"), s.get("element")),
                    "emoji": ELEMENT_EMOJIS.get(s.get("element"), ""),
                    "time": s.get("time", "always"),
                    "composed": bool(s.get("crop")),
                }
                for s in (z.get("spots") or [])
            ],
        }
        for z in zones if int(z.get("channel_id", 0) or 0)
    ]
    mob_rows = sorted(
        ({"code": m.code, "name": m.name, "image_name": m.image_name, "family": m.family}
         for m in mobs),
        key=lambda r: (r["family"] or "", r["name"]),
    )
    return get_templates().TemplateResponse(
        request, "admin/scenes/home.html",
        context={"user": user, "zones": zone_rows, "mobs": mob_rows},
    )


# ------------------------------------------------------------------ image mob
@router.get("/mob-content/{image_name}")
async def mob_content_image(
    image_name: str, element: str = "", user: AdminUser = Depends(require_admin),
):
    """Sprite du monstre recadré sur ses pixels réels, éventuellement teinté par
    `element` — exactement ce que le rendu affiche (WYSIWYG)."""
    path = MOBS_ASSETS_DIR / _safe(image_name)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image introuvable.")
    content = fight_scene.mob_content(Image.open(path))
    if element:
        content = element_visuals.tint_by_element(content, element)
    buf = io.BytesIO()
    content.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=600"})


# ------------------------------------------------------------------ SPOT
def _find_zone_spot(channel_id: int, element: str) -> tuple[dict, dict | None]:
    data = json_writer.load_json(_ZONES_FILE, {}) or {}
    for z in data.get("zones", []):
        if int(z.get("channel_id", 0) or 0) == channel_id:
            for s in z.get("spots", []) or []:
                if str(s.get("element", "")).lower() == element.lower():
                    return z, s
            return z, None
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"Zone {channel_id} introuvable.")


@router.get("/spot/{channel_id}/{element}")
async def spot_composer(
    channel_id: int, element: str, request: Request, saved: int = 0,
    user: AdminUser = Depends(require_admin),
):
    farm_zone_loader.clear_cache()
    zone, spot = _find_zone_spot(channel_id, element)
    if spot is None:
        spot = {"element": element, "time": "always",
                "background": zone.get("background", ""),
                "crop": {"x": 0.11, "y": 0.12, "w": 0.78}, "ground_y": 0.86}
    # un monstre d'exemple pour juger l'échelle (le 1er de la zone)
    sample = None
    with get_db_session() as session:
        for m in MobRepository(session).list_all():
            if m.family in (zone.get("families") or []):
                sample = {"code": m.code, "image_name": m.image_name}
                break
    return get_templates().TemplateResponse(
        request, "admin/scenes/spot.html",
        context={
            "user": user, "zone": zone, "element": element,
            "label": ELEMENT_LABELS.get(element, element),
            "emoji": ELEMENT_EMOJIS.get(element, ""),
            "spot": spot, "sample": sample, "backgrounds": _list_backgrounds(),
            "frame_w": fight_scene.FRAME_W, "frame_h": fight_scene.FRAME_H,
            "top_panel": fight_scene.TOP_PANEL, "bottom_panel": fight_scene.BOTTOM_PANEL,
            "saved": saved,
        },
    )


@router.get("/spot/{channel_id}/{element}/preview.png")
async def spot_preview(
    channel_id: int, element: str, request: Request,
    user: AdminUser = Depends(require_admin),
):
    zone, _ = _find_zone_spot(channel_id, element)
    p = request.query_params
    spot = {"background": _safe(p.get("background", "")),
            "crop": {"x": _f(p, "crop_x", 0), "y": _f(p, "crop_y", 0), "w": _f(p, "crop_w", 1)},
            "ground_y": _f(p, "ground_y", 0.86)}
    sample_mob = None
    with get_db_session() as session:
        for m in MobRepository(session).list_all():
            if m.family in (zone.get("families") or []):
                pl = mob_placement_loader.get_mob_placement(m.code)
                sample_mob = {
                    "code": m.code, "name": m.name, "image_name": m.image_name,
                    "element": element, "current_hp": max(1, int(m.max_hp * 0.7)),
                    "max_hp": m.max_hp, "power_score": "?",
                }
                placement = pl or {"scale": 0.6, "offset_x": 0.0, "shadow": True}
                break
        else:
            placement = None
    image = fight_scene.render_scene(mob=sample_mob, players=_demo_players(),
                                     spot=spot, placement=placement)
    buf = io.BytesIO(); image.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/spot/{channel_id}/{element}")
async def spot_save(
    channel_id: int, element: str, request: Request,
    user: AdminUser = Depends(require_admin),
):
    form = await request.form()
    background = _safe(str(form.get("background", "")))
    upload = form.get("background_file")
    if upload is not None and getattr(upload, "filename", ""):
        try:
            background = uploads.save_asset_bytes(
                await upload.read(), upload.filename, LANDSCAPES_ASSETS_DIR)
        except uploads.UploadError as exc:
            _logger.warning("Upload décor refusé : %s", exc)
    new_spot = {
        "element": element,
        "time": str(form.get("time", "always")),
        "background": background,
        "crop": {"x": _f(form, "crop_x", 0), "y": _f(form, "crop_y", 0), "w": _f(form, "crop_w", 1)},
        "ground_y": _f(form, "ground_y", 0.86),
    }
    data = json_writer.load_json(_ZONES_FILE, {}) or {}
    for z in data.get("zones", []):
        if int(z.get("channel_id", 0) or 0) == channel_id:
            spots = z.setdefault("spots", [])
            for i, s in enumerate(spots):
                if str(s.get("element", "")).lower() == element.lower():
                    spots[i] = new_spot
                    break
            else:
                spots.append(new_spot)
            break
    json_writer.atomic_write_json(_ZONES_FILE, data)
    farm_zone_loader.clear_cache()
    _logger.info("Admin %s a composé le spot %s/%s", user.discord_id, channel_id, element)
    return RedirectResponse(f"/admin/scenes/spot/{channel_id}/{element}?saved=1", status_code=303)


# ------------------------------------------------------------------ MONSTRE
@router.get("/mob/{code}")
async def mob_editor(
    code: str, request: Request, saved: int = 0, user: AdminUser = Depends(require_admin),
):
    with get_db_session() as session:
        mob = MobRepository(session).get_by_code(code)
    if mob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Monstre `{code}` introuvable.")
    mob_placement_loader.reload_cache()
    placement = mob_placement_loader.get_mob_placement(code) or {
        "scale": 0.6, "offset_x": 0.0, "offset_y": 0.0, "shadow": True, "element_weights": {}}
    weights = placement.get("element_weights") or {}
    elements = [
        {"code": e.value, "label": ELEMENT_LABELS[e.value], "emoji": ELEMENT_EMOJIS[e.value],
         "weight": int(weights.get(e.value, 0) or 0)}
        for e in ALL_ELEMENTS
    ]
    # Décors des spots de la zone du monstre (pour le fond du stage live).
    farm_zone_loader.clear_cache()
    ch = farm_zone_loader.get_spawn_channel_for_family(mob.family)
    zone_spots = {
        str(s.get("element")): {
            "background": s.get("background", ""),
            "ground_y": s.get("ground_y", 0.86),
        }
        for s in farm_zone_loader.get_spots(ch)
    }
    default_bg = farm_zone_loader.get_background_for_family(mob.family)
    return get_templates().TemplateResponse(
        request, "admin/scenes/mob.html",
        context={
            "user": user, "mob": mob, "placement": placement, "elements": elements,
            "zone_spots": zone_spots, "default_bg": default_bg,
            "frame_w": fight_scene.FRAME_W, "frame_h": fight_scene.FRAME_H,
            "top_panel": fight_scene.TOP_PANEL, "bottom_panel": fight_scene.BOTTOM_PANEL,
            "saved": saved,
        },
    )


@router.get("/mob/{code}/preview.png")
async def mob_preview(
    code: str, request: Request, user: AdminUser = Depends(require_admin),
):
    with get_db_session() as session:
        mob = MobRepository(session).get_by_code(code)
    if mob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Monstre introuvable.")
    p = request.query_params
    element = p.get("element", mob.element or "")
    placement = {"scale": _f(p, "scale", 0.6), "offset_x": _f(p, "offset_x", 0.0),
                 "offset_y": _f(p, "offset_y", 0.0),
                 "shadow": str(p.get("shadow", "1")).lower() not in {"0", "false", "off"}}
    # décor : le spot de la zone du monstre pour cet élément (sinon fallback)
    spot = None
    ch = farm_zone_loader.get_spawn_channel_for_family(mob.family)
    if element:
        spot = farm_zone_loader.get_spot(ch, element)
    image = fight_scene.render_scene(
        mob={"code": mob.code, "name": mob.name, "image_name": mob.image_name,
             "element": element, "current_hp": max(1, int(mob.max_hp * 0.7)),
             "max_hp": mob.max_hp, "power_score": "?"},
        players=_demo_players(), spot=spot, placement=placement,
    )
    buf = io.BytesIO(); image.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/mob/{code}")
async def mob_save(code: str, request: Request, user: AdminUser = Depends(require_admin)):
    with get_db_session() as session:
        mob = MobRepository(session).get_by_code(code)
    if mob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Monstre introuvable.")
    form = await request.form()
    weights: dict[str, int] = {}
    for e in ALL_ELEMENTS:
        try:
            w = max(0, int(str(form.get(f"weight_{e.value}", "0")).strip() or 0))
        except (TypeError, ValueError):
            w = 0
        if w > 0:
            weights[e.value] = w
    placement = {
        "scale": _f(form, "scale", 0.6),
        "offset_x": _f(form, "offset_x", 0.0),
        "offset_y": _f(form, "offset_y", 0.0),
        "shadow": str(form.get("shadow", "1")).lower() not in {"0", "false", "off"},
        "element_weights": weights,
    }
    data = json_writer.load_json(_MOBS_FILE, {"placements": {}}) or {"placements": {}}
    placements = data.get("placements", {})
    if not isinstance(placements, dict):
        placements = {}
    placements[code] = placement
    json_writer.atomic_write_json(_MOBS_FILE, {"_comment": _MOBS_COMMENT, "placements": placements})
    mob_placement_loader.reload_cache()
    _logger.info("Admin %s a édité le placement du monstre %s", user.discord_id, code)
    return RedirectResponse(f"/admin/scenes/mob/{code}?saved=1", status_code=303)
