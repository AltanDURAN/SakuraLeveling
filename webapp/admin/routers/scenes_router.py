"""Routes admin : COMPOSITION de la scène de spawn, par monstre.

Éditeur WYSIWYG : on choisit la portion visible de l'image d'environnement puis
on place le monstre dedans. Tout est stocké en fractions dans `mob_scenes.json`
(reseed-safe, auto-poussé sur git). L'aperçu « réel » est généré par le MÊME
code que le bot (`fight_scene.render_scene`) → ce que tu vois est ce que tu auras.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response

from app.bot.rendering import fight_scene
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.encounters import farm_zone_loader, mob_scene_loader
from app.shared.paths import LANDSCAPES_ASSETS_DIR, MOBS_ASSETS_DIR
from webapp.admin import json_writer, uploads
from webapp.admin._shared import get_templates
from webapp.admin.auth import AdminUser, require_admin

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/scenes", tags=["admin-scenes"])

_FILENAME = "mob_scenes.json"
_COMMENT = (
    "Composition de la scène de spawn, PAR MONSTRE (éditée via l'admin web : "
    "Monde › Scènes). Coordonnées en FRACTIONS (0-1). crop = portion visible de "
    "l'environnement ; mob = placement (x centre, y pieds, scale hauteur)."
)


def _safe_name(name: str) -> str:
    """Empêche toute traversée de chemin sur un nom d'asset."""
    return Path(name or "").name


def _list_backgrounds() -> list[str]:
    if not LANDSCAPES_ASSETS_DIR.exists():
        return []
    return sorted(
        p.name for p in LANDSCAPES_ASSETS_DIR.iterdir()
        if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    )


def _default_scene_for(mob) -> dict:
    """Composition de départ quand le monstre n'en a pas encore : décor de sa
    zone + cadrage/placement proches du rendu automatique."""
    return {
        "background": farm_zone_loader.get_background_for_family(mob.family),
        "crop": {"x": 0.15, "y": 0.15, "w": 0.70},
        "mob": {"x": 0.5, "y": 0.88, "scale": 0.62},
        "shadow": True,
    }


def _read_scene_params(params) -> dict:
    """Construit une scène depuis des paramètres (form ou query)."""
    def _f(key, default):
        try:
            return float(params.get(key, default))
        except (TypeError, ValueError):
            return default
    shadow = str(params.get("shadow", "1")).lower() not in {"0", "false", "off", ""}
    return {
        "background": _safe_name(str(params.get("background", ""))),
        "crop": {"x": _f("crop_x", 0.0), "y": _f("crop_y", 0.0), "w": _f("crop_w", 1.0)},
        "mob": {"x": _f("mob_x", 0.5), "y": _f("mob_y", 0.88), "scale": _f("mob_scale", 0.6)},
        "shadow": shadow,
    }


@router.get("")
async def scenes_list(request: Request, user: AdminUser = Depends(require_admin)):
    mob_scene_loader.reload_cache()
    scenes = mob_scene_loader.all_scenes()
    with get_db_session() as session:
        mobs = MobRepository(session).list_all()
    rows = [
        {
            "code": m.code, "name": m.name, "image_name": m.image_name,
            "family": m.family, "composed": m.code in scenes,
        }
        for m in sorted(mobs, key=lambda x: (x.family or "", x.name))
    ]
    return get_templates().TemplateResponse(
        request, "admin/scenes/list.html",
        context={"user": user, "rows": rows, "composed_count": sum(r["composed"] for r in rows)},
    )


@router.get("/mob-content/{image_name}")
async def mob_content_image(image_name: str, user: AdminUser = Depends(require_admin)):
    """Image du monstre RECADRÉE sur ses pixels réels — c'est exactement ce que
    le rendu utilise, donc l'éditeur affiche la même chose (WYSIWYG)."""
    path = MOBS_ASSETS_DIR / _safe_name(image_name)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image introuvable.")
    from PIL import Image
    content = fight_scene.mob_content(Image.open(path))
    buf = io.BytesIO()
    content.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})


