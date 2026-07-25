"""Routes admin pour gérer les ZONES de farm (farm_zones.json).

Une zone = un salon Discord + les familles de mobs qui y spawnent + un décor +
une fourchette d'essences élémentaires droppées par kill. Reseed-safe : écrit
directement farm_zones.json (source de vérité, pas de DB). Le bot doit être
redémarré pour que les changements de zone prennent effet (process séparé,
cache module-level)."""

from __future__ import annotations

import io
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from PIL import Image

from app.bot.rendering import fight_scene
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.encounters import farm_zone_loader, mob_placement_loader
from app.shared.enums import ALL_ELEMENTS, ELEMENT_EMOJIS, ELEMENT_LABELS
from app.shared.paths import LANDSCAPES_ASSETS_DIR
from webapp.admin import content_sync, git_sync, json_writer, scene_helpers, uploads
from webapp.admin.auth import AdminUser, require_admin
from webapp.admin._shared import get_templates

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/zones", tags=["admin-zones"])

# Contexte éléments injecté dans le formulaire de zone (section spots).
_ELEMENT_CTX = {
    "all_elements": [e.value for e in ALL_ELEMENTS],
    "element_emojis": ELEMENT_EMOJIS,
    "element_labels": ELEMENT_LABELS,
}


async def _save_zone_background(form) -> tuple[str | None, str | None, str | None]:
    """Si un décor a été uploadé, l'enregistre dans assets/landscapes/ et renvoie
    (filename, asset_path_git, error). Sinon (None, None, None)."""
    upload = form.get("background_file")
    if upload is None or not getattr(upload, "filename", ""):
        return None, None, None
    data = await upload.read()
    try:
        saved = uploads.save_asset_bytes(data, upload.filename, LANDSCAPES_ASSETS_DIR)
    except uploads.UploadError as exc:
        return None, None, str(exc)
    return saved, f"assets/landscapes/{saved}", None


