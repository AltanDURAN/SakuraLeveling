"""Routes admin pour les joueurs : listing + reset_player."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, status, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app.application.use_cases.reset_player import ResetPlayerUseCase
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session
from webapp.admin.auth import AdminUser, require_admin


_logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/players", tags=["admin-players"])


def get_templates():
    from webapp.main import templates
    return templates


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
