"""Helpers partagés entre les routers admin.

Avant : `get_templates()`, `_parse_int()` et `_parse_optional_int()` étaient
recopiés à l'identique dans 8 routers. Toute évolution = 8 endroits à toucher.
Cf. audit Phase 1 finding F11 / dup webapp_routers.

`get_templates` reste une fonction (import paresseux) pour éviter le cycle
`webapp.admin.routers.* → webapp.main → admin routers` au boot.
"""

from __future__ import annotations

from fastapi.templating import Jinja2Templates


def get_templates() -> Jinja2Templates:
    # Import paresseux : casse le cycle d'import au boot de FastAPI.
    from webapp.main import templates
    return templates


def parse_optional_int(raw: str | None) -> int | None:
    """Convertit une saisie form en int, None si vide/invalide."""
    if raw is None:
        return None
    raw = str(raw).strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def parse_int(raw: str | None, default: int = 0) -> int:
    """Convertit une saisie form en int avec fallback."""
    v = parse_optional_int(raw)
    return v if v is not None else default
