"""Routes admin : COMPOSITION des scènes de spawn, par monstre ET par élément.

Un seul endroit : on clique un monstre → on compose chaque version élémentaire
(fond + cadrage/zoom du fond + placement/taille du monstre + ombre + poids +
jour/nuit). Écrit dans `mob_scenes.json`. Aperçu « réel » par le MÊME code que
le bot. Tout en fractions, reseed-safe, auto-poussé sur git.
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
from app.infrastructure.encounters import farm_zone_loader, mob_scene_loader
from app.shared.enums import ALL_ELEMENTS, ELEMENT_EMOJIS, ELEMENT_LABELS
from app.shared.paths import LANDSCAPES_ASSETS_DIR, MOBS_ASSETS_DIR
from webapp.admin import json_writer, uploads
from webapp.admin._shared import get_templates
from webapp.admin.auth import AdminUser, require_admin

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/scenes", tags=["admin-scenes"])

_FILE = "mob_scenes.json"
_COMMENT = (
    "Scène de spawn composée PAR MONSTRE ET PAR ÉLÉMENT (admin › Scènes). Chaque "
    "scène : weight, time (always|day|night), background, crop{x,y,w}, "
    "mob{x,y,scale}, shadow. Fractions 0-1."
)
_VALID_ELEMENTS = {e.value for e in ALL_ELEMENTS}


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


def _default_scene(mob, element: str) -> dict:
    """Scène de départ pour un (monstre, élément) pas encore composé."""
    weights = get_spawn_weights()
    time = "night" if element == "tenebre" else "day" if element == "lumiere" else "always"
    return {
        "weight": int(weights.get(element, 10) or 10),
        "time": time,
        "background": farm_zone_loader.get_background_for_family(mob.family),
        "crop": {"x": 0.11, "y": 0.12, "w": 0.78},
        "mob": {"x": 0.5, "y": 0.88, "scale": 0.6},
        "shadow": True,
    }


def _scene_from_params(params) -> dict:
    shadow = str(params.get("shadow", "1")).lower() not in {"0", "false", "off", ""}
    return {
        "weight": max(0, int(_f(params, "weight", 10))),
        "time": str(params.get("time", "always")),
        "background": _safe(str(params.get("background", ""))),
        "crop": {"x": _f(params, "crop_x", 0.0), "y": _f(params, "crop_y", 0.0), "w": _f(params, "crop_w", 1.0)},
        "mob": {"x": _f(params, "mob_x", 0.5), "y": _f(params, "mob_y", 0.88), "scale": _f(params, "mob_scale", 0.6)},
        "shadow": shadow,
    }


def _scene_to_render(scene: dict):
    m = scene.get("mob", {}) or {}
    spot = {"background": scene.get("background"), "crop": scene.get("crop"), "ground_y": m.get("y", 0.88)}
    placement = {"scale": m.get("scale", 0.6), "offset_x": m.get("x", 0.5) - 0.5,
                 "offset_y": 0.0, "shadow": scene.get("shadow", True)}
    return spot, placement


# ------------------------------------------------------------------ home
@router.get("")
async def scenes_home(request: Request, user: AdminUser = Depends(require_admin)):
    mob_scene_loader.reload_cache()
    all_scenes = mob_scene_loader.all_scenes()
    with get_db_session() as session:
        mobs = MobRepository(session).list_all()
    rows = sorted(
        ({"code": m.code, "name": m.name, "image_name": m.image_name, "family": m.family,
          "elements": sorted((all_scenes.get(m.code) or {}).keys())}
         for m in mobs),
        key=lambda r: (r["family"] or "", r["name"]),
    )
    return get_templates().TemplateResponse(
        request, "admin/scenes/home.html", context={"user": user, "mobs": rows},
    )


@router.get("/mob-content/{image_name}")
async def mob_content_image(image_name: str, element: str = "",
                            user: AdminUser = Depends(require_admin)):
    path = MOBS_ASSETS_DIR / _safe(image_name)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image introuvable.")
    content = fight_scene.mob_content(Image.open(path))
    if element:
        content = element_visuals.tint_by_element(content, element)
    buf = io.BytesIO(); content.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=600"})


@router.get("/mob/{code}")
async def mob_redirect(code: str, user: AdminUser = Depends(require_admin)):
    """Ouvre le composer sur le 1er élément composé, sinon 'feu' par défaut."""
    mob_scene_loader.reload_cache()
    scenes = mob_scene_loader.get_scenes(code)
    element = sorted(scenes.keys())[0] if scenes else "feu"
    return RedirectResponse(f"/admin/scenes/mob/{code}/{element}", status_code=307)


@router.get("/mob/{code}/{element}")
async def composer(code: str, element: str, request: Request, saved: int = 0,
                   user: AdminUser = Depends(require_admin)):
    if element not in _VALID_ELEMENTS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Élément inconnu.")
    with get_db_session() as session:
        mob = MobRepository(session).get_by_code(code)
    if mob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Monstre `{code}` introuvable.")
    mob_scene_loader.reload_cache()
    all_for_mob = mob_scene_loader.get_scenes(code)
    scene = all_for_mob.get(element) or _default_scene(mob, element)
    tabs = [
        {"code": e.value, "label": ELEMENT_LABELS[e.value], "emoji": ELEMENT_EMOJIS[e.value],
         "composed": e.value in all_for_mob}
        for e in ALL_ELEMENTS
    ]
    return get_templates().TemplateResponse(
        request, "admin/scenes/composer.html",
        context={
            "user": user, "mob": mob, "element": element,
            "label": ELEMENT_LABELS.get(element, element), "emoji": ELEMENT_EMOJIS.get(element, ""),
            "scene": scene, "tabs": tabs, "is_composed": element in all_for_mob,
            "backgrounds": _list_backgrounds(),
            "frame_w": fight_scene.FRAME_W, "frame_h": fight_scene.FRAME_H,
            "top_panel": fight_scene.TOP_PANEL, "bottom_panel": fight_scene.BOTTOM_PANEL,
            "saved": saved,
        },
    )


@router.get("/mob/{code}/{element}/preview.png")
async def preview(code: str, element: str, request: Request,
                  user: AdminUser = Depends(require_admin)):
    with get_db_session() as session:
        mob = MobRepository(session).get_by_code(code)
    if mob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Monstre introuvable.")
    spot, placement = _scene_to_render(_scene_from_params(request.query_params))
    image = fight_scene.render_scene(
        mob={"code": mob.code, "name": mob.name, "image_name": mob.image_name,
             "element": element, "current_hp": max(1, int(mob.max_hp * 0.7)),
             "max_hp": mob.max_hp, "power_score": "?"},
        players=_demo_players(), spot=spot, placement=placement,
    )
    buf = io.BytesIO(); image.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/mob/{code}/{element}")
async def save(code: str, element: str, request: Request,
               user: AdminUser = Depends(require_admin)):
    if element not in _VALID_ELEMENTS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Élément inconnu.")
    with get_db_session() as session:
        mob = MobRepository(session).get_by_code(code)
    if mob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Monstre introuvable.")
    form = await request.form()
    params = {k: str(v) for k, v in form.items() if k != "background_file"}
    upload = form.get("background_file")
    if upload is not None and getattr(upload, "filename", ""):
        try:
            params["background"] = uploads.save_asset_bytes(
                await upload.read(), upload.filename, LANDSCAPES_ASSETS_DIR)
        except uploads.UploadError as exc:
            _logger.warning("Upload décor refusé : %s", exc)
    scene = _scene_from_params(params)
    data = json_writer.load_json(_FILE, {"scenes": {}}) or {"scenes": {}}
    scenes = data.get("scenes", {})
    if not isinstance(scenes, dict):
        scenes = {}
    scenes.setdefault(code, {})[element] = scene
    json_writer.atomic_write_json(_FILE, {"_comment": _COMMENT, "scenes": scenes})
    mob_scene_loader.reload_cache()
    _logger.info("Admin %s a composé la scène %s/%s", user.discord_id, code, element)
    return RedirectResponse(f"/admin/scenes/mob/{code}/{element}?saved=1", status_code=303)


@router.post("/mob/{code}/{element}/delete")
async def delete(code: str, element: str, user: AdminUser = Depends(require_admin)):
    data = json_writer.load_json(_FILE, {"scenes": {}}) or {"scenes": {}}
    scenes = data.get("scenes", {})
    if isinstance(scenes, dict) and code in scenes and element in scenes[code]:
        del scenes[code][element]
        if not scenes[code]:
            del scenes[code]
        json_writer.atomic_write_json(_FILE, {"_comment": _COMMENT, "scenes": scenes})
        mob_scene_loader.reload_cache()
        _logger.info("Admin %s a supprimé la scène %s/%s", user.discord_id, code, element)
    return RedirectResponse(f"/admin/scenes/mob/{code}", status_code=303)
