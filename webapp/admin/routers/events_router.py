"""Rubrique admin « Événements » : configure les événements non-combat
(coffre, petite fille, forge sacrée) — activation, cadence, image, params.

Écrit `events.json` via json_writer (git-push + invalidation cache). ⚠️ Le bot
doit être redémarré pour appliquer une nouvelle cadence (orchestrateur lu au
boot). Seul le type `chest` est fonctionnel côté bot (Lot 1) ; les autres se
configurent déjà mais sont inactifs tant que leur lot n'est pas livré.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.infrastructure.events import event_config_loader as cfg
from app.shared.paths import EVENTS_ASSETS_DIR
from webapp.admin import git_sync, json_writer, uploads
from webapp.admin._shared import get_templates, parse_int
from webapp.admin.auth import AdminUser, require_admin

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/events", tags=["admin-events"])

_TYPE_LABELS = {
    "chest": "Coffre au trésor",
    "little_girl": "La petite fille",
    "sacred_forge": "La forge sacrée",
}
_IMPLEMENTED = {"chest"}


def _summary(event_type: str, config: dict) -> str:
    cad = config.get("cadence", {}) or {}
    base = f"{cad.get('times', 1)}× / {cad.get('per_days', 1)}j"
    if event_type == "chest":
        return f"{base} · {len(config.get('loot', []))} lignes de loot"
    if event_type == "little_girl":
        return f"{base} · piège {config.get('trap_probability', 50)}%"
    if event_type == "sacred_forge":
        return f"{base} · niv max {config.get('max_level', 10)}"
    return base


@router.get("", response_class=HTMLResponse)
async def events_list(request: Request, user: AdminUser = Depends(require_admin)):
    cfg.clear_cache()
    rows = []
    for t in cfg.EVENT_TYPES:
        c = cfg.get_config(t)
        rows.append(
            {
                "type": t,
                "label": _TYPE_LABELS.get(t, t),
                "enabled": bool(c.get("enabled")),
                "implemented": t in _IMPLEMENTED,
                "summary": _summary(t, c),
                "image": c.get("image", ""),
            }
        )
    return get_templates().TemplateResponse(
        request, "admin/events/list.html", context={"user": user, "rows": rows}
    )


@router.get("/{event_type}/edit", response_class=HTMLResponse)
async def events_edit_form(
    event_type: str, request: Request, user: AdminUser = Depends(require_admin)
):
    if event_type not in cfg.EVENT_TYPES:
        return RedirectResponse("/admin/events", status_code=303)
    cfg.clear_cache()
    config = cfg.get_config(event_type)
    return get_templates().TemplateResponse(
        request,
        "admin/events/form.html",
        context={
            "user": user,
            "event_type": event_type,
            "label": _TYPE_LABELS.get(event_type, event_type),
            "implemented": event_type in _IMPLEMENTED,
            "config": config,
        },
    )


def _parse_loot(form) -> list[dict]:
    kinds = form.getlist("loot_kind")
    codes = form.getlist("loot_item_code")
    qtys = form.getlist("loot_quantity")
    golds = form.getlist("loot_gold")
    weights = form.getlist("loot_weight")
    out: list[dict] = []
    for i in range(len(kinds)):
        kind = (kinds[i] or "").strip().lower()
        weight = parse_int(weights[i] if i < len(weights) else "0", 0)
        if kind not in ("item", "gold", "nothing") or weight <= 0:
            continue
        entry = {"kind": kind, "weight": weight}
        if kind == "item":
            code = (codes[i] if i < len(codes) else "").strip()
            if not code:
                continue
            entry["item_code"] = code
            entry["quantity"] = max(1, parse_int(qtys[i] if i < len(qtys) else "1", 1))
        elif kind == "gold":
            entry["gold_amount"] = max(1, parse_int(golds[i] if i < len(golds) else "0", 0))
        out.append(entry)
    return out


@router.post("/{event_type}")
async def events_update(
    event_type: str, request: Request, user: AdminUser = Depends(require_admin)
):
    if event_type not in cfg.EVENT_TYPES:
        return RedirectResponse("/admin/events", status_code=303)
    form = await request.form()

    data = json_writer.load_json("events.json", {}) or {}
    current = dict(cfg.get_config(event_type))
    current.update(data.get(event_type, {}) or {})

    current["enabled"] = form.get("enabled") in ("on", "true", "1", "yes")
    current["cadence"] = {
        "times": max(0, parse_int(form.get("cadence_times"), 1)),
        "per_days": max(1, parse_int(form.get("cadence_per_days"), 1)),
    }

    # Image (optionnelle)
    push_paths = ["app/infrastructure/content/events.json"]
    upload = form.get("image_file")
    if upload is not None and getattr(upload, "filename", ""):
        try:
            content = await upload.read()
            if content:
                saved = uploads.save_asset_bytes(
                    content, upload.filename, EVENTS_ASSETS_DIR, preferred_stem=event_type
                )
                current["image"] = saved
                push_paths.append(f"assets/events/{saved}")
        except uploads.UploadError as exc:
            _logger.warning("upload image event %s échoué: %s", event_type, exc)

    # Params spécifiques
    if event_type == "chest":
        current["loot"] = _parse_loot(form)
        current["level_scaling_pct"] = max(0, parse_int(form.get("level_scaling_pct"), 0))
    elif event_type == "little_girl":
        current["trap_probability"] = max(0, min(100, parse_int(form.get("trap_probability"), 50)))
        current["gold_loss_per_level"] = max(0, parse_int(form.get("gold_loss_per_level"), 10))
        current["title_chance"] = max(0, min(100, parse_int(form.get("title_chance"), 10)))
        current["resolve_after_minutes"] = max(1, parse_int(form.get("resolve_after_minutes"), 5))
    elif event_type == "sacred_forge":
        current["max_level"] = max(1, parse_int(form.get("max_level"), 10))
        current["window_minutes"] = max(1, parse_int(form.get("window_minutes"), 5))

    data[event_type] = current
    json_writer.atomic_write_json("events.json", data)
    git_sync.push_content(push_paths, f"admin: event {event_type} mis à jour")
    cfg.clear_cache()
    _logger.info("Admin %s a mis à jour l'event %s", user.discord_id, event_type)
    return RedirectResponse("/admin/events", status_code=303)
