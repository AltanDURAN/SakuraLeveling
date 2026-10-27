"""Application web FastAPI : visualisation de l'arbre de compétences.

Un joueur connecté avec Discord (OAuth, cookie joueur distinct de l'admin)
peut investir dans SON arbre ; tout le reste est en lecture seule. La logique
métier passe par les mêmes use cases que le bot.

Lancement local :
    .venv/bin/python -m webapp.main
    # → http://localhost:8000

Routes :
    GET /                          → page d'accueil minimaliste (instructions)
    GET /skill/<discord_id>        → page HTML interactive
    GET /api/skill/<discord_id>    → JSON brut (état + définition)
    POST /api/skill/<id>/invest    → +1 niveau (joueur connecté, son arbre)
    GET /skill/login, /skill/logout → connexion Discord du joueur
    GET /static/*                  → CSS/JS
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.application.use_cases.get_skill_tree_state import GetSkillTreeStateUseCase
from app.application.use_cases.invest_skill_point import InvestSkillPointUseCase
from app.domain.services.skill_effect_text import effect_lines, mana_lines
from app.bot.rendering.skill_tree_renderer import render_to_svg
from app.domain.services.power_score_service import PowerScoreService
from app.domain.services.skill_tree_service import SkillTreeService
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.encounters.farm_zone_loader import unreleased_families
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.db.session import get_db_session
from app.infrastructure.skill_tree.skill_tree_loader import (
    get_definition as get_skill_tree_definition,
)
from webapp.admin.routers.actions_router import router as admin_actions_router
from webapp.admin.routers.auth_router import router as admin_auth_router
from webapp.admin.routers.titles_router import router as admin_titles_router
from webapp.admin.routers.quests_router import router as admin_quests_router
from webapp.admin.routers.world_bosses_router import router as admin_world_bosses_router
from webapp.admin.routers.offering_router import router as admin_offering_router
from webapp.admin.routers.pacing_router import router as admin_pacing_router
from webapp.admin.routers.skill_builder_router import (
    router as admin_skill_builder_router,
)
from webapp.admin.routers.dashboard_router import router as admin_dashboard_router
from webapp.admin.routers.items_router import router as admin_items_router
from webapp.admin.routers.mobs_router import router as admin_mobs_router
from webapp.admin.routers.players_router import router as admin_players_router
from webapp.admin.routers.roles_router import router as admin_roles_router
from webapp.admin.routers.shop_router import router as admin_shop_router
from webapp.admin.routers.zones_router import router as admin_zones_router
from webapp.admin.routers.scenes_router import router as admin_scenes_router
from webapp.admin.routers.families_router import router as admin_families_router
from webapp.admin.routers.events_router import router as admin_events_router
from webapp.admin.routers.image_gen_router import router as admin_image_gen_router
from webapp.player_auth import current_player, router as player_auth_router


WEBAPP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEBAPP_DIR / "templates"
STATIC_DIR = WEBAPP_DIR / "static"


_logger = logging.getLogger(__name__)


from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Refuse de servir la moindre requête tant que le secret de cookie admin
    est resté au défaut public — sinon n'importe qui forge un cookie admin."""
    settings.assert_safe_admin_secret()
    yield


# Pas de /docs, /redoc ni /openapi.json : le site est PUBLIC, et ces pages
# publiaient la carte des ~110 routes d'administration (audit du 24/10/2026).
app = FastAPI(title="SakuraLeveling — Skill Tree Viewer", lifespan=_lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)

