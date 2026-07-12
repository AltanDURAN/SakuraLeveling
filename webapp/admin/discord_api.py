"""Client Discord REST (bot token) pour l'admin web : gestion des rôles.

Utilise le token du bot (`settings.discord_token`) pour lire les membres/rôles
du serveur et les administrer (ajouter/retirer un rôle, CRUD de rôles).

Prérequis côté Discord :
- Intent privilégié **SERVER MEMBERS** activé (pour lister les membres).
- Le bot doit avoir la permission **Gérer les rôles** ET être plus haut dans
  la hiérarchie que les rôles qu'il manipule (sinon 403).

Toutes les fonctions renvoient (ok: bool, data|error_message).
"""

from __future__ import annotations

import httpx

from app.infrastructure.config.settings import settings

_API = "https://discord.com/api/v10"


def _headers() -> dict:
    return {
        "Authorization": f"Bot {settings.discord_token}",
        "Content-Type": "application/json",
    }


def _reason(reason: str | None) -> dict:
    return {"X-Audit-Log-Reason": reason[:400]} if reason else {}


async def _request(method: str, path: str, **kwargs) -> tuple[bool, object]:
    try:
        async with httpx.AsyncClient(base_url=_API, headers=_headers(), timeout=20) as c:
            resp = await c.request(method, path, **kwargs)
    except httpx.HTTPError as exc:
        return False, f"Erreur réseau Discord : {exc}"

    if resp.status_code in (200, 201, 204):
        if resp.status_code == 204 or not resp.content:
            return True, None
        return True, resp.json()

    # Messages d'erreur lisibles pour les cas fréquents.
    if resp.status_code == 403:
        return False, ("403 — le bot n'a pas la permission (Gérer les rôles) "
                       "ou le rôle est au-dessus du sien dans la hiérarchie.")
    if resp.status_code == 401:
        return False, "401 — token du bot invalide."
    if resp.status_code == 429:
        return False, "429 — rate limit Discord, réessaie dans un instant."
    try:
        detail = resp.json().get("message", resp.text)
    except Exception:  # noqa: BLE001
        detail = resp.text
    return False, f"{resp.status_code} — {detail}"


# ---------- lecture ----------

async def list_roles(guild_id: int) -> tuple[bool, object]:
    """Rôles du serveur, triés par position décroissante (haut → bas)."""
    ok, data = await _request("GET", f"/guilds/{guild_id}/roles")
    if not ok:
        return ok, data
    roles = sorted(data, key=lambda r: r.get("position", 0), reverse=True)
    return True, roles


async def list_members(guild_id: int, limit_total: int = 1000) -> tuple[bool, object]:
    """Tous les membres (pagination `after`). Nécessite l'intent SERVER MEMBERS."""
    members: list[dict] = []
    after = "0"
    while len(members) < limit_total:
        ok, data = await _request(
            "GET", f"/guilds/{guild_id}/members",
            params={"limit": 1000, "after": after},
        )
        if not ok:
            return ok, data
        if not data:
            break
        members.extend(data)
        after = data[-1]["user"]["id"]
        if len(data) < 1000:
            break
    return True, members


# ---------- rôles d'un membre ----------

async def add_member_role(guild_id: int, user_id: int, role_id: int, reason=None):
    return await _request(
        "PUT", f"/guilds/{guild_id}/members/{user_id}/roles/{role_id}",
        headers={**_headers(), **_reason(reason)},
    )


async def remove_member_role(guild_id: int, user_id: int, role_id: int, reason=None):
    return await _request(
        "DELETE", f"/guilds/{guild_id}/members/{user_id}/roles/{role_id}",
        headers={**_headers(), **_reason(reason)},
    )


# ---------- CRUD de rôles ----------

async def create_role(guild_id: int, name: str, color: int = 0, hoist=False, mentionable=False, reason=None):
    return await _request(
        "POST", f"/guilds/{guild_id}/roles",
        headers={**_headers(), **_reason(reason)},
        json={"name": name, "color": color, "hoist": hoist, "mentionable": mentionable},
    )


async def edit_role(guild_id: int, role_id: int, name: str, color: int = 0, hoist=False, mentionable=False, reason=None):
    return await _request(
        "PATCH", f"/guilds/{guild_id}/roles/{role_id}",
        headers={**_headers(), **_reason(reason)},
        json={"name": name, "color": color, "hoist": hoist, "mentionable": mentionable},
    )


async def delete_role(guild_id: int, role_id: int, reason=None):
    return await _request(
        "DELETE", f"/guilds/{guild_id}/roles/{role_id}",
        headers={**_headers(), **_reason(reason)},
    )
