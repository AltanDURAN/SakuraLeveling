"""Protection CSRF par vérification d'origine (Origin/Referer).

Pour toute méthode non sûre (POST/PUT/PATCH/DELETE) sur une route `/admin`,
on exige que l'en-tête `Origin` (ou à défaut `Referer`) provienne d'une origine
autorisée — dérivée de la config (`webapp_base_url`, `oauth_redirect_uri`) +
localhost pour le dev. Une requête forgée depuis un site tiers porte une autre
origine → rejetée (403).

Robuste derrière un reverse-proxy (on ne compare PAS au Host forwardé, qui peut
être réécrit par nginx, mais à une allowlist issue de la config).
Combiné à `samesite=lax` sur les cookies, ferme le vecteur CSRF résiduel sans
toucher aux templates ni aux routes.
"""

from __future__ import annotations

from urllib.parse import urlparse

from app.infrastructure.config.settings import settings

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _allowed_origins() -> set[str]:
    """Netlocs autorisés (host[:port]) issus de la config + dev local."""
    origins: set[str] = set()
    for url in (settings.webapp_base_url, settings.oauth_redirect_uri):
        if url:
            netloc = urlparse(url).netloc
            if netloc:
                origins.add(netloc)
    # Dev local courant.
    origins.update({"localhost:8001", "127.0.0.1:8001", "localhost:8000"})
    return origins


def request_origin_is_allowed(method: str, path: str, origin: str | None, referer: str | None) -> bool:
    """Cœur testable de la vérif (sans dépendre de l'objet Request)."""
    if method.upper() not in _UNSAFE_METHODS:
        return True
    if not path.startswith("/admin"):
        return True

    allowed = _allowed_origins()
    candidate = origin or referer
    if not candidate:
        # Une requête mutante sans Origin ni Referer sur /admin est suspecte.
        return False
    return urlparse(candidate).netloc in allowed


async def csrf_origin_middleware(request, call_next):
    """Middleware Starlette : rejette les requêtes mutantes d'origine étrangère."""
    if not request_origin_is_allowed(
        request.method,
        request.url.path,
        request.headers.get("origin"),
        request.headers.get("referer"),
    ):
        from starlette.responses import PlainTextResponse
        return PlainTextResponse(
            "CSRF : origine non autorisée pour cette action.", status_code=403,
        )
    return await call_next(request)
