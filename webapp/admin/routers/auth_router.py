"""Routes d'authentification admin : login, callback OAuth, logout."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from webapp.admin._shared import get_templates
from webapp.admin.auth import (
    AdminUser,
    build_authorize_url,
    clear_oauth_state,
    clear_session_cookie,
    current_user,
    exchange_code_for_token,
    fetch_user_identity,
    issue_session_cookie,
    make_state,
    read_oauth_state,
    store_oauth_state,
)
from app.infrastructure.config.settings import settings


router = APIRouter(prefix="/admin", tags=["admin-auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    user = current_user(request)
    if user is not None and user.is_admin:
        return RedirectResponse("/admin", status_code=303)
    state = make_state()
    auth_url = build_authorize_url(state)
    response = get_templates().TemplateResponse(
        request, "admin/login.html",
        context={"auth_url": auth_url, "user": user},
    )
    store_oauth_state(response, state)
    return response


@router.get("/auth/callback")
async def oauth_callback(
    request: Request, code: str | None = None, state: str | None = None,
    error: str | None = None,
):
    if error:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"OAuth refusé par Discord : {error}",
        )
    if not code or not state:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Callback OAuth mal formé (code/state manquants).",
        )
    expected_state = read_oauth_state(request)
    if expected_state is None or expected_state != state:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="OAuth state invalide — relancez la connexion.",
        )

    access_token = await exchange_code_for_token(code)
    identity = await fetch_user_identity(access_token)

    user = AdminUser(
        discord_id=int(identity["id"]),
        username=identity.get("username", "?"),
        display_name=(
            identity.get("global_name")
            or identity.get("username", "?")
        ),
    )

    if not user.is_admin:
        # Connecté mais pas admin → on l'affiche pour qu'il comprenne le refus
        response = get_templates().TemplateResponse(
            request, "admin/forbidden.html",
            context={"user": user, "admin_ids": settings.admin_ids},
            status_code=403,
        )
        clear_oauth_state(response)
        return response

    response = RedirectResponse("/admin", status_code=303)
    issue_session_cookie(response, user)
    clear_oauth_state(response)
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse("/admin/login", status_code=303)
    clear_session_cookie(response)
    return response
