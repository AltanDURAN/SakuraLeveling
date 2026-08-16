"""Routes admin : page d'ACTIONS RAPIDES — toute l'administration depuis le site.

Deux familles d'actions :

1. **Directes** (or, XP, niveau, points de compétence, items, panoplies, PV,
   cooldowns, buffs, reset) : la webapp écrit directement en base, l'effet est
   immédiat.
2. **Déléguées au bot** (spawn de monstre / boss / événement, arrêt d'un
   combat) : la webapp ne peut pas parler à Discord — elle dépose une commande
   dans `admin_commands`, que `AdminBridgeCog` exécute côté bot en quelques
   secondes. Le journal en bas de page affiche le statut et le résultat.
"""

from __future__ import annotations

import logging
from collections import Counter
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Request, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.infrastructure.db.repositories.admin_command_repository import (
    AdminCommandRepository,
)
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.inventory_repository import (
    InventoryRepository,
)
from app.infrastructure.db.repositories.player_health_repository import (
    PlayerHealthRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_status_effect_repository import (
    PlayerStatusEffectRepository,
)
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
    from app.infrastructure.db.repositories.mob_repository import MobRepository
    from app.infrastructure.world_boss.boss_definition_loader import (
        list_definitions as list_boss_definitions,
    )
    from app.infrastructure.events import event_config_loader

    with get_db_session() as session:
        profiles = PlayerRepository(session).list_all_profiles()
        items = ItemRepository(session).list_all()
        mobs = [
            {"code": m.code, "name": m.name, "family": m.family or ""}
            for m in MobRepository(session).list_all()
        ]
        # Journal des commandes envoyées au bot (statut + résultat).
        bot_commands = [
            {
                "action": c.action,
                "label": _BOT_ACTION_LABELS.get(c.action, c.action),
                "payload": c.payload_json,
                "status": c.status,
                "result": c.result,
                "created_at": c.created_at,
            }
            for c in AdminCommandRepository(session).list_recent(12)
        ]

    bosses = [{"code": b.code, "name": b.name} for b in list_boss_definitions()]
    event_config_loader.clear_cache()
    events = [
        {"code": code, "label": cfg.get("label", code),
         "enabled": bool(cfg.get("enabled"))}
        for code, cfg in event_config_loader.all_configs().items()
    ]

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
            "mobs": sorted(mobs, key=lambda m: (m["family"], m["name"])),
            "bosses": bosses,
            "events": events,
            "bot_commands": bot_commands,
            "cooldown_keys": [
                ("", "Tous les cooldowns"),
                ("daily", "/daily — récompense quotidienne"),
                ("duel_challenge", "Duel 1v1 (anti-spam 60 s)"),
                ("skill_tree_reset", "Reset de l'arbre (7 j)"),
                ("world_boss_fight", "Combat de world boss (1/jour)"),
            ],
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


# ---------------------------------------------------------------------------
# Actions DIRECTES supplémentaires (PV, cooldowns, buffs, reset)
# ---------------------------------------------------------------------------

def _redirect(message: str = "", error: str = "") -> RedirectResponse:
    key, value = ("error", error) if error else ("message", message)
    return RedirectResponse(f"/admin/actions?{key}={quote_plus(value)}", status_code=303)


def _resolved(session, form) -> tuple[int | None, str]:
    target = form.get("target", "")
    return _resolve_player_id(session, target), target


@router.post("/set_hp")
async def set_hp(request: Request, user: AdminUser = Depends(require_admin)):
    """Fixe les PV COURANTS d'un joueur (ou les met au max avec « heal »).

    Rappel d'invariant : les PV courants ne vivent PAS sur `Player` mais dans
    `player_health_states`."""
    form = await request.form()
    mode = (form.get("mode", "set") or "set").strip()
    with get_db_session() as session:
        pid, target = _resolved(session, form)
        if pid is None:
            return _redirect(error=f"Joueur `{target}` introuvable")

        health_repo = PlayerHealthRepository(session)
        if mode == "heal":
            # Max HP = stats complètes (équipement, arbre, titres, buffs, forge).
            from app.application.services.player_stats_resolver import (
                resolve_player_stats,
            )
            from app.infrastructure.db.repositories.class_repository import (
                ClassRepository,
            )
            from app.infrastructure.db.repositories.equipment_repository import (
                EquipmentRepository,
            )
            profile = PlayerRepository(session).get_profile_by_player_id(pid)
            stats = resolve_player_stats(
                session=session, profile=profile,
                equipped_items=EquipmentRepository(session).list_by_player_id(pid),
                active_class=ClassRepository(session).get_current_class_for_player(pid),
            )
            health_repo.get_or_create(pid, default_current_hp=stats.max_hp)
            health_repo.update_current_hp(pid, stats.max_hp)
            _logger.info("Admin %s a soigné %s à fond (%d PV)", user.discord_id, target, stats.max_hp)
            return _redirect(f"{target} soigné au maximum ({stats.max_hp} PV)")

        try:
            hp = max(0, int(form.get("hp", "0")))
        except ValueError:
            return _redirect(error="PV invalides")
        health_repo.get_or_create(pid, default_current_hp=hp)
        health_repo.update_current_hp(pid, hp)
        _logger.info("Admin %s a fixé les PV de %s à %d", user.discord_id, target, hp)
        return _redirect(f"PV de {target} fixés à {hp}")


@router.post("/reset_cooldowns")
async def reset_cooldowns(request: Request, user: AdminUser = Depends(require_admin)):
    """Remet à zéro les cooldowns de commandes d'un joueur (/daily, duel,
    reset d'arbre, combat de boss…). `action_key` vide = tous."""
    form = await request.form()
    action_key = (form.get("action_key", "") or "").strip()
    with get_db_session() as session:
        pid, target = _resolved(session, form)
        if pid is None:
            return _redirect(error=f"Joueur `{target}` introuvable")
        from sqlalchemy import delete
        from app.infrastructure.db.models.cooldown_model import PlayerCooldownModel
        stmt = delete(PlayerCooldownModel).where(PlayerCooldownModel.player_id == pid)
        if action_key:
            stmt = stmt.where(PlayerCooldownModel.action_key == action_key)
        removed = session.execute(stmt).rowcount or 0
        session.commit()
    label = f"« {action_key} »" if action_key else "tous"
    _logger.info("Admin %s a reset les cooldowns (%s) de %s", user.discord_id, label, target)
    return _redirect(f"{removed} cooldown(s) {label} remis à zéro pour {target}")


@router.post("/status_effect")
async def status_effect(request: Request, user: AdminUser = Depends(require_admin)):
    """Applique un buff/debuff temporaire (multiplicateur sur TOUTES les stats
    positives), ou purge les effets actifs du joueur."""
    form = await request.form()
    mode = (form.get("mode", "add") or "add").strip()
    with get_db_session() as session:
        pid, target = _resolved(session, form)
        if pid is None:
            return _redirect(error=f"Joueur `{target}` introuvable")
        repo = PlayerStatusEffectRepository(session)
        if mode == "clear":
            repo.clear_for_player(pid)
            session.commit()
            _logger.info("Admin %s a purgé les effets de %s", user.discord_id, target)
            return _redirect(f"Effets temporaires de {target} purgés")
        try:
            pct = int(form.get("percent", "10"))
            hours = max(1, int(form.get("hours", "3")))
        except ValueError:
            return _redirect(error="Pourcentage ou durée invalide")
        multiplier = max(0.05, 1 + pct / 100)
        repo.add(pid, "admin_web", multiplier, hours * 3600)
        session.commit()
    sign = "+" if pct >= 0 else ""
    _logger.info("Admin %s a appliqué %s%d%% %dh à %s", user.discord_id, sign, pct, hours, target)
    return _redirect(f"Effet {sign}{pct}% pendant {hours}h appliqué à {target}")


@router.post("/reset_player")
async def reset_player(request: Request, user: AdminUser = Depends(require_admin)):
    """Réinitialise TOUT un joueur (sauf son identité Discord). Irréversible."""
    form = await request.form()
    if (form.get("confirm", "") or "").strip().upper() != "RESET":
        return _redirect(error="Tape RESET pour confirmer la réinitialisation")
    with get_db_session() as session:
        pid, target = _resolved(session, form)
        if pid is None:
            return _redirect(error=f"Joueur `{target}` introuvable")
        from app.application.use_cases.reset_player import ResetPlayerUseCase
        ResetPlayerUseCase().execute(session, pid)
        session.commit()
    _logger.warning("Admin %s a RESET le joueur %s", user.discord_id, target)
    return _redirect(f"Joueur {target} entièrement réinitialisé")


# ---------------------------------------------------------------------------
# Actions déléguées au BOT (file `admin_commands`)
# ---------------------------------------------------------------------------

_BOT_ACTION_LABELS = {
    "spawn_encounter": "Spawn d'un monstre",
    "stop_encounter": "Arrêt du combat en cours",
    "resolve_encounter": "Résolution immédiate du combat",
    "spawn_boss": "Spawn d'un world boss",
    "stop_boss": "Arrêt du world boss",
    "spawn_event": "Spawn d'un événement",
}


@router.post("/bot/{action}")
async def bot_action(action: str, request: Request, user: AdminUser = Depends(require_admin)):
    """Dépose une commande pour le bot. Il la ramasse en ≤ 5 s et écrit le
    résultat, visible dans le journal en bas de page."""
    from app.infrastructure.db.repositories.admin_command_repository import (
        KNOWN_ACTIONS,
    )
    if action not in KNOWN_ACTIONS:
        return _redirect(error=f"Action bot inconnue : {action}")

    form = await request.form()
    payload: dict = {}
    if action == "spawn_encounter":
        if (form.get("mob_code") or "").strip():
            payload["mob_code"] = form.get("mob_code").strip()
        if (form.get("element") or "").strip():
            payload["element"] = form.get("element").strip()
    elif action == "spawn_boss":
        code = (form.get("boss_code") or "").strip()
        if not code:
            return _redirect(error="Choisis un boss à faire spawner")
        payload["boss_code"] = code
    elif action == "spawn_event":
        event_type = (form.get("event_type") or "").strip()
        if not event_type:
            return _redirect(error="Choisis un type d'événement")
        payload["event_type"] = event_type

    with get_db_session() as session:
        AdminCommandRepository(session).enqueue(action, payload, user.discord_id)
        session.commit()
    _logger.info("Admin %s a demandé au bot : %s %s", user.discord_id, action, payload)
    return _redirect(
        f"{_BOT_ACTION_LABELS.get(action, action)} demandé — le bot l'exécute dans quelques secondes"
    )
