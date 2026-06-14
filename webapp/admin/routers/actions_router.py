"""Routes admin : page d'actions rapides (give_gold, give_xp, set_level,
give_item, give_skill_points). Forme à formulaire qui exécute directement
sur la DB sans passer par Discord.
"""

from __future__ import annotations

import logging
from collections import Counter
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Request, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.inventory_repository import (
    InventoryRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.sets.set_loader import list_definitions as list_set_definitions
from webapp.admin.auth import AdminUser, require_admin
from webapp.admin._shared import get_templates


_logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/actions", tags=["admin-actions"])




def _resolve_player_id(session, raw: str) -> int | None:
    """Accepte un Discord ID ou un username."""
    raw = (raw or "").strip()
    if not raw:
        return None
    repo = PlayerRepository(session)
    if raw.isdigit():
        profile = repo.get_by_discord_id(int(raw))
        if profile:
            return profile.player.id
    # fallback : search by username
    for p in repo.list_all_profiles():
        if p.player.username == raw or p.player.display_name == raw:
            return p.player.id
    return None


@router.get("", response_class=HTMLResponse)
async def actions_page(
    request: Request,
    user: AdminUser = Depends(require_admin),
    message: str | None = None,
    error: str | None = None,
):
    with get_db_session() as session:
        profiles = PlayerRepository(session).list_all_profiles()
        items = ItemRepository(session).list_all()

    # Familles de panoplie = familles distinctes parmi les items ÉQUIPABLES.
    # Compte les pièces par famille + nom/icône depuis sets.json si dispo.
    equip_items = [it for it in items if (it.equipment_slot or None) and (it.family or "")]
    counts = Counter(it.family for it in equip_items)
    sets_def = list_set_definitions()
    families = [
        {
            "code": code,
            "name": (sets_def.get(code) or {}).get("name", code),
            "icon": (sets_def.get(code) or {}).get("icon", "🧩"),
            "count": n,
        }
        for code, n in sorted(counts.items())
    ]

    return get_templates().TemplateResponse(
        request, "admin/actions.html",
        context={
            "user": user,
            "profiles": [
                {
                    "discord_id": p.player.discord_id,
                    "display_name": p.player.display_name,
                    "username": p.player.username,
                }
                for p in profiles
            ],
            "items": [{"code": it.code, "name": it.name} for it in items],
            "families": families,
            "flash_message": message,
            "flash_error": error,
        },
    )


async def _apply_amount(request: Request, repo_method: str, noun: str, user: AdminUser):
    """Donner OU retirer un montant (or/xp/skill points). `action` = give|take ;
    le montant saisi est toujours POSITIF, la direction vient du sélecteur.
    Les méthodes add_* du repo clampent le solde à 0 (retrait sûr)."""
    form = await request.form()
    target = form.get("target", "")
    action = (form.get("action", "give") or "give").strip()
    try:
        amount = int(form.get("amount", "0"))
    except ValueError:
        return RedirectResponse("/admin/actions?error=Montant+invalide", status_code=303)
    if amount <= 0:
        return RedirectResponse("/admin/actions?error=Montant+doit+%C3%AAtre+positif", status_code=303)

    delta = -amount if action == "take" else amount
    with get_db_session() as session:
        pid = _resolve_player_id(session, target)
        if pid is None:
            return RedirectResponse(f"/admin/actions?error=Joueur+%60{target}%60+introuvable", status_code=303)
        getattr(PlayerRepository(session), repo_method)(pid, delta)
    verb = "retiré" if action == "take" else "ajouté"
    _logger.info("Admin %s %s %d %s to/from %s", user.discord_id, action, amount, noun, target)
    return RedirectResponse(
        f"/admin/actions?message={quote_plus(f'{amount} {noun} {verb}')}", status_code=303
    )


@router.post("/give_gold")
async def give_gold(request: Request, user: AdminUser = Depends(require_admin)):
    return await _apply_amount(request, "add_gold", "or", user)


@router.post("/give_xp")
async def give_xp(request: Request, user: AdminUser = Depends(require_admin)):
    return await _apply_amount(request, "add_xp", "XP", user)


@router.post("/set_level")
async def set_level(
    request: Request,
    user: AdminUser = Depends(require_admin),
):
    form = await request.form()
    target = form.get("target", "")
    try:
        new_level = int(form.get("level", "0"))
        if new_level < 1:
            raise ValueError
    except ValueError:
        return RedirectResponse("/admin/actions?error=Niveau+invalide", status_code=303)

    with get_db_session() as session:
        repo = PlayerRepository(session)
        pid = _resolve_player_id(session, target)
        if pid is None:
            return RedirectResponse(f"/admin/actions?error=Joueur+%60{target}%60+introuvable", status_code=303)
        profile = repo.get_profile_by_player_id(pid)
        repo.apply_progression(
            player_id=pid,
            new_level=new_level,
            new_xp=0,
            new_skill_points=profile.progression.skill_points,
        )
    return RedirectResponse(f"/admin/actions?message=Niveau+r%C3%A9gl%C3%A9+%C3%A0+{new_level}", status_code=303)


@router.post("/give_skill_points")
async def give_skill_points(request: Request, user: AdminUser = Depends(require_admin)):
    return await _apply_amount(request, "add_skill_points", "skill points", user)


@router.post("/give_item")
async def give_item(
    request: Request,
    user: AdminUser = Depends(require_admin),
):
    form = await request.form()
    target = form.get("target", "")
    item_code = form.get("item_code", "").strip()
    action = (form.get("action", "give") or "give").strip()
    try:
        qty = int(form.get("quantity", "1"))
        if qty < 1:
            raise ValueError
    except ValueError:
        return RedirectResponse("/admin/actions?error=Quantit%C3%A9+invalide", status_code=303)

    with get_db_session() as session:
        pid = _resolve_player_id(session, target)
        if pid is None:
            return RedirectResponse(f"/admin/actions?error=Joueur+%60{target}%60+introuvable", status_code=303)
        item = ItemRepository(session).get_by_code(item_code)
        if item is None:
            return RedirectResponse(f"/admin/actions?error=Item+%60{item_code}%60+introuvable", status_code=303)
        inv = InventoryRepository(session)
        if action == "take":
            ok = inv.remove_item(pid, item.id, qty)
            msg = (f"{qty} × {item_code} retiré" if ok
                   else f"Retrait impossible : {item_code} en quantité insuffisante")
        else:
            inv.add_item(pid, item.id, qty)
            msg = f"{qty} × {item_code} ajouté"
    return RedirectResponse(f"/admin/actions?message={quote_plus(msg)}", status_code=303)


@router.post("/panoplie")
async def panoplie_action(
    request: Request,
    user: AdminUser = Depends(require_admin),
):
    """Donne OU retire une panoplie complète : 1 exemplaire de CHAQUE pièce
    équipable de la famille (armures, accessoires, armes, boucliers).
    `action` = 'give' (ajoute) ou 'take' (retire ce que le joueur possède)."""
    form = await request.form()
    target = form.get("target", "")
    family = (form.get("family", "") or "").strip()
    action = (form.get("action", "give") or "give").strip()
    if not family:
        return RedirectResponse("/admin/actions?error=Panoplie+non+sp%C3%A9cifi%C3%A9e", status_code=303)

    with get_db_session() as session:
        pid = _resolve_player_id(session, target)
        if pid is None:
            return RedirectResponse(f"/admin/actions?error=Joueur+%60{target}%60+introuvable", status_code=303)
        item_repo = ItemRepository(session)
        inv_repo = InventoryRepository(session)
        # Toutes les pièces ÉQUIPABLES de cette famille (1 de chaque).
        pieces = [
            it for it in item_repo.list_all()
            if (it.family or "") == family and (it.equipment_slot or None)
        ]
        if not pieces:
            return RedirectResponse(
                f"/admin/actions?error=Aucune+pi%C3%A8ce+%C3%A9quipable+pour+la+panoplie+{quote_plus(family)}",
                status_code=303,
            )
        if action == "take":
            # remove_item renvoie False si le joueur n'a pas la pièce → on
            # compte celles réellement retirées.
            count = sum(1 for it in pieces if inv_repo.remove_item(pid, it.id, 1))
            verb = "retirée"
        else:
            for it in pieces:
                inv_repo.add_item(pid, it.id, 1)
            count = len(pieces)
            verb = "donnée"

    _logger.info("Admin %s %s panoplie '%s' (%d pieces) to/from %s",
                 user.discord_id, action, family, count, target)
    msg = quote_plus(f"Panoplie {family} {verb} ({count} pièces)")
    return RedirectResponse(f"/admin/actions?message={msg}", status_code=303)
