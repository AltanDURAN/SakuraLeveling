"""Familles de mobs : édition du DROP DE FAMILLE (ressource garantie).

Une famille = le champ `family` des mobs. Chaque famille lâche UNE ressource
commune, avec un [min,max] PAR MONSTRE (drop garanti à chaque kill). On édite
ça ici : liste des familles → clic → membres + item + min/max par membre.
Écrit dans family_drops.json (reseed-safe, auto-poussé git)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.encounters import farm_zone_loader
from app.infrastructure.loot import family_drop_loader
from app.shared.enums import ITEM_CATEGORY_EMOJIS, ITEM_CATEGORY_LABELS
from webapp.admin import content_sync
from webapp.admin.auth import AdminUser, require_admin
from webapp.admin._shared import get_templates

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/familles", tags=["admin-familles"])


def _families_with_mobs(mobs) -> dict[str, list]:
    fams: dict[str, list] = {}
    for m in mobs:
        fams.setdefault(m.family or "unknown", []).append(m)
    return fams


def _parse_int(raw, default: int = 0) -> int:
    try:
        return max(0, int(str(raw).strip()))
    except (TypeError, ValueError):
        return default


@router.get("")
async def families_overview(request: Request, user: AdminUser = Depends(require_admin)):
    farm_zone_loader.clear_cache()
    family_drop_loader.clear_cache()
    with get_db_session() as session:
        mobs = MobRepository(session).list_all()
        items = {it.code: it for it in ItemRepository(session).list_all()}
    drops = family_drop_loader.get_family_drops() or {}

    zone_by_family: dict[str, dict] = {}
    for z in farm_zone_loader.list_zones():
        for fam in z.get("families", []):
            zone_by_family[fam] = z

    rows = []
    for fam, fam_mobs in sorted(_families_with_mobs(mobs).items()):
        cfg = drops.get(fam) or {}
        item = items.get(cfg.get("item_code"))
        rows.append({
            "name": fam, "mob_count": len(fam_mobs),
            "zone": (zone_by_family.get(fam) or {}).get("name", ""),
            "item_code": cfg.get("item_code", ""),
            "item_name": item.name if item else cfg.get("item_code", ""),
            "configured": len((cfg.get("mobs") or {})),
        })
    return get_templates().TemplateResponse(
        request, "admin/families/list.html",
        context={"user": user, "families": rows},
    )


@router.get("/{family}")
async def family_detail(family: str, request: Request, saved: int = 0,
                        user: AdminUser = Depends(require_admin)):
    family_drop_loader.clear_cache()
    with get_db_session() as session:
        all_mobs = MobRepository(session).list_all()
        items = ItemRepository(session).list_all()
    members = [m for m in all_mobs if (m.family or "unknown") == family]
    if not members:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Famille `{family}` introuvable.")

    cfg = (family_drop_loader.get_family_drops() or {}).get(family) or {}
    per_mob = cfg.get("mobs") or {}
    member_rows = []
    for m in sorted(members, key=lambda x: x.name):
        e = per_mob.get(m.code) or {}
        member_rows.append({
            "code": m.code, "name": m.name, "image_name": m.image_name,
            "element": m.element or "",
            "min": int(e.get("min", 1)), "max": int(e.get("max", 1)),
        })
    resources = sorted(
        [{"code": it.code, "name": it.name}
         for it in items if it.category == "resource"],
        key=lambda x: x["name"],
    )
    return get_templates().TemplateResponse(
        request, "admin/families/detail.html",
        context={
            "user": user, "family": family, "members": member_rows,
            "item_code": cfg.get("item_code", ""), "resources": resources,
            "res_emoji": ITEM_CATEGORY_EMOJIS.get("resource", "🪵"),
            "res_label": ITEM_CATEGORY_LABELS.get("resource", "Ressource"),
            "saved": saved,
        },
    )


@router.post("/{family}")
async def family_save(family: str, request: Request, user: AdminUser = Depends(require_admin)):
    form = {k: str(v) for k, v in (await request.form()).items()}
    item_code = form.get("item_code", "").strip()
    if not item_code:
        content_sync.delete_family_drop_json(family)
        family_drop_loader.clear_cache()
        _logger.info("Admin %s a retiré le drop de la famille %s", user.discord_id, family)
        return RedirectResponse(f"/admin/familles/{family}?saved=1", status_code=303)

    with get_db_session() as session:
        members = [m.code for m in MobRepository(session).list_all()
                   if (m.family or "unknown") == family]
    mobs: dict[str, dict] = {}
    for code in members:
        lo = _parse_int(form.get(f"min_{code}"), 1)
        hi = max(lo, _parse_int(form.get(f"max_{code}"), lo))
        mobs[code] = {"min": lo, "max": hi}
    content_sync.upsert_family_drop_json(family, item_code, mobs)
    family_drop_loader.clear_cache()
    _logger.info("Admin %s a défini le drop de %s → %s (%d membres)",
                 user.discord_id, family, item_code, len(mobs))
    return RedirectResponse(f"/admin/familles/{family}?saved=1", status_code=303)
