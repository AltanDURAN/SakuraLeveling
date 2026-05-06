"""Application web FastAPI : visualisation de l'arbre de compétences.

Lecture seule : aucune modification possible depuis le navigateur. La logique
métier (déblocage, reset) reste exclusivement côté bot Discord.

Lancement local :
    .venv/bin/python -m webapp.main
    # → http://localhost:8000

Routes :
    GET /                          → page d'accueil minimaliste (instructions)
    GET /skill/<discord_id>        → page HTML interactive
    GET /api/skill/<discord_id>    → JSON brut (état + définition)
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
from app.bot.rendering.skill_tree_renderer import render_to_svg
from app.domain.services.power_score_service import PowerScoreService
from app.domain.services.skill_tree_service import SkillTreeService
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.db.session import get_db_session
from app.infrastructure.skill_tree.skill_tree_loader import (
    get_definition as get_skill_tree_definition,
)


WEBAPP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEBAPP_DIR / "templates"
STATIC_DIR = WEBAPP_DIR / "static"


_logger = logging.getLogger(__name__)


app = FastAPI(title="SakuraLeveling — Skill Tree Viewer")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


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


@app.get("/skill/{discord_id}", response_class=HTMLResponse)
async def skill_page(request: Request, discord_id: int):
    state, definition = _load_state_for_discord(discord_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"Aucun joueur trouvé pour le Discord ID {discord_id}.",
        )

    svg = render_to_svg(state, definition)
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
            prereq_level = state.allocations.get(prereq_code, 0)
            prereqs_with_state.append({
                "code": prereq_code,
                "name": prereq_node.name,
                "icon": prereq_node.icon,
                "current_level": prereq_level,
                "satisfied": prereq_level > 0,
            })

        nodes_payload.append(
            {
                "code": node.code,
                "name": node.name,
                "description": node.description,
                "icon": node.icon,
                "max_level": node.max_level,
                "current_level": state.allocations.get(node.code, 0),
                "state": service.compute_node_state(state.allocations, node.code),
                "costs": node.costs,
                "prerequisites": node.prerequisites,
                "prereqs_detail": prereqs_with_state,
                "effects": [
                    {"type": e.type, "values": e.values} for e in node.effects
                ],
            }
        )

    return templates.TemplateResponse(
        request,
        "skill_tree.html",
        context={
            "state": state,
            "svg": svg,
            "nodes": nodes_payload,
        },
    )


@app.get("/bestiary", response_class=HTMLResponse)
async def bestiary_page(request: Request):
    """Catalogue public des monstres du jeu."""
    pss = PowerScoreService()

    with get_db_session() as session:
        mobs = MobRepository(session).list_all()

    # Tri : famille puis PV décroissant pour avoir une lecture cohérente
    mobs_sorted = sorted(
        mobs, key=lambda m: (m.family or "zzz", -m.max_hp),
    )

    rendered_mobs = []
    for m in mobs_sorted:
        score = pss.calculate_from_mob(m)
        rendered_mobs.append({
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
            "xp_reward": m.xp_reward,
            "gold_reward": m.gold_reward,
            "loot_table": m.loot_table or [],
            "power_score": pss.format_score(score),
            "rank": pss.compute_rank(score),
        })

    return templates.TemplateResponse(
        request,
        "bestiary.html",
        context={"mobs": rendered_mobs},
    )


@app.get("/api/bestiary")
async def bestiary_api():
    pss = PowerScoreService()
    with get_db_session() as session:
        mobs = MobRepository(session).list_all()
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
                "current_level": state.allocations.get(node.code, 0),
                "state": service.compute_node_state(state.allocations, node.code),
            }
            for node in definition.skills.values()
        },
    }


def main() -> None:
    import uvicorn

    uvicorn.run("webapp.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
