"""Vue d'ensemble des FAMILLES de mobs (lecture).

Une famille n'est pas une entité stockée à part : c'est le champ `family` d'un
mob. Cette page agrège, par famille : les mobs qui la composent, la zone de
spawn (via farm_zones.json) et le drop commun de famille (family_drops.json).
La création/édition se fait via le mob (champ famille) et via les zones."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.encounters import farm_zone_loader
from app.infrastructure.loot.family_drop_loader import get_family_drops
from webapp.admin.auth import AdminUser, require_admin
from webapp.admin._shared import get_templates

router = APIRouter(prefix="/admin/familles", tags=["admin-familles"])


@router.get("")
async def families_overview(request: Request, user: AdminUser = Depends(require_admin)):
    farm_zone_loader.clear_cache()
    with get_db_session() as session:
        mobs = MobRepository(session).list_all()

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
        context={"user": user, "families": families_list},
    )