# Protection CSRF (vérification d'origine) sur les routes /admin mutantes.
from webapp.admin.csrf import csrf_origin_middleware
app.middleware("http")(csrf_origin_middleware)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
# Sert les assets du jeu (images de mobs, décors) pour les aperçus admin.
from app.shared.paths import ASSETS_DIR as _ASSETS_DIR  # noqa: E402
_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/assets", StaticFiles(directory=str(_ASSETS_DIR)), name="assets")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Routers admin — montés avant les routes publiques pour que /admin/* matche
# en priorité (sinon /admin/{slug} du dashboard router gobble nos sous-routes).
# L'ordre des inclusions compte : auth → items → mobs → dashboard (fallback).
app.include_router(admin_auth_router)
app.include_router(player_auth_router)
app.include_router(admin_items_router)
app.include_router(admin_mobs_router)
app.include_router(admin_zones_router)
app.include_router(admin_scenes_router)
app.include_router(admin_families_router)
app.include_router(admin_shop_router)
app.include_router(admin_players_router)
app.include_router(admin_roles_router)
app.include_router(admin_actions_router)
app.include_router(admin_events_router)
app.include_router(admin_image_gen_router)
app.include_router(admin_skill_builder_router)
app.include_router(admin_titles_router)
app.include_router(admin_quests_router)
app.include_router(admin_world_bosses_router)
app.include_router(admin_offering_router)
app.include_router(admin_pacing_router)
app.include_router(admin_dashboard_router)


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    """Handler global : log la stack trace et renvoie une réponse propre.

    Évite d'exposer la stack trace brute aux navigateurs en cas d'erreur 500.
    """
    _logger.exception("Erreur non gérée sur %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Erreur interne du serveur. Réessayez plus tard.",
        },
    )


def _load_state_for_discord(discord_id: int):
    definition = get_skill_tree_definition()
    with get_db_session() as session:
        use_case = GetSkillTreeStateUseCase(
            player_repository=PlayerRepository(session),
            skill_allocation_repository=PlayerSkillAllocationRepository(session),
            cooldown_repository=CooldownRepository(session),
            skill_tree_definition=definition,
        )
        state = use_case.execute(discord_id)
    return state, definition


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


def _nodes_payload(state, definition) -> list[dict]:
    """Cases de l'arbre pour la page (tooltip, état, coût, prérequis)."""
    service = SkillTreeService(definition)
    nodes_payload = []
    for node in definition.skills.values():
        # Pour chaque prérequis, on enrichit avec son nom + niveau courant
        # afin que le tooltip puisse afficher "Prérequis : <X> ✅/❌".
        prereqs_with_state = []
        for prereq_code in node.prerequisites:
            prereq_node = definition.get(prereq_code)
            if prereq_node is None:
                continue
            # Une case de départ est acquise d'office ; un prérequis n'est
            # rempli qu'au niveau MAXIMUM (règle du moteur).
            prereq_level = (
                prereq_node.max_level if prereq_node.start
                else state.allocations.get(prereq_code, 0)
            )
            prereqs_with_state.append({
                "code": prereq_code,
                "name": prereq_node.name,
                "icon": prereq_node.icon,
                "current_level": prereq_level,
                "max_level": prereq_node.max_level,
                "satisfied": prereq_level >= prereq_node.max_level,
            })

        nodes_payload.append(
            {
                "code": node.code,
                "name": node.name,
                "description": node.description,
                "icon": node.icon,
                "max_level": node.max_level,
                "start": bool(node.start),
                "current_level": (
                    node.max_level if node.start else state.allocations.get(node.code, 0)
                ),
                "unlock_rule": node.unlock_rule,
                # Ce que donne la case, lisible (« +1 % d'attaque »).
                "effects_text": effect_lines(node) + mana_lines(node),
                "state": service.compute_node_state(state.allocations, node.code),
                "costs": node.costs,
                "prerequisites": node.prerequisites,
                "prereqs_detail": prereqs_with_state,
                # Règle de spécialisation qui ferme encore la case (seuil de
                # voie, exclusivité) — None si aucune.
                "rule_lock": service.rule_lock(state.allocations, node),
                "effects": [
                    {"type": e.type, "values": e.values} for e in node.effects
                ],
            }
        )
    return nodes_payload


