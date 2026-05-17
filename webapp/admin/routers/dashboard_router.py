"""Routes du dashboard admin (home avec compteurs pour toutes les entités)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from webapp.admin.auth import AdminUser, require_admin


router = APIRouter(prefix="/admin", tags=["admin-dashboard"])

CONTENT_DIR = Path(__file__).resolve().parents[3] / "app" / "infrastructure" / "content"


def get_templates():
    from webapp.main import templates
    return templates


def _load_json(filename: str):
    path = CONTENT_DIR / filename
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _count_json_top_level(filename: str) -> int:
    data = _load_json(filename)
    if data is None:
        return 0
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        return len(data)
    return 0


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request, user: AdminUser = Depends(require_admin),
):
    """Page d'accueil de l'admin : grille des entités gérables."""
    from app.infrastructure.db.repositories.item_repository import ItemRepository
    from app.infrastructure.db.repositories.mob_repository import MobRepository
    from app.infrastructure.db.repositories.player_repository import PlayerRepository
    from app.infrastructure.db.repositories.shop_repository import ShopRepository
    from app.infrastructure.db.models.craft_model import CraftRecipeModel
    from app.infrastructure.db.session import get_db_session
    from sqlalchemy import select, func

    with get_db_session() as session:
        items_count = len(ItemRepository(session).list_all())
        mobs_count = len(MobRepository(session).list_all())
        players_count = len(PlayerRepository(session).list_all_profiles())
        shop_count = len(ShopRepository(session).list_all(only_enabled=False))
        crafts_count = session.execute(select(func.count()).select_from(CraftRecipeModel)).scalar() or 0

    skill_data = _load_json("skill_tree.json") or {}
    skill_nodes_count = len(skill_data.get("skills", {})) if isinstance(skill_data, dict) else 0

    return get_templates().TemplateResponse(
        request, "admin/dashboard.html",
        context={
            "user": user,
            "items_count": items_count,
            "mobs_count": mobs_count,
            "classes_count": _count_json_top_level("classes.json"),
            "crafts_count": crafts_count,
            "skill_nodes_count": skill_nodes_count,
            "panoplies_count": _count_json_top_level("sets.json"),
            "titles_count": _count_json_top_level("titles.json"),
            "quests_count": _count_json_top_level("daily_quests.json") + _count_json_top_level("weekly_quests.json"),
            "bosses_count": _count_json_top_level("boss_definitions.json"),
            "shop_count": shop_count,
            "players_count": players_count,
        },
    )
