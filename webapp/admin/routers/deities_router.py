"""Monde › Divinités (28/11/2026, demande de l'auteur) : les sept divinités de
l'offrande et le Grand Cerisier, chacun avec sa carte telle que le bot la
dessine (normale et brillante), sa bénédiction, l'effet de sa carte et d'où
vient son image (la tienne ou une ébauche). On y dépose l'image de la carte
et l'illustration pleine carte de la brillante — mêmes fichiers que la fiche
de la carte (`assets/cards/<code>.png`, `<code>_fullart.png`), le bot suit
sans redémarrer. La formule et les effets de l'offrande restent sur la page
Offrande."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.domain.services import card_service as cs
from app.infrastructure.cards import card_loader
from app.infrastructure.offering import offering_loader
from webapp.admin._shared import get_templates
from webapp.admin.auth import AdminUser, require_admin
from webapp.admin.routers import cards_router

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/divinites", tags=["admin-divinites"])

#: Le Grand Cerisier n'est pas une divinité de l'offrande, mais il trône avec
#: elles dans l'album (carte mythique, toujours brillante).
TREE = "grand_cerisier"


def _entries() -> list[dict]:
    from app.bot.rendering import card_render

    card_loader.clear_cache()
    offering_loader.clear_cache()
    rows = []
    for deity in offering_loader.list_deities():
        card = card_loader.get_card(deity.code)
        rows.append({"code": deity.code, "name": deity.name, "title": deity.title, "emoji": deity.emoji,
                     "blessing": deity.blessing, "card": card})
    tree = card_loader.get_card(TREE)
    if tree is not None:
        rows.append({"code": TREE, "name": tree.name, "title": tree.title, "emoji": "🌸",
                     "blessing": "", "card": tree})
    for row in rows:
        card = row["card"]
        if card is None:
            continue
        row["effect"] = cs.effect_text(card)
        row["origin"] = card_loader.art_origin(card)
        row["mine"] = row["origin"] == "carte"
        row["fullart"] = card_loader.full_art_path(card) is not None
        row["mythic"] = card.always_brillante
        row["v_normal"] = card_render.render_version(card, False)
        row["v_shiny"] = card_render.render_version(card, True)
    return rows


@router.get("")
async def deities_page(request: Request, user: AdminUser = Depends(require_admin)):
    return get_templates().TemplateResponse(request, "admin/deities/index.html", context={
        "user": user, "rows": _entries(),
        "saved": request.query_params.get("ok"), "error": request.query_params.get("erreur"),
    })


@router.post("/{code}/{kind}")
async def deity_upload(code: str, kind: str, request: Request, user: AdminUser = Depends(require_admin)):
    allowed = {d.code for d in offering_loader.list_deities()} | {TREE}
    if code not in allowed or kind not in ("carte", "fullart"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Divinité ou image inconnue.")
    error = await cards_router._upload(request, code, kind)
    if error:
        from urllib.parse import quote
        return RedirectResponse(f"/admin/divinites?erreur={quote(error)}#{code}", status_code=303)
    card_loader.clear_cache()
    _logger.info("Admin %s a changé %s de %s", user.discord_id, cards_router.ART_KINDS[kind], code)
    return RedirectResponse(f"/admin/divinites?ok={code}#{code}", status_code=303)