def _render_tree(state, definition) -> str:
    # Web : vue d'ensemble du triskèle complet (la page est zoomable/pannable),
    # contrairement à l'image Discord qui est cadrée sur la zone d'action.
    return render_to_svg(state, definition, focus=False, header=False)


@app.get("/skill/{discord_id}", response_class=HTMLResponse)
async def skill_page(request: Request, discord_id: int):
    state, definition = _load_state_for_discord(discord_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"Aucun joueur trouvé pour le Discord ID {discord_id}.",
        )

    viewer = current_player(request)
    return templates.TemplateResponse(
        request,
        "skill_tree.html",
        context={
            "state": state,
            "svg": _render_tree(state, definition),
            "nodes": _nodes_payload(state, definition),
            "page": {
                "discord_id": str(discord_id),
                "logged_in": viewer is not None,
                "viewer_name": viewer.display_name if viewer else "",
                "viewer_id": str(viewer.discord_id) if viewer else "",
                "is_owner": viewer is not None and viewer.discord_id == discord_id,
                "available_points": state.available_points,
                "login_url": f"/skill/login?next=/skill/{discord_id}",
                "logout_url": f"/skill/logout?next=/skill/{discord_id}",
            },
        },
    )


@app.post("/api/skill/{discord_id}/invest")
async def skill_invest(request: Request, discord_id: int):
    """Investit +1 niveau depuis le web — même use case que le bouton Discord.

    Réservé au joueur connecté (OAuth Discord) et à SON arbre uniquement.
    """
    viewer = current_player(request)
    if viewer is None:
        return JSONResponse(
            status_code=401,
            content={"ok": False, "message": "Connecte-toi avec Discord pour investir."},
        )
    if viewer.discord_id != discord_id:
        return JSONResponse(
            status_code=403,
            content={"ok": False, "message": "Tu ne peux investir que dans ton propre arbre."},
        )
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    code = str((body or {}).get("code", ""))[:100]

    definition = get_skill_tree_definition()
    with get_db_session() as session:
        result = InvestSkillPointUseCase(
            player_repository=PlayerRepository(session),
            skill_allocation_repository=PlayerSkillAllocationRepository(session),
            skill_tree_definition=definition,
        ).execute(discord_id, code)

    state, definition = _load_state_for_discord(discord_id)
    payload = {
        "ok": result.success,
        # Le message du bot est en Markdown Discord (**gras**) : on l'aplatit.
        "message": result.message.replace("**", ""),
    }
    if state is not None:
        payload.update(
            svg=_render_tree(state, definition),
            nodes=_nodes_payload(state, definition),
            available_points=state.available_points,
            spent_points=state.spent_points,
        )
    return JSONResponse(status_code=200 if result.success else 400, content=payload)


@app.get("/bestiary", response_class=HTMLResponse)
async def bestiary_page(request: Request):
    """Catalogue public des monstres du jeu."""
    from app.infrastructure.db.repositories.item_repository import ItemRepository
    from app.domain.services.adventurers_guild import specialties_revealed
    from app.domain.services.mob_ability_service import get_mob_ability_summary

    pss = PowerScoreService()
    reveal = specialties_revealed()

    with get_db_session() as session:
        hidden = unreleased_families()  # zones pas encore ouvertes
        mobs = [m for m in MobRepository(session).list_all() if m.family not in hidden]
        # Lookup table code → name pour résoudre les drops en nom lisible.
        items_by_code = {it.code: it.name for it in ItemRepository(session).list_all()}

    rendered_mobs = []
    for m in mobs:
        score = pss.calculate_from_mob(m)
        loot_resolved = [
            {**entry, "item_name": items_by_code.get(entry.get("item_code", ""), entry.get("item_code", ""))}
            for entry in (m.loot_table or [])
        ]
        summary = get_mob_ability_summary(m.code)
        specialty = None
        if summary:
            specialty = summary if reveal else "???"
        rendered_mobs.append({
            "code": m.code,
            "name": m.name,
            "family": m.family,
            "description": m.description,
            "specialty": specialty,
            "specialty_hidden": bool(summary) and not reveal,
            "max_hp": m.max_hp,
            "attack": m.attack,
            "defense": m.defense,
            "speed": m.speed,
            "crit_chance": m.crit_chance,
            "crit_damage": m.crit_damage,
            "dodge": m.dodge,
            "xp_reward": m.xp_reward,
            "gold_reward": m.gold_reward,
            "loot_table": loot_resolved,
            "power_score_raw": score,
            "power_score": pss.format_score(score),
            "rank": pss.compute_rank(score),
        })

    # Tri par power score décroissant (du plus fort au plus faible).
    # Tri par score de puissance CROISSANT (du plus faible au plus fort).
    rendered_mobs.sort(key=lambda r: r["power_score_raw"])

    return templates.TemplateResponse(
        request,
        "bestiary.html",
        context={"mobs": rendered_mobs},
    )


