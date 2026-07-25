"""Routes admin : PLACEMENT des monstres dans la scène de spawn.

Éditeur MONSTRE : placement visuel (taille, décalage x/y, ombre) par élément.
Le DÉCOR (spot) est possédé par la zone (Monde › Zones › décor) ; les POIDS de
spawn élémentaires sont possédés par la fiche du monstre (Monde › Mobs).

Un onglet par élément de la zone du monstre ; chaque couple (monstre, élément)
a son propre placement. Aperçu « réel » généré par le MÊME code que le bot
(`fight_scene.render_scene`). Tout en fractions, reseed-safe, auto-poussé git.
"""

from __future__ import annotations

import io
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from PIL import Image

from app.bot.rendering import element_visuals, fight_scene
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.encounters import (
    farm_zone_loader,
    mob_element_weight_loader,
    mob_placement_loader,
)
from app.shared.enums import ALL_ELEMENTS, ELEMENT_EMOJIS, ELEMENT_LABELS
from app.shared.paths import MOBS_ASSETS_DIR
from webapp.admin import json_writer, scene_helpers
from webapp.admin._shared import get_templates
from webapp.admin.auth import AdminUser, require_admin

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/scenes", tags=["admin-scenes"])

_MOBS_FILE = "mob_placements.json"
_MOBS_COMMENT = (
    "Placement VISUEL du monstre par (monstre × élément), indépendant du décor "
    "(qui vient du spot de la zone) et du poids de spawn (fiche du monstre → "
    "mob_element_weights.json) : placements[mob][element] = {scale, offset_x, "
    "offset_y, shadow}."
)
_VALID_ELEMENTS = {e.value for e in ALL_ELEMENTS}


# ------------------------------------------------------------------ vue liste
@router.get("")
async def scenes_home(request: Request, user: AdminUser = Depends(require_admin)):
    farm_zone_loader.clear_cache()
    with get_db_session() as session:
        mobs = MobRepository(session).list_all()
    mob_rows = sorted(
        ({"code": m.code, "name": m.name, "image_name": m.image_name, "family": m.family}
         for m in mobs),
        key=lambda r: (r["family"] or "", r["name"]),
    )
    return get_templates().TemplateResponse(
        request, "admin/scenes/home.html",
        context={"user": user, "mobs": mob_rows},
    )


# ------------------------------------------------------------------ image mob
@router.get("/mob-content/{image_name}")
async def mob_content_image(
    image_name: str, element: str = "", user: AdminUser = Depends(require_admin),
):
    """Sprite du monstre recadré sur ses pixels réels, éventuellement teinté par
    `element` — exactement ce que le rendu affiche (WYSIWYG)."""
    path = MOBS_ASSETS_DIR / scene_helpers.safe(image_name)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image introuvable.")
    content = fight_scene.mob_content(Image.open(path))
    if element:
        content = element_visuals.tint_by_element(content, element)
    buf = io.BytesIO()
    content.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=600"})


# ------------------------------------------------------------------ MONSTRE
def _mob_zone_spots(mob) -> dict:
    """Spots (par élément) de la zone du monstre : {element: spot}."""
    farm_zone_loader.clear_cache()
    ch = farm_zone_loader.get_spawn_channel_for_family(mob.family)
    return {str(s.get("element")): s for s in farm_zone_loader.get_spots(ch)}


@router.get("/mob/{code}")
async def mob_redirect(code: str, user: AdminUser = Depends(require_admin)):
    """Ouvre l'éditeur sur le 1er élément de la zone du monstre."""
    with get_db_session() as session:
        mob = MobRepository(session).get_by_code(code)
    if mob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Monstre `{code}` introuvable.")
    mob_placement_loader.reload_cache()
    elems = list(_mob_zone_spots(mob).keys()) or list(mob_placement_loader.get_mob_elements(code).keys()) or ["feu"]
    return RedirectResponse(f"/admin/scenes/mob/{code}/{elems[0]}", status_code=307)


