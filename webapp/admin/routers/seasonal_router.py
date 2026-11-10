"""Admin : ÉVÉNEMENTS SAISONNIERS (`seasonal_events.json`).

Demande de l'auteur (10/11/2026) : pour le lancement de la saison 1, le
calendrier de l'Avent, Noël (cadeau selon la gentillesse, sucres d'orge,
atelier des lutins) et le Nouvel An — et des boutiques d'événement qu'on
réutilisera souvent. Puis (même jour) : un réglage VISUEL — le calendrier
tel que les joueurs le verront, une case cliquée = son contenu ; les
messages Discord en aperçu, construits par le code du bot lui-même.

Le bot relit le fichier dès qu'il change (pas de redémarrage). Pour TESTER
sur la bêta : avancer les dates, puis les remettre.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from datetime import UTC, date, datetime, time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import select

from app.domain.services import seasonal_service as ss
from app.infrastructure.db.models.seasonal_model import SeasonalClaimModel
from app.infrastructure.db.repositories.seasonal_repository import SeasonalRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.offering import offering_loader
from app.infrastructure.seasonal import seasonal_loader
from app.shared.paths import ASSETS_DIR
from webapp.admin import json_writer
from webapp.admin._shared import get_templates
from webapp.admin.auth import AdminUser, require_admin

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/seasonal", tags=["admin-seasonal"])

_FILE = "seasonal_events.json"
#: Ce qu'on ne donne PAS en récompense : l'équipement (des exemplaires, pas
#: des objets d'inventaire) et les cartes (elles viennent des boosters).
_NOT_GIVEN = {"arme", "bouclier", "tete", "corps", "accessoire", "carte"}
_CATEGORY_LABELS = {"consumable": "Consommables", "resource": "Ressources", "cosmetic": "Cosmétiques"}
#: Exemples de joueurs pour estimer les objets d'événement (monstres vaincus par jour).
PROFILES = (("Occasionnel", 15), ("Régulier", 40), ("Assidu", 80))
TIER_LABELS = {ss.NAUGHTY: "Pas très sage", ss.NICE: "Sage", ss.ANGEL: "Cœur d'or", ss.UNKNOWN: "Jamais croisée"}


def _items() -> list[dict]:
    from app.bot.rendering.advent_calendar import item_emoji, item_picture_path

    items = json_writer.load_json("items.json", []) or []
    rows = []
    for i in items:
        if i.get("category") in _NOT_GIVEN:
            continue
        picture = item_picture_path(i["code"])
        rows.append({"code": i["code"], "name": i["name"], "category": i.get("category", ""),
                     "group": _CATEGORY_LABELS.get(i.get("category", ""), "Autres"),
                     "img": f"/assets/{picture.relative_to(ASSETS_DIR).as_posix()}" if picture else "",
                     "emoji": item_emoji(i["code"], i.get("category", ""))})
    order = list(_CATEGORY_LABELS)
    return sorted(rows, key=lambda r: (order.index(r["category"]) if r["category"] in order else 9, r["name"]))


def _script_json(data) -> str:
    """JSON pour un <script type="application/json"> : ordre des clés gardé
    (pas le filtre `tojson`, qui les trie), `</` échappé."""
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def _status(now: datetime) -> dict:
    content = seasonal_loader.get_content()
    stats: dict = {"advent": {}, "tiers": {}, "shops": {}}
    announced: set[str] = set()
    try:
        with get_db_session() as session:
            repo = SeasonalRepository(session)
            announced = repo.announced()
            stats["advent"] = repo.claim_counts("advent")
            payloads = session.execute(select(SeasonalClaimModel.payload_json)
                                       .where(SeasonalClaimModel.event_code == "christmas")).scalars()
            stats["tiers"] = dict(Counter(json.loads(p or "{}").get("tier", "?") for p in payloads))
            stats["shops"] = {s.code: repo.shop_sales(s.code) for s in content.shops}
    except Exception:  # noqa: BLE001 — base absente (démo) : la page s'affiche quand même
        _logger.warning("statistiques des événements saisonniers indisponibles", exc_info=True)
    announcements = [{"key": a.key, "kind": a.kind, "at": a.at.astimezone(ss.PARIS),
                      "posted": a.key in announced, "late": a.until <= now}
                     for a in ss.announcements(content)]
    return {"announcements": announcements, "stats": stats, "problems": list(content.problems)}


def _render(request: Request, user: AdminUser, data: dict, errors: list[str] | None = None,
            saved: bool = False, status_code: int = 200):
    now = datetime.now(UTC)
    deities = [{"emoji": d.emoji, "name": d.name, "blessing": d.blessing} for d in offering_loader.list_deities()]
    return get_templates().TemplateResponse(
        request, "admin/seasonal/index.html", status_code=status_code,
        context={"user": user, "data_json": _script_json(data), "items_json": _script_json(_items()),
                 "meta_json": _script_json({"today": ss.paris_day(now).isoformat(), "deities": deities,
                                            "profiles": PROFILES, "tiers": TIER_LABELS}),
                 "errors": errors or [], "saved": saved, "status": _status(now), "tier_labels": TIER_LABELS})


def _validated(data) -> tuple[dict | None, list[str]]:
    if not isinstance(data, dict):
        return None, ["Contenu illisible : rien n'a été enregistré."]
    previous = json_writer.load_json(_FILE, {}) or {}
    if "_comment" in previous:
        data = {"_comment": previous["_comment"], **{k: v for k, v in data.items() if k != "_comment"}}
    return data, ss.validate(data, {i["code"] for i in _items()})


def _write(data: dict, user: AdminUser) -> None:
    json_writer.atomic_write_json(_FILE, data)
    seasonal_loader.clear_cache()
    _logger.info("Admin %s a modifié les événements saisonniers", user.discord_id)


@router.get("", response_class=HTMLResponse)
async def seasonal_page(request: Request, saved: int = 0, user: AdminUser = Depends(require_admin)):
    seasonal_loader.clear_cache()
    data = json_writer.load_json(_FILE, {}) or {}
    return _render(request, user, data, saved=bool(saved))


@router.post("")
async def seasonal_save_form(request: Request, user: AdminUser = Depends(require_admin)):
    """Enregistrement par formulaire (champ `content`, sans JavaScript)."""
    form = await request.form()
    try:
        raw = json.loads(str(form.get("content") or ""))
    except ValueError:
        raw = None
    data, problems = _validated(raw)
    if problems:
        return _render(request, user, data or json_writer.load_json(_FILE, {}) or {}, errors=problems,
                       status_code=400)
    _write(data, user)
    return RedirectResponse("/admin/seasonal?saved=1", status_code=303)


@router.post("/save")
async def seasonal_save(request: Request, user: AdminUser = Depends(require_admin)):
    """Enregistrement depuis l'éditeur (JSON) : rien n'est écrit s'il reste un problème."""
    try:
        raw = await request.json()
    except ValueError:
        raw = None
    data, problems = _validated(raw)
    if problems:
        return JSONResponse({"ok": False, "errors": problems}, status_code=400)
    _write(data, user)
    return {"ok": True}