@app.get("/api/bestiary")
async def bestiary_api():
    pss = PowerScoreService()
    with get_db_session() as session:
        hidden = unreleased_families()  # zones pas encore ouvertes
        mobs = [m for m in MobRepository(session).list_all() if m.family not in hidden]
    return {
        "mobs": [
            {
                "code": m.code,
                "name": m.name,
                "family": m.family,
                "description": m.description,
                "max_hp": m.max_hp,
                "attack": m.attack,
                "defense": m.defense,
                "speed": m.speed,
                "crit_chance": m.crit_chance,
                "crit_damage": m.crit_damage,
                "dodge": m.dodge,
                "hp_regeneration": m.hp_regeneration,
                "xp_reward": m.xp_reward,
                "gold_reward": m.gold_reward,
                "spawn_weight": m.spawn_weight,
                "loot_table": m.loot_table,
                "power_score": pss.calculate_from_mob(m),
                "rank": pss.compute_rank(pss.calculate_from_mob(m)),
            }
            for m in mobs
        ]
    }


@app.get("/api/skill/{discord_id}")
async def skill_api(discord_id: int):
    state, definition = _load_state_for_discord(discord_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"Aucun joueur trouvé pour le Discord ID {discord_id}.",
        )

    service = SkillTreeService(definition)
    return {
        "player": {
            "discord_id": state.discord_id,
            "display_name": state.player_display_name,
            "available_points": state.available_points,
            "spent_points": state.spent_points,
            "next_reset_available_at": (
                state.next_reset_available_at.isoformat()
                if state.next_reset_available_at
                else None
            ),
        },
        "allocations": state.allocations,
        "skills": {
            node.code: {
                "name": node.name,
                "description": node.description,
                "icon": node.icon,
                "max_level": node.max_level,
                "costs": node.costs,
                "effects": [asdict(e) for e in node.effects],
                "prerequisites": node.prerequisites,
                "position": {"x": node.position.x, "y": node.position.y},
                "current_level": (
                    node.max_level if node.start else state.allocations.get(node.code, 0)
                ),
                "unlock_rule": node.unlock_rule,
                # Ce que donne la case, lisible (« +1 % d'attaque »).
                "effects_text": effect_lines(node) + mana_lines(node),
                "state": service.compute_node_state(state.allocations, node.code),
            }
            for node in definition.skills.values()
        },
    }


def main() -> None:
    import uvicorn
    import os

    # Port configurable via env (WEBAPP_PORT). Default 8001 pour cohérence
    # avec OAUTH_REDIRECT_URI=.../localhost:8001/admin/auth/callback.
    port = int(os.environ.get("WEBAPP_PORT", "8001"))
    # 0.0.0.0 pour permettre l'accès depuis l'IP publique du VPS.
    host = os.environ.get("WEBAPP_HOST", "0.0.0.0")
    uvicorn.run("webapp.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
