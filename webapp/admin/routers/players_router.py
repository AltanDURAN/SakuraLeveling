"""Routes admin pour les joueurs : listing + reset_player."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, status, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app.application.services.player_stats_resolver import resolve_player_stats
from app.application.use_cases.reset_player import ResetPlayerUseCase
from app.domain.services.power_score_service import PowerScoreService
from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_career_stats_repository import (
    PlayerCareerStatsRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session
from webapp.admin.auth import AdminUser, require_admin
from webapp.admin._shared import get_templates


_logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/players", tags=["admin-players"])




@router.get("", response_class=HTMLResponse)
async def players_list(
    request: Request,
    user: AdminUser = Depends(require_admin),
    q: str | None = None,
):
    with get_db_session() as session:
        profiles = PlayerRepository(session).list_all_profiles()

    rows = []
    for p in profiles:
        rows.append({
            "id": p.player.id,
            "discord_id": p.player.discord_id,
            "username": p.player.username,
            "display_name": p.player.display_name,
            "level": p.progression.level,
            "xp": p.progression.xp,
            "skill_points": p.progression.skill_points,
            "gold": p.resources.gold,
            "daily_streak": p.resources.daily_streak,
            "last_seen": p.player.last_seen_at.strftime("%Y-%m-%d %H:%M"),
        })

    if q:
        ql = q.lower()
        rows = [
            r for r in rows
            if ql in str(r["discord_id"])
            or ql in r["username"].lower()
            or ql in r["display_name"].lower()
        ]

    rows.sort(key=lambda r: -r["level"])

    return get_templates().TemplateResponse(
        request, "admin/players/list.html",
        context={"user": user, "rows": rows, "filter_q": q or ""},
    )


@router.get("/{player_id}/view", response_class=HTMLResponse)
async def players_view(
    player_id: int, request: Request,
    user: AdminUser = Depends(require_admin),
):
    """Fiche complète d'un joueur : profil, stats calculées, équipement, inventaire."""
    with get_db_session() as session:
        repo = PlayerRepository(session)
        profile = repo.get_profile_by_player_id(player_id)
        if profile is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Player #{player_id} introuvable.")

        equipped = EquipmentRepository(session).list_by_player_id(player_id)
        inventory = InventoryRepository(session).list_by_player_id(player_id)
        active_class = ClassRepository(session).get_current_class_for_player(player_id)
        career = PlayerCareerStatsRepository(session).get_or_create(player_id)

        # Stats finales (skill + titre + set bonuses) via le resolver centralisé.
        try:
            stats = resolve_player_stats(session, profile, equipped, active_class)
            pss = PowerScoreService()
            power = pss.calculate_from_stats(stats)
            rank = pss.compute_rank(power)
        except Exception:  # défensif : ne jamais casser la fiche admin
            _logger.warning("calcul stats échoué pour player %s", player_id, exc_info=True)
            stats = power = rank = None

        ctx = {
            "user": user,
            "p": {
                "id": profile.player.id,
                "discord_id": profile.player.discord_id,
                "username": profile.player.username,
                "display_name": profile.player.display_name,
                "level": profile.progression.level,
                "xp": profile.progression.xp,
                "skill_points": profile.progression.skill_points,
                "gold": profile.resources.gold,
                "daily_streak": profile.resources.daily_streak,
                "class": active_class.name if active_class else "—",
            },
            "stats": stats,
            "power": power,
            "rank": rank,
            "equipment": sorted(
                [
                    {
                        "slot": e.slot,
                        "code": e.item_definition.code,
                        "name": e.item_definition.name,
                        "family": e.item_definition.family or "",
                    }
                    for e in equipped
                ],
                key=lambda x: x["slot"],
            ),
            "inventory": sorted(
                [
                    {
                        "code": it.item_definition.code,
                        "name": it.item_definition.name,
                        "category": it.item_definition.category,
                        "quantity": it.quantity,
                    }
                    for it in inventory
                ],
                key=lambda x: (x["category"], x["code"]),
            ),
            "career": career,
        }
    return get_templates().TemplateResponse(request, "admin/players/view.html", context=ctx)


@router.post("/{player_id}/reset")
async def players_reset(
    player_id: int,
    user: AdminUser = Depends(require_admin),
):
    with get_db_session() as session:
        profile = PlayerRepository(session).get_profile_by_player_id(player_id)
        if profile is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Player #{player_id} introuvable.")
        ResetPlayerUseCase().execute(session, player_id)
        _logger.info("Admin %s reset player %s (%s)", user.discord_id, player_id, profile.player.display_name)
    return RedirectResponse("/admin/players", status_code=303)


@router.get("/{player_id}/edit", response_class=HTMLResponse)
async def players_edit_form(
    player_id: int, request: Request,
    user: AdminUser = Depends(require_admin),
):
    with get_db_session() as session:
        profile = PlayerRepository(session).get_profile_by_player_id(player_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Player #{player_id} introuvable.")
    return get_templates().TemplateResponse(
        request, "admin/players/form.html",
        context={"user": user, "profile": profile},
    )


@router.post("/{player_id}")
async def players_update(
    player_id: int, request: Request,
    user: AdminUser = Depends(require_admin),
):
    form = await request.form()
    with get_db_session() as session:
        repo = PlayerRepository(session)
        profile = repo.get_profile_by_player_id(player_id)
        if profile is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Player #{player_id} introuvable.")

        def _i(key, default):
            try:
                return int(str(form.get(key, default)).strip())
            except (ValueError, TypeError):
                return default

        new_level = max(1, _i("level", profile.progression.level))
        new_xp = max(0, _i("xp", profile.progression.xp))
        new_sp = max(0, _i("skill_points", profile.progression.skill_points))
        new_gold = max(0, _i("gold", profile.resources.gold))
        new_streak = max(0, _i("daily_streak", profile.resources.daily_streak))

        repo.apply_progression(
            player_id=player_id,
            new_level=new_level,
            new_xp=new_xp,
            new_skill_points=new_sp,
        )
        repo.set_gold(player_id, new_gold)
        repo.set_daily_streak(player_id, new_streak)
        _logger.info(
            "Admin %s edited player %s : level=%s xp=%s sp=%s gold=%s streak=%s",
            user.discord_id, player_id, new_level, new_xp, new_sp, new_gold, new_streak,
        )
    return RedirectResponse("/admin/players", status_code=303)
