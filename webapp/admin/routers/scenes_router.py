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


# ------------------------------------------------------------------ FORMATIONS
# Combats contre plusieurs monstres (meutes de zone) : où se tient chacun.
_FORMATIONS_FILE = "mob_formations.json"
_FORMATIONS_COMMENT = (
    "Formations des combats contre plusieurs monstres (meutes), par zone : "
    "formations[salon de la zone][n] = [{x, y, scale}, …] pour n = 2, 3, 4. x = décalage "
    "horizontal depuis le centre, y = décalage vertical (< 0 = plus loin, dessiné derrière), "
    "scale = multiplicateur de la taille propre du monstre. Édité dans Scènes › Formations."
)


def _formation_zones() -> list[dict]:
    farm_zone_loader.clear_cache()
    return [z for z in farm_zone_loader.list_zones() if z.get("channel_id")]


def _sample_mobs(zone: dict, n: int) -> list:
    """n monstres d'exemple de la zone (les plus courants d'abord, sans élite)."""
    from app.domain.services.mob_ability_service import is_group_elite

    with get_db_session() as session:
        mobs = [m for m in MobRepository(session).list_all()
                if m.family in zone.get("families", []) and not is_group_elite(m.code)]
    mobs.sort(key=lambda m: -m.spawn_weight)
    if not mobs:
        return []
    return [mobs[i % len(mobs)] for i in range(n)]


@router.get("/formations")
async def formations_home(request: Request, user: AdminUser = Depends(require_admin)):
    from app.infrastructure.encounters import mob_formation_loader as fl

    fl.reload_cache()
    rows = [{"key": str(z["channel_id"]), "name": z.get("name", "?"), "rank": z.get("rank", ""),
             "sizes": [{"n": n, "custom": fl.is_custom(str(z["channel_id"]), n)} for n in fl.SIZES]}
            for z in _formation_zones()]
    return get_templates().TemplateResponse(
        request, "admin/scenes/formations.html", context={"user": user, "zones": rows})


@router.get("/formations/{key}/{n}")
async def formation_editor(key: str, n: int, request: Request, saved: int = 0,
                           user: AdminUser = Depends(require_admin)):
    from app.infrastructure.encounters import mob_formation_loader as fl

    zone = next((z for z in _formation_zones() if str(z["channel_id"]) == key), None)
    if zone is None or n not in fl.SIZES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Zone ou taille inconnue.")
    fl.reload_cache()
    return get_templates().TemplateResponse(
        request, "admin/scenes/formation.html",
        context={"user": user, "key": key, "n": n, "zone": zone, "sizes": fl.SIZES,
                 "slots": fl.get_formation(key, n), "custom": fl.is_custom(key, n),
                 "samples": [m.name for m in _sample_mobs(zone, n)], "saved": saved})


def _slots_from(params, n: int) -> list[dict]:
    return [{"x": round(scene_helpers.fnum(params, f"x{i}", 0.0), 4),
             "y": round(scene_helpers.fnum(params, f"y{i}", 0.0), 4),
             "scale": round(max(0.1, scene_helpers.fnum(params, f"s{i}", 1.0)), 4)}
            for i in range(n)]


@router.get("/formations/{key}/{n}/preview.png")
async def formation_preview(key: str, n: int, request: Request,
                            user: AdminUser = Depends(require_admin)):
    """Aperçu RÉEL (même rendu que le bot) avec des monstres de la zone."""
    from app.infrastructure.encounters import mob_formation_loader as fl
    from app.shared.paths import LANDSCAPES_ASSETS_DIR

    zone = next((z for z in _formation_zones() if str(z["channel_id"]) == key), None)
    if zone is None or n not in fl.SIZES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Zone ou taille inconnue.")
    spots = farm_zone_loader.get_spots(int(key))
    spot = spots[0] if spots else None
    element = (spot or {}).get("element", "") or ""
    mobs = _sample_mobs(zone, n)
    payloads = [{"code": m.code, "name": m.name, "image_name": m.image_name, "element": element,
                 "current_hp": max(1, int(m.max_hp * (0.4 + 0.15 * i))), "max_hp": m.max_hp}
                for i, m in enumerate(mobs)]
    placements = [mob_placement_loader.get_placement(m.code, element) for m in mobs]
    background = farm_zone_loader.get_background_for_family((zone.get("families") or [""])[0])
    image = fight_scene.render_scene(
        mob=None, mobs=payloads, placements=placements, formation=_slots_from(request.query_params, n),
        players=scene_helpers.demo_players(), spot=spot,
        background_path=str(LANDSCAPES_ASSETS_DIR / background) if background else None,
    )
    buf = io.BytesIO(); image.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/formations/{key}/{n}")
async def formation_save(key: str, n: int, request: Request,
                         user: AdminUser = Depends(require_admin)):
    from app.infrastructure.encounters import mob_formation_loader as fl

    if not any(str(z["channel_id"]) == key for z in _formation_zones()) or n not in fl.SIZES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Zone ou taille inconnue.")
    form = await request.form()
    data = json_writer.load_json(_FORMATIONS_FILE, {"formations": {}}) or {"formations": {}}
    formations = data.get("formations") if isinstance(data.get("formations"), dict) else {}
    if form.get("reset"):
        (formations.get(key) or {}).pop(str(n), None)
        if key in formations and not formations[key]:
            del formations[key]
    else:
        formations.setdefault(key, {})[str(n)] = _slots_from(form, n)
    json_writer.atomic_write_json(_FORMATIONS_FILE, {"_comment": _FORMATIONS_COMMENT, "formations": formations})
    fl.reload_cache()
    _logger.info("Admin %s a réglé la formation %s/%s", user.discord_id, key, n)
    return RedirectResponse(f"/admin/scenes/formations/{key}/{n}?saved=1", status_code=303)
