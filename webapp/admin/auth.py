"""Authentification Discord OAuth2 pour la webapp admin.

Flow :
1. L'utilisateur clique "Se connecter avec Discord" → redirigé vers
   Discord (oauth2/authorize).
2. Discord callback sur /admin/auth/callback?code=... avec un code court.
3. On échange le code contre un access_token (POST /oauth2/token).
4. On récupère l'identité du user via GET /users/@me.
5. On vérifie que son Discord ID ∈ ADMIN_DISCORD_IDS. Sinon refus.
6. On signe un cookie de session contenant le user_id + display_name.

Le cookie est signé via `itsdangerous` (HMAC + clé `admin_session_secret`).
Pas de session DB → stateless, simple, suffisant pour une admin app
mono-utilisateur ou très petit groupe.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException, Request, Response, status
from itsdangerous import BadSignature, URLSafeSerializer

from app.infrastructure.config.settings import settings


_logger = logging.getLogger(__name__)

DISCORD_API_BASE = "https://discord.com/api"
DISCORD_AUTHORIZE_URL = f"{DISCORD_API_BASE}/oauth2/authorize"
DISCORD_TOKEN_URL = f"{DISCORD_API_BASE}/oauth2/token"
DISCORD_USER_URL = f"{DISCORD_API_BASE}/users/@me"

# OAuth scopes : `identify` suffit (on a juste besoin de l'ID Discord +
# username pour valider l'admin). `email` non requis.
OAUTH_SCOPES = "identify"

_SESSION_COOKIE_NAME = "sakura_admin_session"
_STATE_COOKIE_NAME = "sakura_oauth_state"


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(
        settings.admin_session_secret, salt="sakura-admin-v1",
    )


@dataclass
class AdminUser:
    discord_id: int
    username: str
    display_name: str

    @property
    def is_admin(self) -> bool:
        return self.discord_id in settings.admin_ids


def build_authorize_url(state: str) -> str:
    from urllib.parse import urlencode

    params = {
        "client_id": settings.discord_client_id,
        "redirect_uri": settings.oauth_redirect_uri,
        "response_type": "code",
        "scope": OAUTH_SCOPES,
        "state": state,
        "prompt": "consent",
    }
    return f"{DISCORD_AUTHORIZE_URL}?{urlencode(params)}"


def make_state() -> str:
    """Token aléatoire stocké côté client (cookie) + dans l'URL OAuth.
    On vérifie que les deux matchent au callback pour prévenir CSRF."""
    return secrets.token_urlsafe(24)


async def exchange_code_for_token(code: str) -> str:
    """Échange le code reçu en callback contre un access_token Discord."""
    data = {
        "client_id": settings.discord_client_id,
        "client_secret": settings.discord_client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.oauth_redirect_uri,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            DISCORD_TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if resp.status_code != 200:
        _logger.warning("Discord OAuth token error: %s", resp.text)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="OAuth échec : impossible d'obtenir un token Discord.",
        )
    return resp.json()["access_token"]


async def fetch_user_identity(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            DISCORD_USER_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code != 200:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Impossible de récupérer votre identité Discord.",
        )
    return resp.json()


def issue_session_cookie(response: Response, user: AdminUser) -> None:
    payload = {
        "discord_id": user.discord_id,
        "username": user.username,
        "display_name": user.display_name,
    }
    token = _serializer().dumps(payload)
    response.set_cookie(
        _SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        # `secure=True` quand on aura HTTPS. Pour http://IP:port on laisse False.
        secure=False,
        max_age=60 * 60 * 24 * 7,  # 7 jours
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(_SESSION_COOKIE_NAME)


def store_oauth_state(response: Response, state: str) -> None:
    response.set_cookie(
        _STATE_COOKIE_NAME,
        state,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=600,  # 10 min suffisent
    )


def read_oauth_state(request: Request) -> str | None:
    return request.cookies.get(_STATE_COOKIE_NAME)


def clear_oauth_state(response: Response) -> None:
    response.delete_cookie(_STATE_COOKIE_NAME)


def current_user(request: Request) -> AdminUser | None:
    token = request.cookies.get(_SESSION_COOKIE_NAME)
    if not token:
        return None
    try:
        payload = _serializer().loads(token)
    except BadSignature:
        return None
    return AdminUser(
        discord_id=int(payload["discord_id"]),
        username=str(payload.get("username", "")),
        display_name=str(payload.get("display_name", "")),
    )


def require_admin(request: Request) -> AdminUser:
    """Dependency FastAPI : injecte l'utilisateur courant, redirige si
    pas connecté, 403 si connecté mais pas admin."""
    user = current_user(request)
    if user is None:
        raise HTTPException(
            status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/admin/login"},
        )
    if not user.is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Votre compte Discord n'a pas les droits administrateur.",
        )
    return user
