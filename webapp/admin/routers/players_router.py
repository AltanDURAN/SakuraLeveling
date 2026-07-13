"""Routes admin pour les joueurs : liste + fiche « carte » (carousel) + sous-cartes.

Fiche principale d'un joueur (`/{id}/view`) avec navigation précédent/suivant +
sélecteur, et des sous-cartes focalisées (inventaire, équipement, titres,
affinités, compétences, duel) accessibles depuis la fiche avec retour arrière.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, status, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app.application.services.player_stats_resolver import resolve_player_stats
from app.application.use_cases.reset_player import ResetPlayerUseCase
from app.domain.services.power_score_service import PowerScoreService
from app.domain.services.progression_service import ProgressionService
from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.player_health_repository import PlayerHealthRepository
from app.infrastructure.db.repositories.player_mana_repository import PlayerManaRepository
from app.infrastructure.db.repositories.element_affinity_repository import (
    ElementAffinityRepository,
)
from app.infrastructure.db.repositories.element_essence_repository import (
    ElementEssenceRepository,
)
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_career_stats_repository import (
    PlayerCareerStatsRepository,
)
from app.infrastructure.db.repositories.player_duel_rank_repository import (
    PlayerDuelRankRepository,
)
from app.infrastructure.db.repositories.player_kill_repository import PlayerKillRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_title_repository import PlayerTitleRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.elements import element_skill_loader
from app.infrastructure.titles import title_loader
from app.shared.enums import ALL_ELEMENTS, ELEMENT_EMOJIS, ELEMENT_LABELS
from webapp.admin import discord_api
from webapp.admin.auth import AdminUser, require_admin
from webapp.admin._shared import get_templates


_logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/players", tags=["admin-players"])


def _fmt_dt(dt) -> str:
    return dt.strftime("%d/%m/%Y") if dt else "—"


# Mapping rang bot (lettre de base) → tier LoL + couleur du tier (pour le repli
# coloré et la teinte de la fleur). L'image d'emblème (si fournie) vit dans
# webapp/static/admin/ranks/<tier>.png.
_RANK_TIER: dict[str, tuple[str, str]] = {
    "F": ("iron", "#8a8a8a"),
    "E": ("bronze", "#b06a3b"),
    "D": ("silver", "#b8c2cf"),
    "C": ("gold", "#e3b23c"),
    "B": ("platinum", "#57c9d6"),
    "A": ("emerald", "#2ecc71"),
    "S": ("diamond", "#6ea8ff"),
    "SS": ("master", "#b06fe0"),
    "SSS": ("grandmaster", "#e35b4a"),
}


def _emblem_for_rank(rank) -> tuple[str, str]:
    """(tier, couleur) pour un rang. SSS+ → challenger (top absolu)."""
    if not rank:
        return ("iron", "#8a8a8a")
    r = str(rank)
    base = r.replace("+", "").replace("-", "")
    if base == "SSS" and "+" in r:
        return ("challenger", "#ecd07a")
    return _RANK_TIER.get(base, ("iron", "#8a8a8a"))


def _player_summary(profile, active_class) -> dict:
    return {
        "id": profile.player.id,
        "discord_id": profile.player.discord_id,
        "username": profile.player.username,
        "display_name": profile.player.display_name,
        "level": profile.progression.level,
        "xp": profile.progression.xp,
        "skill_points": profile.progression.skill_points,
        "gold": profile.resources.gold,
        "daily_streak": profile.resources.daily_streak,
        "class": active_class.name if active_class else "—",
        # created_at = arrivée sur le serveur (création du profil, à l'accueil ou
        # à la 1re commande) ; last_seen_at = dernière commande effectuée.
        "joined": _fmt_dt(profile.player.created_at),
        "last_seen": _fmt_dt(profile.player.last_seen_at),
    }


def _nav(session, current_id: int) -> dict:
    """Construit la navigation carousel : liste ordonnée pour le sélecteur +
    joueur précédent/suivant (ordre : niveau décroissant puis nom)."""
    profiles = PlayerRepository(session).list_all_profiles()
    ordered = sorted(
        profiles,
        key=lambda p: (-p.progression.level, p.player.display_name.lower()),
    )
    options = [
        {"id": p.player.id, "label": f"{p.player.display_name} (niv {p.progression.level})"}
        for p in ordered
    ]
    idx = next((i for i, p in enumerate(ordered) if p.player.id == current_id), None)
    prev_p = next_p = None
    if idx is not None:
        if idx > 0:
            pp = ordered[idx - 1]
            prev_p = {"id": pp.player.id, "name": pp.player.display_name}
        if idx < len(ordered) - 1:
            npp = ordered[idx + 1]
            next_p = {"id": npp.player.id, "name": npp.player.display_name}
    return {
        "options": options,
        "prev": prev_p,
        "next": next_p,
        "position": (idx + 1) if idx is not None else 0,
        "total": len(ordered),
    }


@router.get("", response_class=HTMLResponse)
async def players_list(
    request: Request,
    user: AdminUser = Depends(require_admin),
    q: str | None = None,
):
    with get_db_session() as session:
        profiles = PlayerRepository(session).list_all_profiles()

    rows = []
    for p in profiles:
        rows.append({
            "id": p.player.id,
            "discord_id": p.player.discord_id,
            "username": p.player.username,
            "display_name": p.player.display_name,
            "level": p.progression.level,
            "xp": p.progression.xp,
            "skill_points": p.progression.skill_points,
            "gold": p.resources.gold,
            "daily_streak": p.resources.daily_streak,
            "last_seen": p.player.last_seen_at.strftime("%Y-%m-%d %H:%M"),
        })

    if q:
        ql = q.lower()
        rows = [
            r for r in rows
            if ql in str(r["discord_id"])
            or ql in r["username"].lower()
            or ql in r["display_name"].lower()
        ]

    rows.sort(key=lambda r: -r["level"])

    return get_templates().TemplateResponse(
        request, "admin/players/list.html",
        context={"user": user, "rows": rows, "filter_q": q or ""},
    )


async def _base_ctx(session, user, player_id, section: str) -> tuple[dict, object]:
    """Contexte commun à toutes les cartes : identité + avatar + nav + stats/rang
    (le badge de rang est ainsi cohérent sur toutes les cartes)."""
    profile = PlayerRepository(session).get_profile_by_player_id(player_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Player #{player_id} introuvable.")
    active_class = ClassRepository(session).get_current_class_for_player(player_id)
    equipped = EquipmentRepository(session).list_by_player_id(player_id)

    stats = power = rank = None
    try:
        stats = resolve_player_stats(session, profile, equipped, active_class)
        pss = PowerScoreService()
        score = pss.calculate_from_stats(stats)
        power = pss.format_score(score)
        rank = pss.compute_rank(score)
    except Exception:
        _logger.warning("calcul stats échoué player %s", player_id, exc_info=True)

    tier, tier_color = _emblem_for_rank(rank)
    ctx = {
        "user": user,
        "section": section,
        "p": _player_summary(profile, active_class),
        "nav": _nav(session, player_id),
        "avatar_url": await discord_api.avatar_url_for(profile.player.discord_id),
        "stats": stats,
        "power": power,
        "rank": rank,
        "rank_tier": tier,
        "rank_tier_color": tier_color,
        "_equipped": equipped,
    }
    return ctx, profile


@router.get("/{player_id}/view", response_class=HTMLResponse)
async def players_view(
    player_id: int, request: Request,
    user: AdminUser = Depends(require_admin),
):
    """Carte principale : identité, 3 barres (PV/Mana/XP), stats + sous-cartes."""
    with get_db_session() as session:
        ctx, profile = await _base_ctx(session, user, player_id, "main")
        stats = ctx["stats"]
        equipped = ctx["_equipped"]

        # Barres de progression : PV / mana courants (état persisté) + XP.
        max_hp = stats.max_hp if stats else 1
        max_mana = stats.mana_max if stats else 0
        cur_hp = PlayerHealthRepository(session).get_or_create(player_id, max_hp).current_hp
        cur_mana = PlayerManaRepository(session).get_or_create(player_id, max_mana).current_mana
        xp_needed = ProgressionService().xp_required_for_next_level(profile.progression.level)

        ctx.update({
            "counts": {
                "inventory": len(InventoryRepository(session).list_by_player_id(player_id)),
                "equipment": len(equipped),
                "titles": len(PlayerTitleRepository(session).list_codes_for_player(player_id)),
            },
            "bars": {
                "hp": {"cur": cur_hp, "max": max_hp},
                "mana": {"cur": cur_mana, "max": max_mana},
                "xp": {"cur": profile.progression.xp, "max": xp_needed},
            },
        })
    return get_templates().TemplateResponse(request, "admin/players/card.html", context=ctx)


@router.get("/{player_id}/inventory", response_class=HTMLResponse)
async def players_inventory(player_id: int, request: Request, user: AdminUser = Depends(require_admin)):
    with get_db_session() as session:
        ctx, _ = await _base_ctx(session, user, player_id, "inventory")
        inv = InventoryRepository(session).list_by_player_id(player_id)
        ctx["inventory"] = sorted(
            [{"code": it.item_definition.code, "name": it.item_definition.name,
              "category": it.item_definition.category, "quantity": it.quantity} for it in inv],
            key=lambda x: (x["category"], x["code"]),
        )
    return get_templates().TemplateResponse(request, "admin/players/card.html", context=ctx)


@router.get("/{player_id}/equipment", response_class=HTMLResponse)
async def players_equipment(player_id: int, request: Request, user: AdminUser = Depends(require_admin)):
    with get_db_session() as session:
        ctx, _ = await _base_ctx(session, user, player_id, "equipment")
        eq = EquipmentRepository(session).list_by_player_id(player_id)
        ctx["equipment"] = sorted(
            [{"slot": e.slot, "code": e.item_definition.code, "name": e.item_definition.name,
              "family": e.item_definition.family or ""} for e in eq],
            key=lambda x: x["slot"],
        )
    return get_templates().TemplateResponse(request, "admin/players/card.html", context=ctx)


@router.get("/{player_id}/titles", response_class=HTMLResponse)
async def players_titles(player_id: int, request: Request, user: AdminUser = Depends(require_admin)):
    with get_db_session() as session:
        ctx, _ = await _base_ctx(session, user, player_id, "titles")
        repo = PlayerTitleRepository(session)
        codes = repo.list_codes_for_player(player_id)
        active = repo.get_active_title_code(player_id)
        titles = []
        for code in codes:
            d = title_loader.get_definition(code)
            titles.append({"code": code, "name": d.name if d else code, "active": code == active})
        ctx["titles"] = sorted(titles, key=lambda t: (not t["active"], t["name"]))
    return get_templates().TemplateResponse(request, "admin/players/card.html", context=ctx)


@router.get("/{player_id}/affinities", response_class=HTMLResponse)
async def players_affinities(player_id: int, request: Request, user: AdminUser = Depends(require_admin)):
    with get_db_session() as session:
        ctx, _ = await _base_ctx(session, user, player_id, "affinities")
        aff = ElementAffinityRepository(session).get_affinities(player_id)
        ess = ElementEssenceRepository(session).get_essences(player_id)
        ctx["affinities"] = [
            {"element": e.value, "emoji": ELEMENT_EMOJIS.get(e.value, ""),
             "label": ELEMENT_LABELS.get(e.value, e.value),
             "value": int(aff.get(e.value, 0)), "essences": int(ess.get(e.value, 0))}
            for e in ALL_ELEMENTS
        ]
    return get_templates().TemplateResponse(request, "admin/players/card.html", context=ctx)


@router.get("/{player_id}/skills", response_class=HTMLResponse)
async def players_skills(player_id: int, request: Request, user: AdminUser = Depends(require_admin)):
    with get_db_session() as session:
        ctx, profile = await _base_ctx(session, user, player_id, "skills")
        slots = []
        for i, code in enumerate((profile.player.skill_slot_1, profile.player.skill_slot_2), start=1):
            sk = element_skill_loader.get_skill(code) if code else None
            slots.append({
                "slot": i, "code": code or None,
                "name": (sk.emoji + " " + code) if sk else None,
                "element": sk.element if sk else None, "role": sk.role if sk else None,
            })
        ctx["skills"] = slots
    return get_templates().TemplateResponse(request, "admin/players/card.html", context=ctx)


@router.get("/{player_id}/duel", response_class=HTMLResponse)
async def players_duel(player_id: int, request: Request, user: AdminUser = Depends(require_admin)):
    with get_db_session() as session:
        ctx, _ = await _base_ctx(session, user, player_id, "duel")
        dr = PlayerDuelRankRepository(session).get_by_player_id(player_id)
        ctx["duel"] = None if dr is None else {
            "rank_position": dr.rank_position, "wins": dr.wins, "losses": dr.losses,
        }
    return get_templates().TemplateResponse(request, "admin/players/card.html", context=ctx)


@router.get("/{player_id}/career", response_class=HTMLResponse)
async def players_career(player_id: int, request: Request, user: AdminUser = Depends(require_admin)):
    with get_db_session() as session:
        ctx, _ = await _base_ctx(session, user, player_id, "career")
        ctx["career"] = PlayerCareerStatsRepository(session).get_or_create(player_id)
        ctx["total_kills"] = PlayerKillRepository(session).get_total_kills(player_id)
    return get_templates().TemplateResponse(request, "admin/players/card.html", context=ctx)


@router.post("/{player_id}/reset")
async def players_reset(player_id: int, user: AdminUser = Depends(require_admin)):
    with get_db_session() as session:
        profile = PlayerRepository(session).get_profile_by_player_id(player_id)
        if profile is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Player #{player_id} introuvable.")
        ResetPlayerUseCase().execute(session, player_id)
        _logger.info("Admin %s reset player %s (%s)", user.discord_id, player_id, profile.player.display_name)
    return RedirectResponse(f"/admin/players/{player_id}/view", status_code=303)


@router.get("/{player_id}/edit", response_class=HTMLResponse)
async def players_edit_form(player_id: int, request: Request, user: AdminUser = Depends(require_admin)):
    with get_db_session() as session:
        profile = PlayerRepository(session).get_profile_by_player_id(player_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Player #{player_id} introuvable.")
    return get_templates().TemplateResponse(
        request, "admin/players/form.html",
        context={"user": user, "profile": profile},
    )


@router.post("/{player_id}")
async def players_update(player_id: int, request: Request, user: AdminUser = Depends(require_admin)):
    form = await request.form()
    with get_db_session() as session:
        repo = PlayerRepository(session)
        profile = repo.get_profile_by_player_id(player_id)
        if profile is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Player #{player_id} introuvable.")

        def _i(key, default):
            try:
                return int(str(form.get(key, default)).strip())
            except (ValueError, TypeError):
                return default

        new_level = max(1, _i("level", profile.progression.level))
        new_xp = max(0, _i("xp", profile.progression.xp))
        new_sp = max(0, _i("skill_points", profile.progression.skill_points))
        new_gold = max(0, _i("gold", profile.resources.gold))
        new_streak = max(0, _i("daily_streak", profile.resources.daily_streak))

        repo.apply_progression(
            player_id=player_id, new_level=new_level, new_xp=new_xp, new_skill_points=new_sp,
        )
        repo.set_gold(player_id, new_gold)
        repo.set_daily_streak(player_id, new_streak)
        _logger.info("Admin %s edited player %s : lvl=%s xp=%s sp=%s gold=%s streak=%s",
                     user.discord_id, player_id, new_level, new_xp, new_sp, new_gold, new_streak)
    return RedirectResponse(f"/admin/players/{player_id}/view", status_code=303)