@router.get("/{code}")
async def scene_composer(code: str, request: Request, user: AdminUser = Depends(require_admin)):
    with get_db_session() as session:
        mob = MobRepository(session).get_by_code(code)
    if mob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Monstre `{code}` introuvable.")
    mob_scene_loader.reload_cache()
    scene = mob_scene_loader.get_mob_scene(code) or _default_scene_for(mob)
    return get_templates().TemplateResponse(
        request, "admin/scenes/composer.html",
        context={
            "user": user, "mob": mob, "scene": scene,
            "backgrounds": _list_backgrounds(),
            "frame_w": fight_scene.FRAME_W, "frame_h": fight_scene.FRAME_H,
            "top_panel": fight_scene.TOP_PANEL, "bottom_panel": fight_scene.BOTTOM_PANEL,
        },
    )


@router.get("/{code}/preview.png")
async def scene_preview(code: str, request: Request, user: AdminUser = Depends(require_admin)):
    """Aperçu RÉEL : rendu par le même code que le bot, avec les paramètres
    courants de l'éditeur (query params)."""
    with get_db_session() as session:
        mob = MobRepository(session).get_by_code(code)
    if mob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Monstre `{code}` introuvable.")
    scene = _read_scene_params(request.query_params)
    demo_players = [
        {"name": "Altan", "avatar_url": None, "current_hp": 100, "max_hp": 100},
        {"name": "Kaori", "avatar_url": None, "current_hp": 55, "max_hp": 100},
        {"name": "Rin", "avatar_url": None, "current_hp": 22, "max_hp": 100},
    ]
    image = fight_scene.render_scene(
        mob={
            "code": mob.code, "name": mob.name, "image_name": mob.image_name,
            "current_hp": max(1, int(mob.max_hp * 0.7)), "max_hp": mob.max_hp,
            "element": request.query_params.get("element", mob.element or ""),
            "power_score": "?",
        },
        players=demo_players,
        scene=scene,
    )
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@router.post("/{code}")
async def scene_save(code: str, request: Request, user: AdminUser = Depends(require_admin)):
    with get_db_session() as session:
        mob = MobRepository(session).get_by_code(code)
    if mob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Monstre `{code}` introuvable.")

    form = await request.form()
    params = {k: str(v) for k, v in form.items() if k != "background_file"}

    # Upload optionnel d'un nouvel environnement.
    upload = form.get("background_file")
    if upload is not None and getattr(upload, "filename", ""):
        data = await upload.read()
        try:
            saved = uploads.save_asset_bytes(data, upload.filename, LANDSCAPES_ASSETS_DIR)
            params["background"] = saved
        except uploads.UploadError as exc:
            _logger.warning("Upload décor refusé : %s", exc)

    scene = _read_scene_params(params)
    data = json_writer.load_json(_FILENAME, {"scenes": {}}) or {"scenes": {}}
    scenes = data.get("scenes", {})
    if not isinstance(scenes, dict):
        scenes = {}
    scenes[code] = scene
    json_writer.atomic_write_json(_FILENAME, {"_comment": _COMMENT, "scenes": scenes})
    mob_scene_loader.reload_cache()
    _logger.info("Admin %s a composé la scène du monstre %s", user.discord_id, code)
    return RedirectResponse(f"/admin/scenes/{code}?saved=1", status_code=303)


@router.post("/{code}/delete")
async def scene_delete(code: str, user: AdminUser = Depends(require_admin)):
    data = json_writer.load_json(_FILENAME, {"scenes": {}}) or {"scenes": {}}
    scenes = data.get("scenes", {})
    if isinstance(scenes, dict) and code in scenes:
        del scenes[code]
        json_writer.atomic_write_json(_FILENAME, {"_comment": _COMMENT, "scenes": scenes})
        mob_scene_loader.reload_cache()
        _logger.info("Admin %s a supprimé la scène du monstre %s", user.discord_id, code)
    return RedirectResponse("/admin/scenes", status_code=303)