def _parse_int(value, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _all_families() -> list[str]:
    with get_db_session() as session:
        return MobRepository(session).list_distinct_families()


@router.get("")
async def zones_list(request: Request, user: AdminUser = Depends(require_admin)):
    farm_zone_loader.clear_cache()
    zones = farm_zone_loader.list_zones()
    defaults = {
        "channel_id": farm_zone_loader.default_channel_id(),
        "background": farm_zone_loader.default_background(),
        "essences_range": farm_zone_loader.default_essences_range(),
    }
    return get_templates().TemplateResponse(
        request, "admin/zones/list.html",
        context={"user": user, "zones": zones, "defaults": defaults,
                 "element_emojis": ELEMENT_EMOJIS, "element_labels": ELEMENT_LABELS},
    )


@router.get("/new")
async def zones_new_form(request: Request, user: AdminUser = Depends(require_admin)):
    return get_templates().TemplateResponse(
        request, "admin/zones/form.html",
        context={
            "user": user, "zone": None, "form_data": {},
            "errors": {}, "all_families": _all_families(), **_ELEMENT_CTX,
        },
    )


def _read_zone_form(form_data: dict) -> tuple[dict, dict]:
    """Valide + construit une entrée de zone depuis le form. Renvoie (zone, errors)."""
    errors: dict[str, str] = {}
    name = form_data.get("name", "").strip()
    channel_id = _parse_int(form_data.get("channel_id"), 0)
    if not name:
        errors["name"] = "Nom requis."
    if channel_id <= 0:
        errors["channel_id"] = "ID de salon requis (entier > 0)."
    essences_min = max(0, _parse_int(form_data.get("essences_min"), 1))
    essences_max = max(essences_min, _parse_int(form_data.get("essences_max"), essences_min))
    zone = content_sync.build_zone_dict(
        name=name,
        channel_id=channel_id,
        families=form_data.get("families", ""),
        background=form_data.get("background", "").strip(),
        essences_min=essences_min,
        essences_max=essences_max,
    )
    return zone, errors


@router.post("")
async def zones_create(request: Request, user: AdminUser = Depends(require_admin)):
    form = await request.form()
    form_data = {k: str(v) for k, v in form.items() if k != "background_file"}
    saved_bg, bg_asset, bg_err = await _save_zone_background(form)
    if saved_bg:
        form_data["background"] = saved_bg
    zone, errors = _read_zone_form(form_data)
    if bg_err:
        errors["background_file"] = bg_err
    if errors:
        return get_templates().TemplateResponse(
            request, "admin/zones/form.html",
            context={
                "user": user, "zone": None, "form_data": form_data,
                "errors": errors, "all_families": _all_families(), **_ELEMENT_CTX,
            },
            status_code=400,
        )
    content_sync.upsert_zone_json(zone)
    push_paths = ["app/infrastructure/content/farm_zones.json"]
    if bg_asset:
        push_paths.append(bg_asset)
    git_sync.push_content(push_paths, f"admin: zone {zone['name']} créée")
    _logger.info("Admin %s a créé la zone %s (channel %s)",
                 user.discord_id, zone["name"], zone["channel_id"])
    return RedirectResponse("/admin/zones", status_code=303)


@router.get("/{channel_id}/edit")
async def zones_edit_form(
    channel_id: int, request: Request, user: AdminUser = Depends(require_admin),
):
    farm_zone_loader.clear_cache()
    zone = next(
        (z for z in farm_zone_loader.list_zones()
         if int(z.get("channel_id", 0) or 0) == channel_id),
        None,
    )
    if zone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Zone `{channel_id}` introuvable.")
    return get_templates().TemplateResponse(
        request, "admin/zones/form.html",
        context={
            "user": user, "zone": zone, "form_data": {},
            "errors": {}, "all_families": _all_families(), **_ELEMENT_CTX,
        },
    )


@router.post("/{channel_id}")
async def zones_update(
    channel_id: int, request: Request, user: AdminUser = Depends(require_admin),
):
    form = await request.form()
    form_data = {k: str(v) for k, v in form.items() if k != "background_file"}
    saved_bg, bg_asset, bg_err = await _save_zone_background(form)
    if saved_bg:
        form_data["background"] = saved_bg
    zone, errors = _read_zone_form(form_data)
    if bg_err:
        errors["background_file"] = bg_err
    if errors:
        # Réinjecte le channel_id d'origine pour l'action du formulaire.
        zone_ctx = {**zone, "channel_id": channel_id}
        return get_templates().TemplateResponse(
            request, "admin/zones/form.html",
            context={
                "user": user, "zone": zone_ctx, "form_data": form_data,
                "errors": errors, "all_families": _all_families(), **_ELEMENT_CTX,
            },
            status_code=400,
        )
    content_sync.upsert_zone_json(zone, original_channel_id=channel_id)
    push_paths = ["app/infrastructure/content/farm_zones.json"]
    if bg_asset:
        push_paths.append(bg_asset)
    git_sync.push_content(push_paths, f"admin: zone {zone['name']} éditée")
    _logger.info("Admin %s a édité la zone %s (channel %s→%s)",
                 user.discord_id, zone["name"], channel_id, zone["channel_id"])
    return RedirectResponse("/admin/zones", status_code=303)


@router.post("/{channel_id}/delete")
async def zones_delete(channel_id: int, user: AdminUser = Depends(require_admin)):
    content_sync.delete_zone_json(channel_id)
    git_sync.push_content(
        ["app/infrastructure/content/farm_zones.json"],
        f"admin: zone {channel_id} supprimée",
    )
    _logger.info("Admin %s a supprimé la zone channel %s", user.discord_id, channel_id)
    return RedirectResponse("/admin/zones", status_code=303)


# ============================================================ SPOTS (décor/élément)
# Un « spot » = décor d'un couple (zone × élément) : image de fond + cadrage
# (zoom/pan) + ligne de sol + fenêtre horaire (always/day/night). Édité en
# WYSIWYG (rendu par le MÊME code que le bot). Stocké dans zones[].spots[].
_ZONES_FILE = "farm_zones.json"


def _find_zone_spot(channel_id: int, element: str) -> tuple[dict, dict | None]:
    data = json_writer.load_json(_ZONES_FILE, {}) or {}
    for z in data.get("zones", []):
        if int(z.get("channel_id", 0) or 0) == channel_id:
            for s in z.get("spots", []) or []:
                if str(s.get("element", "")).lower() == element.lower():
                    return z, s
            return z, None
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"Zone {channel_id} introuvable.")


def _sample_mob_for_zone(zone: dict, element: str) -> dict | None:
    """Un monstre d'exemple (le 1er de la zone) pour juger l'échelle du décor."""
    with get_db_session() as session:
        for m in MobRepository(session).list_all():
            if m.family in (zone.get("families") or []):
                return {
                    "code": m.code, "name": m.name, "image_name": m.image_name,
                    "element": element, "current_hp": max(1, int(m.max_hp * 0.7)),
                    "max_hp": m.max_hp, "power_score": "?",
                }
    return None


@router.get("/{channel_id}/spot/{element}")
async def spot_composer(
    channel_id: int, element: str, request: Request, saved: int = 0,
    user: AdminUser = Depends(require_admin),
):
    element = element.strip().lower()
    farm_zone_loader.clear_cache()
    zone, spot = _find_zone_spot(channel_id, element)
    if spot is None:
        spot = {"element": element, "time": "always",
                "background": zone.get("background", ""),
                "crop": {"x": 0.11, "y": 0.12, "w": 0.78}, "ground_y": 0.86}
    sample = _sample_mob_for_zone(zone, element)
    return get_templates().TemplateResponse(
        request, "admin/zones/spot.html",
        context={
            "user": user, "zone": zone, "element": element,
            "label": ELEMENT_LABELS.get(element, element),
            "emoji": ELEMENT_EMOJIS.get(element, ""),
            "spot": spot,
            "sample": {"code": sample["code"], "image_name": sample["image_name"]} if sample else None,
            "backgrounds": scene_helpers.list_backgrounds(),
            "frame_w": fight_scene.FRAME_W, "frame_h": fight_scene.FRAME_H,
            "top_panel": fight_scene.TOP_PANEL, "bottom_panel": fight_scene.BOTTOM_PANEL,
            "saved": saved,
        },
    )


