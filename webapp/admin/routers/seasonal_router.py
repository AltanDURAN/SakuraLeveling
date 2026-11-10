"""Admin : ÉVÉNEMENTS SAISONNIERS (`seasonal_events.json`).

Demande de l'auteur (10/11/2026) : pour le lancement de la saison 1, le
calendrier de l'Avent, Noël (cadeau selon la gentillesse, sucres d'orge,
atelier des lutins) et le Nouvel An — et des boutiques d'événement qu'on
réutilisera souvent. Tout se règle ici : dates, récompenses, articles et
prix, textes. Le bot relit le fichier dès qu'il change (pas de redémarrage).
Pour TESTER sur la bêta : avancer les dates, puis les remettre.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app.domain.services import seasonal_service as ss
from app.infrastructure.db.models.seasonal_model import SeasonalClaimModel
from app.infrastructure.db.repositories.seasonal_repository import SeasonalRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.seasonal import seasonal_loader
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


def _items() -> list[dict]:
    items = json_writer.load_json("items.json", []) or []
    rows = [{"code": i["code"], "name": i["name"], "category": i.get("category", "")}
            for i in items if i.get("category") not in _NOT_GIVEN]
    order = list(_CATEGORY_LABELS)
    return sorted(rows, key=lambda r: (order.index(r["category"]) if r["category"] in order else 9, r["name"]))


def _script_json(data) -> str:
    """JSON pour un <script type="application/json"> : ordre des clés gardé
    (pas le filtre `tojson`, qui les trie), `</` échappé."""
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def _status(now: datetime) -> dict:
    content = seasonal_loader.get_content()
    happening = ss.happening(content, now)
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
    return {"happening": happening, "announcements": announcements,
            "stats": stats, "problems": list(content.problems), "content": content}


def _render(request: Request, user: AdminUser, data: dict, errors: list[str] | None = None,
            saved: bool = False, status_code: int = 200):
    now = datetime.now(UTC)
    return get_templates().TemplateResponse(
        request, "admin/seasonal/index.html", status_code=status_code,
        context={"user": user, "data_json": _script_json(data), "items_json": _script_json(_items()),
                 "errors": errors or [], "saved": saved, "status": _status(now), "tier_labels": {
                     ss.UNKNOWN: "jamais croisée", ss.NAUGHTY: "pas très sage", ss.NICE: "sage",
                     ss.ANGEL: "cœur d'or"}})


@router.get("", response_class=HTMLResponse)
async def seasonal_page(request: Request, saved: int = 0, user: AdminUser = Depends(require_admin)):
    seasonal_loader.clear_cache()
    data = json_writer.load_json(_FILE, {}) or {}
    return _render(request, user, data, saved=bool(saved))


@router.post("")
async def seasonal_save(request: Request, user: AdminUser = Depends(require_admin)):
    form = await request.form()
    try:
        data = json.loads(str(form.get("content") or ""))
        if not isinstance(data, dict):
            raise ValueError
    except ValueError:
        return _render(request, user, json_writer.load_json(_FILE, {}) or {},
                       errors=["Contenu illisible : rien n'a été enregistré."], status_code=400)
    previous = json_writer.load_json(_FILE, {}) or {}
    if "_comment" in previous:
        data = {"_comment": previous["_comment"], **{k: v for k, v in data.items() if k != "_comment"}}
    problems = ss.validate(data, {i["code"] for i in _items()})
    if problems:
        return _render(request, user, data, errors=problems, status_code=400)
    json_writer.atomic_write_json(_FILE, data)
    seasonal_loader.clear_cache()
    _logger.info("Admin %s a modifié les événements saisonniers", user.discord_id)
    return RedirectResponse("/admin/seasonal?saved=1", status_code=303)
