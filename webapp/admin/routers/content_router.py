"""Routes admin read-only pour le contenu JSON-backed (classes, skill tree,
panoplies, titres, quêtes, world bosses) + le DB-backed read-only (crafts).

V1 : pas d'édition depuis le web — le contenu vit dans
`app/infrastructure/content/*.json` et passe par le seeder. Cette interface
sert à consulter rapidement ce qui est en jeu.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.session import get_db_session
from webapp.admin.auth import AdminUser, require_admin


_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin-content"])

CONTENT_DIR = Path(__file__).resolve().parents[3] / "app" / "infrastructure" / "content"


def get_templates():
    from webapp.main import templates
    return templates


def _load_json(filename: str):
    path = CONTENT_DIR / filename
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _filter_rows(rows: list[dict], q: str | None, extra_filters: dict | None = None) -> list[dict]:
    """Filtre client : q matche en sous-chaîne dans toutes les valeurs string ;
    extra_filters[k] doit matcher exactement row[k] si défini."""
    out = rows
    if q:
        ql = q.lower()
        out = [
            r for r in out
            if any(ql in str(v).lower() for v in r.values() if v is not None)
        ]
    for k, v in (extra_filters or {}).items():
        if v:
            out = [r for r in out if str(r.get(k, "")) == str(v)]
    return out


def _render(request: Request, user: AdminUser, **ctx) -> HTMLResponse:
    return get_templates().TemplateResponse(
        request, "admin/_generic_list.html",
        context={"user": user, **ctx},
    )


# ============ Classes ============
@router.get("/classes", response_class=HTMLResponse)
async def classes_list(
    request: Request,
    user: AdminUser = Depends(require_admin),
    q: str | None = None,
):
    data = _load_json("classes.json") or []
    rows = [
        {
            "code": c.get("code", ""),
            "name": c.get("name", ""),
            "description": c.get("description", "")[:80],
            "bonuses": ", ".join(f"{k}+{v}" for k, v in (c.get("stat_bonuses") or {}).items()),
            "unlock": ", ".join(
                f"{r.get('profession_code', r.get('type', '?'))} lvl {r.get('level', '?')}"
                for r in (c.get("unlock_requirements") or [])
            ) or "—",
        }
        for c in data
    ]
    filtered = _filter_rows(rows, q)
    return _render(
        request, user,
        title="Classes", icon="🧬",
        source_label="Définitions : app/infrastructure/content/classes.json",
        filter_q=q or "",
        columns=[
            {"label": "Code", "key": "code"},
            {"label": "Nom", "key": "name"},
            {"label": "Description", "key": "description"},
            {"label": "Bonus de stats", "key": "bonuses"},
            {"label": "Déblocage", "key": "unlock"},
        ],
        rows=filtered,
    )


# ============ Crafts (DB) ============
@router.get("/crafts", response_class=HTMLResponse)
async def crafts_list(
    request: Request,
    user: AdminUser = Depends(require_admin),
    q: str | None = None,
    station: str | None = None,
):
    from app.infrastructure.db.models.craft_model import (
        CraftRecipeModel,
        CraftRecipeIngredientModel,
    )
    from app.infrastructure.db.models.item_model import ItemDefinitionModel
    from sqlalchemy import select

    rows = []
    stations: set[str] = set()
    with get_db_session() as session:
        # Charge les items pour le mapping result_id → name
        items = {it.id: it for it in session.execute(select(ItemDefinitionModel)).scalars().all()}
        recipes = session.execute(select(CraftRecipeModel)).scalars().all()
        # Charge tous les ingredients groupés par recipe_id
        ingredients_by_recipe: dict[int, list[CraftRecipeIngredientModel]] = {}
        for ing in session.execute(select(CraftRecipeIngredientModel)).scalars().all():
            ingredients_by_recipe.setdefault(ing.craft_recipe_id, []).append(ing)

        for r in recipes:
            result_item = items.get(r.result_item_definition_id)
            result_cat = result_item.category if result_item else ""
            # Inférer la station à partir de la catégorie du résultat (cohérent
            # avec FORGE_CATEGORIES). Pas stocké en DB.
            from app.shared.enums import FORGE_CATEGORIES
            st = "forge" if result_cat in FORGE_CATEGORIES else "craft"
            stations.add(st)
            ings = ingredients_by_recipe.get(r.id, [])
            ing_str = ", ".join(
                f"{items.get(i.item_definition_id).name if items.get(i.item_definition_id) else '?'}×{i.quantity}"
                for i in ings
            )
            rows.append({
                "code": r.code,
                "name": r.name,
                "result": result_item.name if result_item else "?",
                "result_qty": r.result_quantity,
                "station": st,
                "ingredients": ing_str,
            })

    filtered = _filter_rows(rows, q, {"station": station})
    return _render(
        request, user,
        title="Recettes", icon="🛠️",
        source_label="Stockées en DB (craft_recipes). Source : app/infrastructure/content/crafts.json (seed).",
        filter_q=q or "",
        filter_groups=[{
            "name": "station",
            "current": station or "",
            "placeholder": "Toutes stations",
            "options": [(s, s) for s in sorted(stations)],
        }],
        columns=[
            {"label": "Code", "key": "code"},
            {"label": "Nom", "key": "name"},
            {"label": "Résultat", "key": "result"},
            {"label": "Qté", "key": "result_qty"},
            {"label": "Station", "key": "station"},
            {"label": "Ingrédients", "key": "ingredients"},
        ],
        rows=filtered,
    )


# ============ Skill Tree ============
@router.get("/skill-tree", response_class=HTMLResponse)
async def skill_tree_list(
    request: Request,
    user: AdminUser = Depends(require_admin),
    q: str | None = None,
):
    data = _load_json("skill_tree.json") or {}
    skills = data.get("skills", {})
    rows = []
    for code, node in skills.items():
        effects_str = ", ".join(
            f"{e.get('type')}={e.get('values')}"
            for e in (node.get("effects") or [])
        )
        rows.append({
            "code": code,
            "name": node.get("name", ""),
            "icon": node.get("icon", ""),
            "max_level": node.get("max_level", 1),
            "costs": ",".join(str(c) for c in (node.get("costs") or [])),
            "prereqs": ", ".join(node.get("prerequisites") or []) or "—",
            "effects": effects_str or "—",
        })
    filtered = _filter_rows(rows, q)
    return _render(
        request, user,
        title="Skill Tree", icon="🌳",
        source_label=f"Définitions : app/infrastructure/content/skill_tree.json (root = {data.get('root', '?')})",
        filter_q=q or "",
        columns=[
            {"label": "Icon", "key": "icon"},
            {"label": "Code", "key": "code"},
            {"label": "Nom", "key": "name"},
            {"label": "Max", "key": "max_level"},
            {"label": "Coûts", "key": "costs"},
            {"label": "Prérequis", "key": "prereqs"},
            {"label": "Effets", "key": "effects"},
        ],
        rows=filtered,
    )


# ============ Panoplies ============
@router.get("/panoplies", response_class=HTMLResponse)
async def panoplies_list(
    request: Request,
    user: AdminUser = Depends(require_admin),
    q: str | None = None,
):
    data = _load_json("sets.json") or {}
    # sets.json contient un dict family → {tiers, name, description}
    # ou parfois une liste de codes. On gère les 2 formats.
    rows = []
    if isinstance(data, dict):
        for family, info in data.items():
            tiers_str = ""
            if isinstance(info, dict):
                tiers = info.get("tiers", {}) or info.get("bonuses", {})
                if isinstance(tiers, dict):
                    tiers_str = " | ".join(
                        f"{k}: {v}" if not isinstance(v, dict)
                        else f"{k}: " + ", ".join(f"{kk}+{vv}" for kk, vv in v.items())
                        for k, v in tiers.items()
                    )
            rows.append({
                "family": family,
                "name": info.get("name", family) if isinstance(info, dict) else family,
                "tiers": tiers_str or "—",
            })
    elif isinstance(data, list):
        for family in data:
            rows.append({"family": family, "name": family, "tiers": "—"})

    # Compte le nombre d'items par famille
    with get_db_session() as session:
        all_items = ItemRepository(session).list_all()
    item_count_by_family: dict[str, int] = {}
    for it in all_items:
        if it.family:
            item_count_by_family[it.family] = item_count_by_family.get(it.family, 0) + 1
    for r in rows:
        r["items_count"] = item_count_by_family.get(r["family"], 0)

    filtered = _filter_rows(rows, q)
    return _render(
        request, user,
        title="Panoplies", icon="🌸",
        source_label="Définitions : app/infrastructure/content/sets.json — pièces taggées via item.family",
        filter_q=q or "",
        columns=[
            {"label": "Famille", "key": "family"},
            {"label": "Nom", "key": "name"},
            {"label": "Items", "key": "items_count"},
            {"label": "Paliers / bonus", "key": "tiers"},
        ],
        rows=filtered,
    )


# ============ Titres ============
@router.get("/titles", response_class=HTMLResponse)
async def titles_list(
    request: Request,
    user: AdminUser = Depends(require_admin),
    q: str | None = None,
    condition_type: str | None = None,
):
    data = _load_json("titles.json") or []
    rows = []
    cond_types: set[str] = set()
    for t in data:
        ct = t.get("condition_type", "—")
        cond_types.add(ct)
        effects_str = ", ".join(
            f"{e.get('type')}={e.get('value', '?')}"
            for e in (t.get("effects") or [])
        )
        rows.append({
            "icon": t.get("icon", ""),
            "code": t.get("code", ""),
            "name": t.get("name", ""),
            "condition_type": ct,
            "condition_target": t.get("condition_target", "—") or "—",
            "condition_value": t.get("condition_value", "—"),
            "effects": effects_str or "—",
        })
    filtered = _filter_rows(rows, q, {"condition_type": condition_type})
    return _render(
        request, user,
        title="Titres", icon="🏷️",
        source_label="Définitions : app/infrastructure/content/titles.json",
        filter_q=q or "",
        filter_groups=[{
            "name": "condition_type",
            "current": condition_type or "",
            "placeholder": "Tous types de condition",
            "options": [(c, c) for c in sorted(cond_types)],
        }],
        columns=[
            {"label": "Icon", "key": "icon"},
            {"label": "Code", "key": "code"},
            {"label": "Nom", "key": "name"},
            {"label": "Condition", "key": "condition_type"},
            {"label": "Cible", "key": "condition_target"},
            {"label": "Seuil", "key": "condition_value"},
            {"label": "Effets", "key": "effects"},
        ],
        rows=filtered,
    )


# ============ Quêtes (daily + weekly) ============
def _quest_rows(filename: str):
    data = _load_json(filename) or []
    rows = []
    for q in data:
        items_str = ", ".join(
            f"{code}×{qty}" for code, qty in (q.get("reward_items") or [])
        ) or "—"
        rows.append({
            "code": q.get("code", ""),
            "name": q.get("name", ""),
            "tier": q.get("tier", "—"),
            "objective_type": q.get("objective_type", "—"),
            "objective_target": q.get("objective_target", "—") or "—",
            "objective_quantity": q.get("objective_quantity", 0),
            "reward_gold": q.get("reward_gold", 0),
            "reward_xp": q.get("reward_xp", 0),
            "reward_items": items_str,
        })
    return rows


@router.get("/quests", response_class=HTMLResponse)
async def quests_list(
    request: Request,
    user: AdminUser = Depends(require_admin),
    q: str | None = None,
    tier: str | None = None,
    scope: str = "daily",
):
    filename = "weekly_quests.json" if scope == "weekly" else "daily_quests.json"
    rows = _quest_rows(filename)
    tiers = sorted({r["tier"] for r in rows if r["tier"]})
    filtered = _filter_rows(rows, q, {"tier": tier})
    return _render(
        request, user,
        title=f"Quêtes — {'Hebdomadaires' if scope == 'weekly' else 'Quotidiennes'}",
        icon="📜",
        source_label=(
            f"Définitions : app/infrastructure/content/{filename} "
            f"— passer ?scope=weekly pour basculer."
        ),
        filter_q=q or "",
        filter_groups=[{
            "name": "tier",
            "current": tier or "",
            "placeholder": "Tous les tiers",
            "options": [(t, t) for t in tiers],
        }, {
            "name": "scope",
            "current": scope,
            "placeholder": "Type",
            "options": [("daily", "Quotidiennes"), ("weekly", "Hebdomadaires")],
        }],
        columns=[
            {"label": "Code", "key": "code"},
            {"label": "Nom", "key": "name"},
            {"label": "Tier", "key": "tier"},
            {"label": "Objectif", "key": "objective_type"},
            {"label": "Cible", "key": "objective_target"},
            {"label": "Qté", "key": "objective_quantity"},
            {"label": "Or", "key": "reward_gold"},
            {"label": "XP", "key": "reward_xp"},
            {"label": "Items", "key": "reward_items"},
        ],
        rows=filtered,
    )


# ============ World Bosses ============
@router.get("/world-bosses", response_class=HTMLResponse)
async def world_bosses_list(
    request: Request,
    user: AdminUser = Depends(require_admin),
    q: str | None = None,
    tier: str | None = None,
):
    data = _load_json("boss_definitions.json") or []
    rows = []
    tiers: set[str] = set()
    for b in data:
        if b.get("tier"):
            tiers.add(b["tier"])
        mods = b.get("modifiers") or {}
        mods_str = ", ".join(f"{k}={v}" for k, v in mods.items()) or "—"
        rows.append({
            "code": b.get("code", ""),
            "name": b.get("name", ""),
            "tier": b.get("tier", "—"),
            "max_hp": b.get("max_hp", 0),
            "attack": b.get("attack", 0),
            "defense": b.get("defense", 0),
            "speed": b.get("speed", 0),
            "spawn_weight": b.get("spawn_weight", 0),
            "modifiers": mods_str,
        })
    filtered = _filter_rows(rows, q, {"tier": tier})
    return _render(
        request, user,
        title="World Bosses", icon="🐉",
        source_label="Définitions : app/infrastructure/content/boss_definitions.json",
        filter_q=q or "",
        filter_groups=[{
            "name": "tier",
            "current": tier or "",
            "placeholder": "Tous les tiers",
            "options": [(t, t) for t in sorted(tiers)],
        }],
        columns=[
            {"label": "Code", "key": "code"},
            {"label": "Nom", "key": "name"},
            {"label": "Tier", "key": "tier"},
            {"label": "PV", "key": "max_hp"},
            {"label": "Atk", "key": "attack"},
            {"label": "Def", "key": "defense"},
            {"label": "Vit", "key": "speed"},
            {"label": "Poids", "key": "spawn_weight"},
            {"label": "Modifiers", "key": "modifiers"},
        ],
        rows=filtered,
    )