# ---------------------------------------------------------------- aperçus
async def _json(request: Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _advent_png(advent_raw: dict, day: int) -> bytes | None:
    from app.application.use_cases.seasonal import AdventStatus
    from app.bot.rendering.advent_calendar import render_advent

    advent = ss.parse_content({"advent": advent_raw}).advent
    if advent is None or not advent.size:
        return None
    day = max(1, min(advent.size, int(day or 1)))
    today = advent.start.toordinal() + day - 1
    opened = set(range(1, day))
    status = AdventStatus(advent, day, frozenset(opened),
                          tuple(ss.door_states(advent, date.fromordinal(today), opened)), 20, {})
    return render_advent(status, "Aperçu")


@router.post("/preview/advent.png")
async def preview_advent(request: Request, user: AdminUser = Depends(require_admin)):
    """L'image EXACTE du calendrier (code du bot) : les cases d'avant `day`
    ouvertes, celle de `day` à ouvrir — ce que voit un joueur ce jour-là."""
    body = await _json(request)
    try:
        png = await asyncio.to_thread(_advent_png, body.get("advent") or {}, int(body.get("day") or 1))
    except (TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    if png is None:
        return JSONResponse({"error": "Calendrier vide ou date illisible."}, status_code=400)
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


def _names() -> dict[str, str]:
    return {i["code"]: i["name"] for i in json_writer.load_json("items.json", []) or []}


def _embed_preview(body: dict) -> dict:
    """Le message Discord tel que le bot l'écrirait, avec le contenu en cours
    d'édition (pas encore enregistré)."""
    from app.application.use_cases.seasonal import ChristmasStatus, ShopStatus
    from app.bot.embeds import seasonal_embeds as se

    content = ss.parse_content(body.get("content") or {})
    if content.problems:
        return {"error": content.problems[0]}
    kind, ref = str(body.get("kind") or ""), str(body.get("ref") or "")
    level = max(1, min(100, int(body.get("level") or 20)))
    names = _names()
    text = None
    if kind == "panel":
        try:
            day = date.fromisoformat(str(body.get("date")))
        except ValueError:
            day = ss.paris_day()
        moment = datetime.combine(day, time(12, 0), tzinfo=ss.PARIS)
        embed = se.build_panel_embed(content, ss.happening(content, moment))
    elif kind == "advent" and content.advent is not None:
        embed = se.build_advent_announcement(content.advent)
    elif kind == "drop" and (drop := next((d for d in content.drops if d.code == ref), None)) is not None:
        embed = se.build_drop_announcement(drop, names.get(drop.item, drop.item))
    elif kind == "christmas" and content.christmas is not None:
        shops = [s for s in content.shops if s.enabled and s.opens == content.christmas.gift_day]
        embed = se.build_christmas_announcement(content.christmas, shops)
    elif kind == "gift" and content.christmas is not None:
        c = content.christmas
        tier = ref if ref in TIER_LABELS else ss.NICE
        pct = {ss.NAUGHTY: c.kindness.naughty_pct, ss.NICE: c.kindness.nice_pct,
               ss.ANGEL: c.kindness.angel_pct, ss.UNKNOWN: c.kindness.unknown_pct}[tier]
        k = ss.Kindness(0, 0, tier, pct)
        status = ChristmasStatus(c, True, False, k, c.gift_for(k), level, names)
        embed = se.build_christmas_embed(status, granted=status.lines)
    elif kind == "shop" and (shop := content.shop(ref)) is not None:
        status = ShopStatus(shop, True, int(body.get("balance") or 0), {}, names)
        embed = se.build_shop_embed(status)
    elif kind == "new_year" and content.new_year is not None:
        deities = offering_loader.list_deities()
        embed = se.build_new_year_announcement(content.new_year, deities)
        text = "@everyone" if content.new_year.mention_everyone else None
    else:
        return {"error": "Rien à montrer pour l'instant."}
    return {"content": text, "embeds": [embed.to_dict()]}


@router.post("/preview/embed")
async def preview_embed(request: Request, user: AdminUser = Depends(require_admin)):
    body = await _json(request)
    try:
        return JSONResponse(await asyncio.to_thread(_embed_preview, body))
    except (TypeError, ValueError, KeyError) as exc:
        return JSONResponse({"error": f"Aperçu impossible : {exc}"}, status_code=400)