@router.get("/mob/{code}/{element}")
async def mob_editor(code: str, element: str, request: Request, saved: int = 0,
                     user: AdminUser = Depends(require_admin)):
    if element not in _VALID_ELEMENTS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Élément inconnu.")
    with get_db_session() as session:
        mob = MobRepository(session).get_by_code(code)
    if mob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Monstre `{code}` introuvable.")
    mob_placement_loader.reload_cache()
    zone_channel = farm_zone_loader.get_spawn_channel_for_family(mob.family)
    spots = _mob_zone_spots(mob)
    placed = mob_placement_loader.get_mob_elements(code)
    entry = placed.get(element) or {}
    placement = {
        "scale": entry.get("scale", 0.6), "offset_x": entry.get("offset_x", 0.0),
        "offset_y": entry.get("offset_y", 0.0), "shadow": entry.get("shadow", True),
    }
    # Poids : LECTURE SEULE ici (édité sur la fiche du monstre). 0 = ne spawne
    # pas sous cet élément ; vide (aucun poids défini) = tirage uniforme.
    mob_weights = mob_element_weight_loader.get_weights(code)
    weight = mob_weights.get(element, 0)
    # Onglets = éléments de la zone (+ ceux déjà placés hors zone, par sécurité).
    tab_elems = list(dict.fromkeys(list(spots.keys()) + list(placed.keys())))
    tabs = [
        {"code": e, "label": ELEMENT_LABELS.get(e, e), "emoji": ELEMENT_EMOJIS.get(e, ""),
         "placed": e in placed, "time": (spots.get(e) or {}).get("time", "always"),
         "weight": mob_weights.get(e, 0)}
        for e in tab_elems
    ]
    spot = spots.get(element)
    spot_ctx = None
    if spot:
        spot_ctx = {"background": spot.get("background", ""),
                    "crop": spot.get("crop") or {"x": 0, "y": 0, "w": 1},
                    "ground_y": spot.get("ground_y", 0.86)}
    return get_templates().TemplateResponse(
        request, "admin/scenes/mob.html",
        context={
            "user": user, "mob": mob, "element": element,
            "label": ELEMENT_LABELS.get(element, element), "emoji": ELEMENT_EMOJIS.get(element, ""),
            "placement": placement, "weight": weight, "has_weights": bool(mob_weights),
            "tabs": tabs, "is_placed": element in placed,
            "spot": spot_ctx, "has_spot": spot is not None, "zone_channel": zone_channel,
            "frame_w": fight_scene.FRAME_W, "frame_h": fight_scene.FRAME_H,
            "top_panel": fight_scene.TOP_PANEL, "bottom_panel": fight_scene.BOTTOM_PANEL,
            "saved": saved,
        },
    )


@router.get("/mob/{code}/{element}/preview.png")
async def mob_preview(code: str, element: str, request: Request,
                      user: AdminUser = Depends(require_admin)):
    with get_db_session() as session:
        mob = MobRepository(session).get_by_code(code)
    if mob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Monstre introuvable.")
    p = request.query_params
    placement = {"scale": scene_helpers.fnum(p, "scale", 0.6),
                 "offset_x": scene_helpers.fnum(p, "offset_x", 0.0),
                 "offset_y": scene_helpers.fnum(p, "offset_y", 0.0),
                 "shadow": scene_helpers.truthy(p.get("shadow"))}
    ch = farm_zone_loader.get_spawn_channel_for_family(mob.family)
    spot = farm_zone_loader.get_spot(ch, element)
    image = fight_scene.render_scene(
        mob={"code": mob.code, "name": mob.name, "image_name": mob.image_name,
             "element": element, "current_hp": max(1, int(mob.max_hp * 0.7)),
             "max_hp": mob.max_hp, "power_score": "?"},
        players=scene_helpers.demo_players(), spot=spot, placement=placement,
    )
    buf = io.BytesIO(); image.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/mob/{code}/{element}")
async def mob_save(code: str, element: str, request: Request,
                   user: AdminUser = Depends(require_admin)):
    if element not in _VALID_ELEMENTS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Élément inconnu.")
    with get_db_session() as session:
        mob = MobRepository(session).get_by_code(code)
    if mob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Monstre introuvable.")
    form = await request.form()
    entry = {
        "scale": scene_helpers.fnum(form, "scale", 0.6),
        "offset_x": scene_helpers.fnum(form, "offset_x", 0.0),
        "offset_y": scene_helpers.fnum(form, "offset_y", 0.0),
        "shadow": scene_helpers.truthy(form.get("shadow")),
    }
    data = json_writer.load_json(_MOBS_FILE, {"placements": {}}) or {"placements": {}}
    placements = data.get("placements", {})
    if not isinstance(placements, dict):
        placements = {}
    placements.setdefault(code, {})[element] = entry
    json_writer.atomic_write_json(_MOBS_FILE, {"_comment": _MOBS_COMMENT, "placements": placements})
    mob_placement_loader.reload_cache()
    _logger.info("Admin %s a placé %s/%s", user.discord_id, code, element)
    return RedirectResponse(f"/admin/scenes/mob/{code}/{element}?saved=1", status_code=303)


@router.post("/mob/{code}/{element}/delete")
async def mob_delete(code: str, element: str, user: AdminUser = Depends(require_admin)):
    data = json_writer.load_json(_MOBS_FILE, {"placements": {}}) or {"placements": {}}
    placements = data.get("placements", {})
    if isinstance(placements, dict) and code in placements and element in placements[code]:
        del placements[code][element]
        if not placements[code]:
            del placements[code]
        json_writer.atomic_write_json(_MOBS_FILE, {"_comment": _MOBS_COMMENT, "placements": placements})
        mob_placement_loader.reload_cache()
        _logger.info("Admin %s a retiré %s/%s", user.discord_id, code, element)
    return RedirectResponse(f"/admin/scenes/mob/{code}", status_code=303)
