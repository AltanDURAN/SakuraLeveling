"""Routes admin pour gérer les ZONES de farm (farm_zones.json).

Une zone = un salon Discord + les familles de mobs qui y spawnent + un décor +
une fourchette d'essences élémentaires droppées par kill. Reseed-safe : écrit
directement farm_zones.json (source de vérité, pas de DB). Le bot doit être
redémarré pour que les changements de zone prennent effet (process séparé,
cache module-level)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.encounters import farm_zone_loader
from app.shared.enums import ELEMENT_EMOJIS, ELEMENT_LABELS
from app.shared.paths import LANDSCAPES_ASSETS_DIR
from webapp.admin import content_sync, git_sync, uploads
from webapp.admin.auth import AdminUser, require_admin
from webapp.admin._shared import get_templates

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/zones", tags=["admin-zones"])


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
            "errors": {}, "all_families": _all_families(),
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
                "errors": errors, "all_families": _all_families(),
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
            "errors": {}, "all_families": _all_families(),
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
                "errors": errors, "all_families": _all_families(),
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