@router.get("/{channel_id}/spot/{element}/preview.png")
async def spot_preview(
    channel_id: int, element: str, request: Request,
    user: AdminUser = Depends(require_admin),
):
    element = element.strip().lower()
    zone, _ = _find_zone_spot(channel_id, element)
    p = request.query_params
    spot = {"background": scene_helpers.safe(p.get("background", "")),
            "crop": {"x": scene_helpers.fnum(p, "crop_x", 0),
                     "y": scene_helpers.fnum(p, "crop_y", 0),
                     "w": scene_helpers.fnum(p, "crop_w", 1)},
            "ground_y": scene_helpers.fnum(p, "ground_y", 0.86)}
    sample_mob = _sample_mob_for_zone(zone, element)
    placement = mob_placement_loader.get_placement(sample_mob["code"], element) if sample_mob else None
    image = fight_scene.render_scene(mob=sample_mob, players=scene_helpers.demo_players(),
                                     spot=spot, placement=placement)
    buf = io.BytesIO(); image.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


def _write_spots(channel_id: int, mutate) -> None:
    """Charge farm_zones.json, applique `mutate(spots_list)` sur la zone, réécrit
    (auto-push git) et invalide le cache."""
    data = json_writer.load_json(_ZONES_FILE, {}) or {}
    for z in data.get("zones", []):
        if int(z.get("channel_id", 0) or 0) == channel_id:
            mutate(z.setdefault("spots", []))
            break
    else:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Zone {channel_id} introuvable.")
    json_writer.atomic_write_json(_ZONES_FILE, data)
    farm_zone_loader.clear_cache()


@router.post("/{channel_id}/spot/{element}")
async def spot_save(
    channel_id: int, element: str, request: Request,
    user: AdminUser = Depends(require_admin),
):
    element = element.strip().lower()
    form = await request.form()
    background = scene_helpers.safe(str(form.get("background", "")))
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
        "crop": {"x": scene_helpers.fnum(form, "crop_x", 0),
                 "y": scene_helpers.fnum(form, "crop_y", 0),
                 "w": scene_helpers.fnum(form, "crop_w", 1)},
        "ground_y": scene_helpers.fnum(form, "ground_y", 0.86),
    }

    def _mut(spots):
        for i, s in enumerate(spots):
            if str(s.get("element", "")).lower() == element:
                spots[i] = new_spot
                return
        spots.append(new_spot)

    _write_spots(channel_id, _mut)
    _logger.info("Admin %s a composé le spot %s/%s", user.discord_id, channel_id, element)
    return RedirectResponse(f"/admin/zones/{channel_id}/spot/{element}?saved=1", status_code=303)


@router.post("/{channel_id}/spot/{element}/add")
async def spot_add(channel_id: int, element: str, user: AdminUser = Depends(require_admin)):
    """Ajoute un élément (spot vierge) à la zone puis ouvre son compositeur."""
    element = element.strip().lower()
    if element not in {e.value for e in ALL_ELEMENTS}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Élément inconnu.")
    zone = farm_zone_loader.get_zone_by_channel(channel_id) or {}
    bg = zone.get("background", "")

    def _mut(spots):
        if any(str(s.get("element", "")).lower() == element for s in spots):
            return
        spots.append({"element": element, "time": "always", "background": bg,
                      "crop": {"x": 0.11, "y": 0.12, "w": 0.78}, "ground_y": 0.86})

    _write_spots(channel_id, _mut)
    _logger.info("Admin %s a ajouté l'élément %s à la zone %s", user.discord_id, element, channel_id)
    return RedirectResponse(f"/admin/zones/{channel_id}/spot/{element}", status_code=303)


@router.post("/{channel_id}/spot/{element}/delete")
async def spot_delete(channel_id: int, element: str, user: AdminUser = Depends(require_admin)):
    element = element.strip().lower()

    def _mut(spots):
        spots[:] = [s for s in spots if str(s.get("element", "")).lower() != element]

    _write_spots(channel_id, _mut)
    _logger.info("Admin %s a retiré l'élément %s de la zone %s", user.discord_id, element, channel_id)
    return RedirectResponse(f"/admin/zones/{channel_id}/edit", status_code=303)
