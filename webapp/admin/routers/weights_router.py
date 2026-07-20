"""Routes admin : POIDS de spawn élémentaire des monstres.

Chaque monstre sauvage spawne sous un élément tiré aléatoirement PONDÉRÉ.
Cet éditeur écrit `element_spawn_weights.json` (source de vérité). Le loader du
bot est invalidé par mtime → les changements prennent effet au prochain spawn
sans redémarrage.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from app.infrastructure.elements import element_spawn_weight_loader
from app.shared.enums import ALL_ELEMENTS, ELEMENT_EMOJIS, ELEMENT_LABELS
from webapp.admin import json_writer
from webapp.admin._shared import get_templates
from webapp.admin.auth import AdminUser, require_admin

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/weights", tags=["admin-weights"])

_FILENAME = "element_spawn_weights.json"
_COMMENT = (
    "Poids de spawn par élément des monstres sauvages. Plus le poids est grand, "
    "plus le monstre a de chances de spawner sous cet élément. Un poids de 0 "
    "désactive l'élément. Édité via l'admin web."
)


def _read_raw() -> dict[str, int]:
    """Poids bruts stockés (0 si absent), un par élément."""
    path = element_spawn_weight_loader.CONTENT_PATH
    raw: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            raw = data.get("weights", {}) if isinstance(data, dict) else {}
        except (ValueError, OSError):
            raw = {}
    out: dict[str, int] = {}
    for e in ALL_ELEMENTS:
        try:
            out[e.value] = max(0, int(raw.get(e.value, 0) or 0))
        except (TypeError, ValueError):
            out[e.value] = 0
    return out


def _elements_ctx() -> tuple[list[dict], int]:
    weights = _read_raw()
    total = sum(weights.values()) or 1
    elements = [
        {
            "code": e.value,
            "label": ELEMENT_LABELS[e.value],
            "emoji": ELEMENT_EMOJIS[e.value],
            "weight": weights[e.value],
            "pct": round(100 * weights[e.value] / total),
        }
        for e in ALL_ELEMENTS
    ]
    return elements, total


@router.get("")
async def weights_form(request: Request, user: AdminUser = Depends(require_admin)):
    elements, total = _elements_ctx()
    return get_templates().TemplateResponse(
        request, "admin/weights/form.html",
        context={"user": user, "elements": elements, "total": total, "saved": False},
    )


@router.post("")
async def weights_save(request: Request, user: AdminUser = Depends(require_admin)):
    form = await request.form()
    weights: dict[str, int] = {}
    for e in ALL_ELEMENTS:
        try:
            weights[e.value] = max(0, int(str(form.get(f"weight_{e.value}", "0")).strip() or 0))
        except (TypeError, ValueError):
            weights[e.value] = 0
    # atomic_write_json invalide les caches webapp + push git automatiquement.
    json_writer.atomic_write_json(_FILENAME, {"_comment": _COMMENT, "weights": weights})
    element_spawn_weight_loader.reload_cache()
    _logger.info("Admin %s a modifié les poids de spawn élémentaire : %s",
                 user.discord_id, weights)
    return RedirectResponse("/admin/weights?saved=1", status_code=303)
