"""Rubrique admin « Événements » : les événements non-combat (coffre, petite
fille, forge sacrée), une seule page visuelle (11/11/2026, demande de
l'auteur : « améliore la page »).

Pour chaque événement :
    • l'APERÇU du message Discord, construit par le code du bot
      (`app/bot/embeds/event_embeds.py`) avec les réglages en cours d'édition,
      à chaque étape (apparition, coffre ouvert / volatilisé, vraie petite
      fille / piège, forge éteinte) ;
    • les réglages, avec les chiffres utiles calculés en direct (chances du
      butin, gain au niveau choisi, conséquences des choix…) ;
    • ce qui s'est passé en vrai (table `active_events`) et le bouton pour le
      faire apparaître tout de suite (file `admin_commands`).

Le bot relit `events.json` à chaque passage de sa boucle : aucun redémarrage.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.domain.services.chest_loot_service import ChestLootResult, ChestLootService
from app.domain.services.gear_service import FORGE_BONUS_PER_LEVEL, FORGE_MAX_LEVEL
from app.domain.services.little_girl_service import (
    CHOICE_HELP, CHOICE_IGNORE, LittleGirlConfig, LittleGirlService,
)
from app.infrastructure.config.settings import settings
from app.infrastructure.db.session import get_db_session
from app.infrastructure.events import event_config_loader as cfg
from app.shared.enums import EQUIPABLE_CATEGORIES, ITEM_CATEGORY_EMOJIS, ItemCategory
from app.shared.paths import EVENTS_ASSETS_DIR, ITEMS_ASSETS_DIR
from webapp.admin import git_sync, json_writer, uploads
from webapp.admin._shared import get_templates
from webapp.admin.auth import AdminUser, require_admin

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/events", tags=["admin-events"])

_TYPE_LABELS = {
    "chest": "Coffre au trésor",
    "little_girl": "La petite fille",
    "sacred_forge": "La forge sacrée",
}
_TYPE_EMOJIS = {"chest": "🎁", "little_girl": "👧", "sacred_forge": "🔨"}
_TYPE_PITCH = {
    "chest": "Le premier qui l'ouvre rafle le butin.",
    "little_girl": "Aider ou ignorer ? Vraie enfant perdue… ou monstre déguisé.",
    "sacred_forge": "Chacun renforce une de ses pièces, une fois.",
}
#: Étapes de chaque message, montrées en aperçu.
_STATES = {
    "chest": [("spawn", "À l'apparition"), ("opened", "Ouvert par un joueur"), ("expired", "Volatilisé")],
    "little_girl": [("spawn", "À l'apparition"), ("real", "Vraie petite fille"), ("trap", "C'était un piège")],
    "sacred_forge": [("spawn", "À l'apparition"), ("closed", "Forge éteinte")],
}
_SPAWN_LOOP_MINUTES = 10          # miroir d'event_cog
_GLOBAL_KEY = "__global__"
_DEMO = [("Altan", CHOICE_HELP), ("Kaori", CHOICE_IGNORE), ("Rin", CHOICE_HELP)]


# ------------------------------------------------------------ réglages ----
def _num(raw, default, lo, hi, cast=int):
    try:
        value = cast(raw)
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def clean(event_type: str, raw: dict, base: dict, item_codes: set[str] | None = None) -> tuple[dict, list[str]]:
    """Les réglages tels qu'on les écrit : bornés (une valeur hors bornes est
    ramenée dans les bornes) ; seules les erreurs de structure sont refusées."""
    out = dict(base)
    errors: list[str] = []
    out["enabled"] = raw.get("enabled") in (True, "on", "true", "1", "yes", 1)
    cad = raw.get("cadence") or {}
    out["cadence"] = {"times": _num(cad.get("times"), 1, 0, 24), "per_days": _num(cad.get("per_days"), 1, 1, 365)}
    if raw.get("channel") in cfg.CHANNELS:
        out["channel"] = raw["channel"]
    if event_type == "chest":
        loot = []
        for row in raw.get("loot") or []:
            kind = str(row.get("kind", "")).strip().lower()
            weight = _num(row.get("weight"), 0, 0, 100_000)
            if kind not in ("item", "gold", "nothing") or weight <= 0:
                continue
            entry = {"kind": kind, "weight": weight}
            if kind == "item":
                code = str(row.get("item_code") or "").strip()
                if not code:
                    continue
                if item_codes is not None and code not in item_codes:
                    errors.append(f"Objet inconnu dans le butin : « {code} ».")
                    continue
                entry["item_code"] = code
                entry["quantity"] = _num(row.get("quantity"), 1, 1, 10_000)
            elif kind == "gold":
                entry["gold_amount"] = _num(row.get("gold_amount"), 1, 1, 10_000_000)
            loot.append(entry)
        if not loot:
            errors.append("Le coffre a besoin d'au moins une récompense.")
        out["loot"] = loot
        out["level_scaling_pct"] = _num(raw.get("level_scaling_pct"), 0, 0, 100)
        out["expire_after_minutes"] = _num(raw.get("expire_after_minutes"), cfg.CHEST_LIFETIME_MINUTES, 5, 7 * 24 * 60)
    elif event_type == "little_girl":
        out["trap_probability"] = _num(raw.get("trap_probability"), 50, 0, 100)
        out["gold_loss_per_level"] = _num(raw.get("gold_loss_per_level"), 10, 0, 100_000)
        out["title_chance"] = _num(raw.get("title_chance"), 10, 0, 100)
        out["resolve_after_minutes"] = _num(raw.get("resolve_after_minutes"), 5, 1, 120)
        out["buff_multiplier"] = round(_num(raw.get("buff_multiplier", base.get("buff_multiplier", 1.1)), 1.1, 1.0, 3.0, float), 2)
        out["buff_duration_hours"] = _num(raw.get("buff_duration_hours", base.get("buff_duration_hours", 3)), 3, 1, 48)
        out["debuff_multiplier"] = round(_num(raw.get("debuff_multiplier", base.get("debuff_multiplier", 0.5)), 0.5, 0.1, 1.0, float), 2)
        out["debuff_duration_hours"] = _num(raw.get("debuff_duration_hours", base.get("debuff_duration_hours", 3)), 3, 1, 48)
    elif event_type == "sacred_forge":
        out["max_level"] = _num(raw.get("max_level"), FORGE_MAX_LEVEL, 1, FORGE_MAX_LEVEL)
        out["window_minutes"] = _num(raw.get("window_minutes"), 5, 1, 120)
    return out, errors


def _write(event_type: str, config: dict, extra_paths: list[str] | None = None) -> None:
    data = json_writer.load_json("events.json", {}) or {}
    data[event_type] = config
    json_writer.atomic_write_json("events.json", data)
    git_sync.push_content(["app/infrastructure/content/events.json", *(extra_paths or [])],
                          f"admin: event {event_type} mis à jour")
    cfg.clear_cache()


def _current(event_type: str) -> dict:
    cfg.clear_cache()
    data = json_writer.load_json("events.json", {}) or {}
    current = dict(cfg.get_config(event_type))
    current.update(data.get(event_type, {}) or {})
    return current


# ------------------------------------------------------------- données ----
def _items(session) -> list[dict]:
    """Ce qu'un coffre peut donner : tout ce qui va dans l'inventaire (pas une
    pièce d'équipement — un exemplaire —, ni une carte)."""
    from app.infrastructure.db.repositories.item_repository import ItemRepository

    out = []
    for item in ItemRepository(session).list_all():
        if item.category in EQUIPABLE_CATEGORIES or item.category == ItemCategory.CARD.value:
            continue
        image = ITEMS_ASSETS_DIR / f"{item.code}.png"
        out.append({"code": item.code, "name": item.name, "category": item.category,
                    "emoji": ITEM_CATEGORY_EMOJIS.get(item.category, "📦"),
                    "image": f"/assets/items/{item.code}.png?v={int(image.stat().st_mtime)}" if image.is_file() else ""})
    return sorted(out, key=lambda i: i["name"].lower())


def _iso(moment: datetime | None) -> str:
    if moment is None:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _link(channel_id: int | None, message_id: int | None) -> str:
    guild = int(getattr(settings, "discord_guild_id", 0) or 0)
    return f"https://discord.com/channels/{guild}/{channel_id}/{message_id}" if guild and channel_id and message_id else ""


def history(session, now: datetime | None = None) -> dict[str, dict]:
    """Ce qui s'est passé en vrai, par événement : apparitions, en cours,
    coffres ouverts / perdus, choix et issues de la petite fille, forges."""
    from app.infrastructure.db.models.event_model import (
        ActiveEventModel, EventParticipationModel, EventSchedulerStateModel,
    )
    from app.infrastructure.db.models.player_model import PlayerModel

    now = (now or datetime.now(UTC)).replace(tzinfo=None)
    month_ago = now - timedelta(days=30)
    events = session.query(ActiveEventModel).order_by(ActiveEventModel.created_at).all()
    parts = session.query(EventParticipationModel.event_id, EventParticipationModel.choice).all()
    by_event: dict[int, list[str]] = {}
    for event_id, choice in parts:
        by_event.setdefault(event_id, []).append(choice or "")
    last_spawn = {row.event_type: row.last_spawn_at for row in session.query(EventSchedulerStateModel).all()}
    winner_ids = {e.winner_player_id for e in events if e.winner_player_id}
    names = {pid: display or username for pid, display, username in
             session.query(PlayerModel.id, PlayerModel.display_name, PlayerModel.username)
             .filter(PlayerModel.id.in_(winner_ids)).all()} if winner_ids else {}

    out: dict[str, dict] = {}
    for event_type in cfg.EVENT_TYPES:
        mine = [e for e in events if e.event_type == event_type]
        recent = [e for e in mine if e.created_at and e.created_at.replace(tzinfo=None) >= month_ago]
        active = next((e for e in reversed(mine) if e.status == "active"), None)
        stats: dict = {
            "total": len(mine), "month": len(recent),
            "last_at": _iso(mine[-1].created_at) if mine else "",
            "last_spawn_at": _iso(last_spawn.get(event_type)),
            "active": {"since": _iso(active.created_at), "link": _link(active.channel_id, active.message_id),
                       "until": _iso(active.expires_at)} if active else None,
        }
        if event_type == "chest":
            opened = [e for e in recent if e.winner_player_id]
            stats.update(opened=len(opened), expired=sum(1 for e in recent if e.status == "expired"),
                         winners=[{"name": names.get(pid, "?"), "count": n}
                                  for pid, n in Counter(e.winner_player_id for e in opened).most_common(3)])
        elif event_type == "little_girl":
            choices = [c for e in recent for c in by_event.get(e.id, [])]
            outcomes = [json.loads(e.payload_json or "{}").get("trap") for e in recent if e.status == "resolved"]
            stats.update(help=choices.count(CHOICE_HELP), ignore=choices.count(CHOICE_IGNORE),
                         alone=sum(1 for e in recent if e.status == "resolved" and not by_event.get(e.id)),
                         trap=outcomes.count(True), real=outcomes.count(False))
        elif event_type == "sacred_forge":
            uses = [len(by_event.get(e.id, [])) for e in recent]
            stats.update(uses=sum(uses), empty=sum(1 for n in uses if n == 0))
        out[event_type] = stats
    stats_global = last_spawn.get(_GLOBAL_KEY)
    out["_global"] = {"last_spawn_at": _iso(stats_global)}
    return out


def _page_data(session) -> dict:
    cfg.clear_cache()
    events = []
    for t in cfg.EVENT_TYPES:
        config = _current(t)
        image = config.get("image", "") or ""
        path = EVENTS_ASSETS_DIR / image if image else None
        events.append({
            "type": t, "label": _TYPE_LABELS.get(t, t), "emoji": _TYPE_EMOJIS.get(t, "🎲"),
            "pitch": _TYPE_PITCH.get(t, ""), "states": [{"code": c, "label": lbl} for c, lbl in _STATES.get(t, [])],
            "config": config,
            "image_url": f"/assets/events/{image}?v={int(path.stat().st_mtime)}" if path and path.is_file() else "",
        })
    return {
        "events": events,
        "channels": cfg.CHANNELS,
        # En liste : le filtre `tojson` de Jinja trie les clés d'un dict.
        "channel_list": [{"code": code, "name": name} for code, name in cfg.CHANNELS.items()],
        "items": _items(session),
        "history": history(session),
        "loop_minutes": _SPAWN_LOOP_MINUTES,
        "forge": {"bonus_pct": round(FORGE_BONUS_PER_LEVEL * 100, 2), "max": FORGE_MAX_LEVEL},
        "max_mb": uploads.MAX_UPLOAD_BYTES // (1024 * 1024),
    }


# --------------------------------------------------------------- pages ----
@router.get("", response_class=HTMLResponse)
async def events_page(request: Request, user: AdminUser = Depends(require_admin)):
    with get_db_session() as session:
        data = _page_data(session)
    return get_templates().TemplateResponse(
        request, "admin/events/index.html", context={"user": user, "data": data})


@router.get("/{event_type}/edit")
async def events_edit_form(event_type: str, user: AdminUser = Depends(require_admin)):
    """Ancienne fiche : tout est désormais sur la page Événements."""
    anchor = f"#{event_type}" if event_type in cfg.EVENT_TYPES else ""
    return RedirectResponse(f"/admin/events{anchor}", status_code=303)


async def _json(request: Request) -> dict:
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        return {}
    return body if isinstance(body, dict) else {}


@router.post("/save")
async def events_save(request: Request, user: AdminUser = Depends(require_admin)):
    body = await _json(request)
    event_type = str(body.get("type") or "")
    if event_type not in cfg.EVENT_TYPES:
        return JSONResponse({"error": "Événement inconnu."}, status_code=400)
    with get_db_session() as session:
        codes = {i["code"] for i in _items(session)}
    config, errors = clean(event_type, body.get("config") or {}, _current(event_type), codes)
    if errors:
        return JSONResponse({"error": " ".join(errors)}, status_code=400)
    await asyncio.to_thread(_write, event_type, config)
    _logger.info("Admin %s a mis à jour l'event %s", user.discord_id, event_type)
    return {"ok": True, "config": config}


@router.post("/preview")
async def events_preview(request: Request, user: AdminUser = Depends(require_admin)):
    body = await _json(request)
    try:
        return JSONResponse(await asyncio.to_thread(preview, body))
    except (TypeError, ValueError, KeyError) as exc:
        return JSONResponse({"error": f"Aperçu impossible : {exc}"}, status_code=400)


def _item_names() -> dict[str, str]:
    with get_db_session() as session:
        return {i["code"]: i["name"] for i in _items(session)}


def preview(body: dict) -> dict:
    """Le message Discord tel que le bot l'écrirait, avec les réglages en
    cours d'édition (pas encore enregistrés)."""
    from app.bot.embeds import event_embeds as ee
    from app.shared.formatters import format_int

    event_type = str(body.get("type") or "")
    if event_type not in cfg.EVENT_TYPES:
        return {"error": "Événement inconnu."}
    config, _ = clean(event_type, body.get("config") or {}, _current(event_type))
    state = str(body.get("state") or "spawn")
    level = _num(body.get("level"), 20, 1, 100)
    buttons = []
    if event_type == "chest":
        if state == "opened":
            loot = ChestLootService().parse_entries(config.get("loot", []))
            row = _num(body.get("row"), 0, 0, max(0, len(loot) - 1)) if loot else 0
            entry = loot[row] if loot else None
            result = ChestLootResult(kind=entry.kind, item_code=entry.item_code, quantity=entry.quantity,
                                     gold_amount=entry.gold_amount) if entry else ChestLootResult(kind="nothing")
            result = ChestLootService().scale_for_level(result, level, float(config.get("level_scaling_pct", 0)))
            if result.kind == "gold":
                reward = f"{format_int(result.gold_amount)} or"
            elif result.kind == "item":
                reward = f"{result.quantity}× {_item_names().get(result.item_code, result.item_code)}"
            else:
                reward = "rien du tout… 😞 (le coffre était vide)"
            embed = ee.chest_opened_embed("@Altan", reward)
        elif state == "expired":
            embed = ee.chest_expired_embed()
        else:
            embed, buttons = ee.chest_spawn_embed(), ee.BUTTONS["chest"]
    elif event_type == "little_girl":
        if state in ("real", "trap"):
            girl = LittleGirlConfig(
                trap_probability=config["trap_probability"], gold_loss_per_level=config["gold_loss_per_level"],
                buff_multiplier=config["buff_multiplier"], buff_duration_hours=config["buff_duration_hours"],
                debuff_multiplier=config["debuff_multiplier"], debuff_duration_hours=config["debuff_duration_hours"],
                title_chance=config["title_chance"])
            service = LittleGirlService()
            import random
            rng = random.Random(7)
            lines = [f"@{name} · {ee.girl_outcome_tag(service.resolve(choice, state == 'trap', level, girl, False, rng))}"
                     for name, choice in _DEMO]
            embed = ee.girl_result_embed(state == "trap", lines)
        else:
            embed, buttons = ee.girl_spawn_embed(config["resolve_after_minutes"]), ee.BUTTONS["little_girl"]
    else:
        if state == "closed":
            embed = ee.forge_closed_embed(3)
        else:
            embed = ee.forge_spawn_embed(config["window_minutes"], config["max_level"])
            buttons = ee.BUTTONS["sacred_forge"]
    return {"embeds": [embed.to_dict()],
            "buttons": [{"emoji": e, "label": label, "style": style} for e, label, style in buttons],
            # À l'apparition l'image est DANS le message ; ensuite elle reste en pièce jointe.
            "image_in_embed": state == "spawn"}


@router.post("/{event_type}/image")
async def events_image(event_type: str, request: Request, user: AdminUser = Depends(require_admin)):
    if event_type not in cfg.EVENT_TYPES:
        return JSONResponse({"error": "Événement inconnu."}, status_code=404)
    form = await request.form()
    upload = form.get("image")
    if upload is None or not getattr(upload, "filename", ""):
        return JSONResponse({"error": "Aucune image reçue."}, status_code=400)
    try:
        saved = uploads.save_asset_bytes(await upload.read(), upload.filename, EVENTS_ASSETS_DIR,
                                         preferred_stem=event_type, max_side=1600)
    except uploads.UploadError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    config = _current(event_type)
    config["image"] = saved
    await asyncio.to_thread(_write, event_type, config, [f"assets/events/{saved}"])
    path = EVENTS_ASSETS_DIR / saved
    return {"ok": True, "image": saved, "image_url": f"/assets/events/{saved}?v={int(path.stat().st_mtime)}"}


@router.post("/{event_type}/spawn")
async def events_spawn(event_type: str, user: AdminUser = Depends(require_admin)):
    """Fait apparaître l'événement tout de suite (le bot le prend dans les
    5 secondes, cf. AdminBridgeCog) — pas s'il y en a déjà un en cours."""
    from app.infrastructure.db.repositories.admin_command_repository import AdminCommandRepository
    from app.infrastructure.db.repositories.event_repository import EventRepository

    if event_type not in cfg.EVENT_TYPES:
        return JSONResponse({"error": "Événement inconnu."}, status_code=404)
    with get_db_session() as session:
        if EventRepository(session).get_active_by_type(event_type) is not None:
            return JSONResponse({"error": f"{_TYPE_LABELS[event_type]} est déjà en cours : attends qu'il se termine."},
                                status_code=409)
        AdminCommandRepository(session).enqueue("spawn_event", {"event_type": event_type}, user.discord_id)
        session.commit()
    _logger.info("Admin %s fait apparaître l'event %s", user.discord_id, event_type)
    return {"ok": True, "message": f"{_TYPE_LABELS[event_type]} : demandé au bot, il apparaît dans quelques secondes."}


# ----------------------------------------- ancien formulaire (conservé) ---
def _form_to_raw(event_type: str, form) -> dict:
    raw: dict = {
        "enabled": form.get("enabled"),
        "cadence": {"times": form.get("cadence_times"), "per_days": form.get("cadence_per_days")},
        "channel": form.get("channel"),
    }
    if event_type == "chest":
        kinds, codes, qtys = form.getlist("loot_kind"), form.getlist("loot_item_code"), form.getlist("loot_quantity")
        golds, weights = form.getlist("loot_gold"), form.getlist("loot_weight")
        at = lambda values, i, default: values[i] if i < len(values) else default  # noqa: E731
        raw["loot"] = [{"kind": kinds[i], "item_code": at(codes, i, ""), "quantity": at(qtys, i, "1"),
                        "gold_amount": at(golds, i, "0"), "weight": at(weights, i, "0")} for i in range(len(kinds))]
        raw["level_scaling_pct"] = form.get("level_scaling_pct")
        raw["expire_after_minutes"] = form.get("expire_after_minutes")
    else:
        for key in ("trap_probability", "gold_loss_per_level", "title_chance", "resolve_after_minutes",
                    "max_level", "window_minutes"):
            if form.get(key) is not None:
                raw[key] = form.get(key)
    return raw


@router.post("/{event_type}")
async def events_update(event_type: str, request: Request, user: AdminUser = Depends(require_admin)):
    if event_type not in cfg.EVENT_TYPES:
        return RedirectResponse("/admin/events", status_code=303)
    form = await request.form()
    config, _ = clean(event_type, _form_to_raw(event_type, form), _current(event_type))
    push = []
    upload = form.get("image_file")
    if upload is not None and getattr(upload, "filename", ""):
        try:
            content = await upload.read()
            if content:
                saved = uploads.save_asset_bytes(content, upload.filename, EVENTS_ASSETS_DIR, preferred_stem=event_type)
                config["image"] = saved
                push.append(f"assets/events/{saved}")
        except uploads.UploadError as exc:
            _logger.warning("upload image event %s échoué: %s", event_type, exc)
    _write(event_type, config, push)
    _logger.info("Admin %s a mis à jour l'event %s", user.discord_id, event_type)
    return RedirectResponse(f"/admin/events#{event_type}", status_code=303)
