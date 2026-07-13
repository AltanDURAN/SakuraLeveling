"""Vue d'ensemble des FAMILLES de mobs (lecture).

Une famille n'est pas une entité stockée à part : c'est le champ `family` d'un
mob. Cette page agrège, par famille : les mobs qui la composent, la zone de
spawn (via farm_zones.json) et le drop commun de famille (family_drops.json).
La création/édition se fait via le mob (champ famille) et via les zones."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.encounters import farm_zone_loader
from app.infrastructure.loot.family_drop_loader import clear_cache as clear_family_drops_cache
from app.infrastructure.loot.family_drop_loader import get_family_drops
from webapp.admin import content_sync
from webapp.admin.auth import AdminUser, require_admin
from webapp.admin._shared import get_templates

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/familles", tags=["admin-familles"])


def _parse_float(raw, default=0.0) -> float:
    try:
        return float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError):
        return default


@router.get("")
async def families_overview(request: Request, user: AdminUser = Depends(require_admin)):
    farm_zone_loader.clear_cache()
    clear_family_drops_cache()
    with get_db_session() as session:
        mobs = MobRepository(session).list_all()
        item_codes = [it.code for it in ItemRepository(session).list_all()]

    # famille -> {name, channel_id} (zone qui la contient)
    zone_by_family: dict[str, dict] = {}
    for z in farm_zone_loader.list_zones():
        for fam in z.get("families", []):
            zone_by_family[fam] = z

    family_drops = get_family_drops() or {}

    families: dict[str, dict] = {}
    for m in mobs:
        fam = m.family or "unknown"
        entry = families.setdefault(fam, {
            "name": fam,
            "mobs": [],
            "zone": zone_by_family.get(fam),
            "essences": farm_zone_loader.get_essences_range_for_family(fam),
            "common_drop": family_drops.get(fam),
        })
        entry["mobs"].append({
            "code": m.code, "name": m.name, "element": m.element or "",
        })

    families_list = sorted(families.values(), key=lambda f: f["name"])
    return get_templates().TemplateResponse(
        request, "admin/families/list.html",
        context={"user": user, "families": families_list, "item_codes": sorted(item_codes)},
    )


@router.post("/{family}/drop")
async def set_family_drop(
    family: str, request: Request, user: AdminUser = Depends(require_admin),
):
    """Définit (ou retire) le drop commun d'une famille. item_code vide → retire."""
    fd = {k: str(v) for k, v in (await request.form()).items()}
    item_code = fd.get("item_code", "").strip()
    if item_code:
        drop_rate = max(0.0, min(1.0, _parse_float(fd.get("drop_rate"), 0.75)))
        content_sync.upsert_family_drop_json(family, item_code, drop_rate)
        _logger.info("Admin %s a défini le drop de %s → %s (%.2f)",
                     user.discord_id, family, item_code, drop_rate)
    else:
        content_sync.delete_family_drop_json(family)
        _logger.info("Admin %s a retiré le drop commun de %s", user.discord_id, family)
    return RedirectResponse("/admin/familles", status_code=303)
