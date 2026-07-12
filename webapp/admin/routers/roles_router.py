"""Routes admin : gestion des rôles Discord du serveur.

Deux vues : par rôle (qui possède quoi) et par membre (chacun a quels rôles).
Ajout/retrait de rôles + CRUD de rôles, via l'API Discord (bot token).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.infrastructure.config.settings import settings
from webapp.admin import discord_api
from webapp.admin._shared import get_templates, parse_int
from webapp.admin.auth import AdminUser, require_admin

_logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/roles", tags=["admin-roles"])


def _color_hex(color: int) -> str:
    """Couleur Discord (int décimal) → #rrggbb. 0 = gris par défaut."""
    if not color:
        return "#99aab5"
    return f"#{color & 0xFFFFFF:06x}"


def _member_name(member: dict) -> str:
    user = member.get("user", {})
    return member.get("nick") or user.get("global_name") or user.get("username") or "?"


def _avatar_url(member: dict) -> str:
    user = member.get("user", {})
    av = user.get("avatar")
    uid = user.get("id")
    if av and uid:
        ext = "gif" if str(av).startswith("a_") else "png"
        return f"https://cdn.discordapp.com/avatars/{uid}/{av}.{ext}?size=32"
    return "https://cdn.discordapp.com/embed/avatars/0.png"


async def _load(guild_id: int):
    """Charge rôles + membres. Renvoie (roles, members, error)."""
    ok_r, roles = await discord_api.list_roles(guild_id)
    if not ok_r:
        return [], [], str(roles)
    ok_m, members = await discord_api.list_members(guild_id)
    if not ok_m:
        return roles, [], str(members)
    return roles, members, None


def _guild_or_none():
    gid = settings.discord_guild_id
    return gid or None


@router.get("", response_class=HTMLResponse)
@router.get("/by-role", response_class=HTMLResponse)
async def roles_by_role(request: Request, user: AdminUser = Depends(require_admin)):
    gid = _guild_or_none()
    if gid is None:
        return get_templates().TemplateResponse(
            request, "admin/roles/disabled.html", {"user": user})

    roles, members, error = await _load(gid)
    # Map role_id -> membres qui l'ont (hors @everyone = id du guild).
    by_role: dict[str, list[dict]] = {r["id"]: [] for r in roles}
    for m in members:
        for rid in m.get("roles", []):
            if rid in by_role:
                by_role[rid].append({"name": _member_name(m), "avatar": _avatar_url(m),
                                      "user_id": m["user"]["id"]})
    roles_ctx = [{
        "id": r["id"], "name": r["name"], "color": _color_hex(r.get("color", 0)),
        "position": r.get("position", 0), "managed": r.get("managed", False),
        "everyone": r["id"] == str(gid),
        "members": sorted(by_role.get(r["id"], []), key=lambda x: x["name"].lower()),
        "count": len(by_role.get(r["id"], [])),
    } for r in roles]

    return get_templates().TemplateResponse(request, "admin/roles/by_role.html", {
        "user": user, "roles": roles_ctx, "error": error,
        "member_count": len(members), "guild_id": gid,
    })


@router.get("/by-member", response_class=HTMLResponse)
async def roles_by_member(request: Request, user: AdminUser = Depends(require_admin)):
    gid = _guild_or_none()
    if gid is None:
        return get_templates().TemplateResponse(
            request, "admin/roles/disabled.html", {"user": user})

    roles, members, error = await _load(gid)
    role_map = {r["id"]: r for r in roles}
    # Rôles assignables (hors @everoyne, hors rôles gérés par une intégration).
    assignable = [
        {"id": r["id"], "name": r["name"], "color": _color_hex(r.get("color", 0))}
        for r in roles
        if r["id"] != str(gid) and not r.get("managed", False)
    ]
    members_ctx = []
    for m in members:
        member_roles = []
        for rid in m.get("roles", []):
            r = role_map.get(rid)
            if r is None or rid == str(gid):
                continue
            member_roles.append({"id": rid, "name": r["name"],
                                  "color": _color_hex(r.get("color", 0)),
                                  "managed": r.get("managed", False)})
        member_roles.sort(key=lambda x: x["name"].lower())
        members_ctx.append({
            "user_id": m["user"]["id"], "name": _member_name(m),
            "username": m["user"].get("username", ""),
            "avatar": _avatar_url(m), "bot": m["user"].get("bot", False),
            "roles": member_roles,
        })
    members_ctx.sort(key=lambda x: x["name"].lower())

    return get_templates().TemplateResponse(request, "admin/roles/by_member.html", {
        "user": user, "members": members_ctx, "assignable": assignable,
        "error": error, "guild_id": gid,
    })


# ---------- actions (POST) ----------

@router.post("/member/{user_id}/add")
async def add_role(user_id: int, request: Request, user: AdminUser = Depends(require_admin)):
    form = await request.form()
    role_id = parse_int(form.get("role_id"))
    back = form.get("back", "/admin/roles/by-member")
    gid = _guild_or_none()
    if gid and role_id:
        ok, err = await discord_api.add_member_role(
            gid, user_id, role_id, reason=f"admin web ({user.username})")
        if not ok:
            _logger.warning("add_role fail: %s", err)
    return RedirectResponse(back, status_code=303)


@router.post("/member/{user_id}/remove")
async def remove_role(user_id: int, request: Request, user: AdminUser = Depends(require_admin)):
    form = await request.form()
    role_id = parse_int(form.get("role_id"))
    back = form.get("back", "/admin/roles/by-member")
    gid = _guild_or_none()
    if gid and role_id:
        ok, err = await discord_api.remove_member_role(
            gid, user_id, role_id, reason=f"admin web ({user.username})")
        if not ok:
            _logger.warning("remove_role fail: %s", err)
    return RedirectResponse(back, status_code=303)


@router.post("/create")
async def create_role(request: Request, user: AdminUser = Depends(require_admin)):
    form = await request.form()
    name = (form.get("name") or "").strip()
    color = int((form.get("color") or "#000000").lstrip("#") or "0", 16)
    gid = _guild_or_none()
    if gid and name:
        await discord_api.create_role(gid, name, color, hoist=bool(form.get("hoist")),
                                      mentionable=bool(form.get("mentionable")),
                                      reason=f"admin web ({user.username})")
    return RedirectResponse("/admin/roles/by-role", status_code=303)


@router.post("/{role_id}/edit")
async def edit_role(role_id: int, request: Request, user: AdminUser = Depends(require_admin)):
    form = await request.form()
    name = (form.get("name") or "").strip()
    color = int((form.get("color") or "#000000").lstrip("#") or "0", 16)
    gid = _guild_or_none()
    if gid and name:
        await discord_api.edit_role(gid, role_id, name, color, hoist=bool(form.get("hoist")),
                                    mentionable=bool(form.get("mentionable")),
                                    reason=f"admin web ({user.username})")
    return RedirectResponse("/admin/roles/by-role", status_code=303)


@router.post("/{role_id}/delete")
async def delete_role(role_id: int, request: Request, user: AdminUser = Depends(require_admin)):
    gid = _guild_or_none()
    if gid:
        await discord_api.delete_role(gid, role_id, reason=f"admin web ({user.username})")
    return RedirectResponse("/admin/roles/by-role", status_code=303)
