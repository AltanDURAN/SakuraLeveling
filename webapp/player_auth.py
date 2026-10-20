"""Connexion Discord des JOUEURS (page publique de l'arbre).

Réutilise l'application OAuth et l'URL de callback de l'admin
(`/admin/auth/callback`) : pas de nouvelle URL de redirection à déclarer côté
Discord. Ce qui distingue les deux parcours, c'est un cookie « destination »
posé ici : quand le callback le trouve, il ouvre une session JOUEUR et renvoie
sur l'arbre, sans jamais toucher à la session admin.

La session joueur est un cookie DISTINCT (autre nom, autre sel de signature) :
se connecter comme joueur ne donne aucun droit sur /admin, même à un admin.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeSerializer

from app.infrastructure.config.settings import settings
from webapp.admin.auth import build_authorize_url, make_state, store_oauth_state

_SESSION_COOKIE = "sakura_player_session"
_NEXT_COOKIE = "sakura_oauth_next"
_SESSION_DAYS = 30

#: Seules les pages d'arbre sont des destinations valides (pas de redirection
#: ouverte vers un site tiers).
_SAFE_NEXT = re.compile(r"^/skill/\d{1,25}$")


@dataclass(frozen=True)
class PlayerUser:
    discord_id: int
    display_name: str


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(settings.admin_session_secret, salt="sakura-player-v1")


def safe_next(value: str | None) -> str | None:
    return value if value and _SAFE_NEXT.match(value) else None


def current_player(request: Request) -> PlayerUser | None:
    token = request.cookies.get(_SESSION_COOKIE)
    if not token:
        return None
    try:
        payload = _serializer().loads(token)
        return PlayerUser(int(payload["discord_id"]), str(payload.get("display_name", "")))
    except (BadSignature, KeyError, TypeError, ValueError):
        return None


def issue_player_session(response: Response, discord_id: int, display_name: str) -> None:
    token = _serializer().dumps({"discord_id": discord_id, "display_name": display_name})
    response.set_cookie(
        _SESSION_COOKIE, token, httponly=True, samesite="lax",
        secure=settings.admin_cookie_secure, max_age=60 * 60 * 24 * _SESSION_DAYS,
    )


def pop_player_next(request: Request, response: Response) -> str | None:
    """Destination du parcours joueur (None = parcours admin classique).

    Le cookie ne garde que l'ID Discord de l'arbre : une valeur avec des « / »
    serait mise entre guillemets par le navigateur."""
    raw = request.cookies.get(_NEXT_COOKIE, "").strip('"')
    response.delete_cookie(_NEXT_COOKIE)
    return safe_next(f"/skill/{raw}") if raw.isdigit() else None


router = APIRouter(tags=["player-auth"])


@router.get("/skill/login")
async def player_login(next: str | None = None):
    target = safe_next(next)
    if target is None:
        return RedirectResponse("/", status_code=303)
    state = make_state()
    response = RedirectResponse(build_authorize_url(state), status_code=303)
    store_oauth_state(response, state)
    response.set_cookie(
        _NEXT_COOKIE, target.rsplit("/", 1)[-1], httponly=True, samesite="lax",
        secure=settings.admin_cookie_secure, max_age=600,
    )
    return response


@router.get("/skill/logout")
async def player_logout(next: str | None = None):
    response = RedirectResponse(safe_next(next) or "/", status_code=303)
    response.delete_cookie(_SESSION_COOKIE)
    return response
