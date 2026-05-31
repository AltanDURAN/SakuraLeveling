"""Routes admin pour le contenu JSON-backed (classes, skill tree, panoplies,
titres, quêtes, world bosses) + le DB-backed (crafts).

Listings : read complet via filtres + tri.
Création : ajout d'une entrée via form, écriture atomique dans le JSON.
Édition / suppression : non implémentées en V1 (le contenu peut toujours
être édité à la main dans `app/infrastructure/content/`).

⚠️ Les loaders de contenu (skill_tree_loader, title_loader, …) cachent le
JSON en mémoire au démarrage. Le bot Discord doit être redémarré pour voir
les nouvelles entrées. Le webapp les voit immédiatement (relit à chaque
requête).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Request, status, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.session import get_db_session
from webapp.admin.auth import AdminUser, require_admin
from webapp.admin.json_writer import (
    add_skill_node,
    append_to_list,
    load_json as _writer_load,
    upsert_to_dict,
)


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


def _parse_int(raw, default=0):
    if raw is None:
        return default
    raw = str(raw).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _parse_kv_pairs(raw: str) -> dict[str, int]:
    """Parse 'max_hp=20, attack=3' → {'max_hp': 20, 'attack': 3}."""
    out: dict[str, int] = {}
    if not raw:
        return out
    for chunk in raw.replace(";", ",").split(","):
        if "=" not in chunk:
            continue
        k, v = chunk.split("=", 1)
        k = k.strip()
        try:
            out[k] = int(v.strip())
        except ValueError:
            try:
                out[k] = float(v.strip())
            except ValueError:
                continue
    return out


def _parse_csv(raw: str) -> list[str]:
    """Parse 'a, b , c' → ['a', 'b', 'c']."""
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _parse_int_list(raw: str) -> list[int]:
    """Parse '1, 2, 3, 5' → [1, 2, 3, 5]."""
    out = []
    for x in _parse_csv(raw):
        try:
            out.append(int(x))
        except ValueError:
            pass
    return out


def _parse_unlock_requirements(raw: str) -> list[dict]:
    """Parse le champ 'unlock' libre admin → liste de requirements typés.

    Format attendu : 'profession_level:mining:2, level:5'. Avant cette
    factorisation, classes_create et classes_update faisaient `int(parts[N])`
    sans try/except → HTTP 500 brut sur faute de frappe (cf. audit B7).
    Désormais : un chunk mal formé est SILENCIEUSEMENT ignoré (au lieu de
    crasher la requête), comme les autres parseurs du module.
    """
    out: list[dict] = []
    raw = (raw or "").strip()
    if not raw:
        return out
    for chunk in raw.split(","):
        parts = [p.strip() for p in chunk.split(":")]
        try:
            if parts[0] == "profession_level" and len(parts) == 3:
                out.append({
                    "type": "profession_level",
                    "profession_code": parts[1],
                    "level": int(parts[2]),
                })
            elif parts[0] == "level" and len(parts) == 2:
                out.append({"type": "level", "level": int(parts[1])})
        except (ValueError, IndexError):
            continue
    return out


def _parse_reward_items(raw: str) -> list[list]:
    """Parse 'potion_soin_i:1, gold_coin:5' → [['potion_soin_i', 1], ['gold_coin', 5]]."""
    out = []
    if not raw:
        return out
    for chunk in raw.replace(";", ",").split(","):
        if ":" not in chunk:
            continue
        code, qty = chunk.split(":", 1)
        try:
            out.append([code.strip(), int(qty.strip())])
        except ValueError:
            continue
    return out


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
            "__edit_url__": f"/admin/classes/{c.get('code', '')}/edit",
        }
        for c in data
    ]
    filtered = _filter_rows(rows, q)
    return _render(
        request, user,
        title="Classes", icon="🧬",
        new_url="/admin/classes/new", new_label="Nouvelle classe",
        source_label="Définitions : app/infrastructure/content/classes.json — ⚠️ restart bot requis après ajout",
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
                "__edit_url__": f"/admin/crafts/{r.code}/edit",
            })

    filtered = _filter_rows(rows, q, {"station": station})
    return _render(
        request, user,
        title="Recettes", icon="🛠️",
        new_url="/admin/crafts/new", new_label="Nouvelle recette",
        source_label="Stockées en DB (craft_recipes). Édition directe — pas de restart bot.",
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
            "__edit_url__": f"/admin/skill-tree/{code}/edit",
        })
    filtered = _filter_rows(rows, q)
    return _render(
        request, user,
        title="Skill Tree", icon="🌳",
        new_url="/admin/skill-tree/new", new_label="Nouveau skill",
        source_label=f"Définitions : app/infrastructure/content/skill_tree.json (root = {data.get('root', '?')}) — ⚠️ restart bot requis après ajout",
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
                "__edit_url__": f"/admin/panoplies/{family}/edit",
            })
    elif isinstance(data, list):
        for family in data:
            rows.append({
                "family": family, "name": family, "tiers": "—",
                "__edit_url__": f"/admin/panoplies/{family}/edit",
            })

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
        new_url="/admin/panoplies/new", new_label="Nouvelle panoplie",
        source_label="Définitions : app/infrastructure/content/sets.json — pièces taggées via item.family — ⚠️ restart bot requis",
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
            "__edit_url__": f"/admin/titles/{t.get('code', '')}/edit",
        })
    filtered = _filter_rows(rows, q, {"condition_type": condition_type})
    return _render(
        request, user,
        title="Titres", icon="🏷️",
        new_url="/admin/titles/new", new_label="Nouveau titre",
        source_label="Définitions : app/infrastructure/content/titles.json — ⚠️ restart bot requis après ajout",
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
def _quest_rows(filename: str, scope: str):
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
            "__edit_url__": f"/admin/quests/{scope}/{q.get('code', '')}/edit",
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
    rows = _quest_rows(filename, scope)
    tiers = sorted({r["tier"] for r in rows if r["tier"]})
    filtered = _filter_rows(rows, q, {"tier": tier})
    return _render(
        request, user,
        title=f"Quêtes — {'Hebdomadaires' if scope == 'weekly' else 'Quotidiennes'}",
        icon="📜",
        new_url=f"/admin/quests/new?scope={scope}",
        new_label=f"Nouvelle quête {'hebdo' if scope == 'weekly' else 'quotidienne'}",
        source_label=(
            f"Définitions : app/infrastructure/content/{filename} "
            f"— ⚠️ restart bot requis après ajout."
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
            "__edit_url__": f"/admin/world-bosses/{b.get('code', '')}/edit",
        })
    filtered = _filter_rows(rows, q, {"tier": tier})
    return _render(
        request, user,
        title="World Bosses", icon="🐉",
        new_url="/admin/world-bosses/new", new_label="Nouveau boss",
        source_label="Définitions : app/infrastructure/content/boss_definitions.json — ⚠️ restart bot requis",
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


# ============ Create forms ============

# --- Classes ---
@router.get("/classes/new", response_class=HTMLResponse)
async def classes_new_form(request: Request, user: AdminUser = Depends(require_admin)):
    return get_templates().TemplateResponse(
        request, "admin/classes/form.html",
        context={"user": user, "errors": {}, "form_data": {}},
    )


@router.post("/classes")
async def classes_create(request: Request, user: AdminUser = Depends(require_admin)):
    fd = {k: str(v) for k, v in (await request.form()).items()}
    errors = {}
    code = fd.get("code", "").strip()
    name = fd.get("name", "").strip()
    if not code:
        errors["code"] = "Code requis."
    if not name:
        errors["name"] = "Nom requis."
    existing = _writer_load("classes.json", default=[]) or []
    if any(c.get("code") == code for c in existing):
        errors["code"] = f"Code `{code}` existe déjà."
    if errors:
        return get_templates().TemplateResponse(
            request, "admin/classes/form.html",
            context={"user": user, "errors": errors, "form_data": fd},
            status_code=400,
        )
    entry = {
        "code": code,
        "name": name,
        "description": fd.get("description", "").strip(),
        "stat_bonuses": _parse_kv_pairs(fd.get("stat_bonuses", "")),
    }
    entry["unlock_requirements"] = _parse_unlock_requirements(fd.get("unlock", ""))
    append_to_list("classes.json", entry)
    return RedirectResponse(f"/admin/classes?q={code}", status_code=303)


# --- Titres ---
@router.get("/titles/new", response_class=HTMLResponse)
async def titles_new_form(request: Request, user: AdminUser = Depends(require_admin)):
    return get_templates().TemplateResponse(
        request, "admin/titles/form.html",
        context={"user": user, "errors": {}, "form_data": {}},
    )


@router.post("/titles")
async def titles_create(request: Request, user: AdminUser = Depends(require_admin)):
    fd = {k: str(v) for k, v in (await request.form()).items()}
    errors = {}
    code = fd.get("code", "").strip()
    name = fd.get("name", "").strip()
    if not code:
        errors["code"] = "Code requis."
    if not name:
        errors["name"] = "Nom requis."
    existing = _writer_load("titles.json", default=[]) or []
    if any(t.get("code") == code for t in existing):
        errors["code"] = f"Code `{code}` existe déjà."
    if errors:
        return get_templates().TemplateResponse(
            request, "admin/titles/form.html",
            context={"user": user, "errors": errors, "form_data": fd},
            status_code=400,
        )
    # effects format : "type:target:value, type::value"
    effects = []
    for chunk in fd.get("effects", "").split(","):
        parts = [p.strip() for p in chunk.split(":")]
        if len(parts) == 3 and parts[0]:
            try:
                value = int(parts[2]) if parts[2] else 0
            except ValueError:
                value = parts[2]
            effects.append({"type": parts[0], "target": parts[1] or None, "value": value})
        elif len(parts) == 2 and parts[0]:
            try:
                value = int(parts[1]) if parts[1] else 0
            except ValueError:
                value = parts[1]
            effects.append({"type": parts[0], "value": value})
    entry = {
        "code": code,
        "name": name,
        "description": fd.get("description", "").strip(),
        "icon": fd.get("icon", "").strip(),
        "condition_type": fd.get("condition_type", "").strip(),
        "condition_target": fd.get("condition_target", "").strip() or None,
        "condition_value": _parse_int(fd.get("condition_value"), 0),
        "effects": effects,
    }
    append_to_list("titles.json", entry)
    return RedirectResponse(f"/admin/titles?q={code}", status_code=303)


# --- Quêtes (daily + weekly) ---
@router.get("/quests/new", response_class=HTMLResponse)
async def quests_new_form(
    request: Request, user: AdminUser = Depends(require_admin),
    scope: str = "daily",
):
    return get_templates().TemplateResponse(
        request, "admin/quests/form.html",
        context={"user": user, "errors": {}, "form_data": {}, "scope": scope},
    )


@router.post("/quests")
async def quests_create(request: Request, user: AdminUser = Depends(require_admin)):
    fd = {k: str(v) for k, v in (await request.form()).items()}
    scope = fd.get("scope", "daily")
    filename = "weekly_quests.json" if scope == "weekly" else "daily_quests.json"
    errors = {}
    code = fd.get("code", "").strip()
    name = fd.get("name", "").strip()
    if not code:
        errors["code"] = "Code requis."
    if not name:
        errors["name"] = "Nom requis."
    existing = _writer_load(filename, default=[]) or []
    if any(q.get("code") == code for q in existing):
        errors["code"] = f"Code `{code}` existe déjà dans {filename}."
    if errors:
        return get_templates().TemplateResponse(
            request, "admin/quests/form.html",
            context={"user": user, "errors": errors, "form_data": fd, "scope": scope},
            status_code=400,
        )
    entry = {
        "code": code,
        "name": name,
        "description": fd.get("description", "").strip(),
        "objective_type": fd.get("objective_type", "").strip(),
        "objective_target": fd.get("objective_target", "").strip() or None,
        "objective_quantity": _parse_int(fd.get("objective_quantity"), 1),
        "reward_gold": _parse_int(fd.get("reward_gold"), 0),
        "reward_xp": _parse_int(fd.get("reward_xp"), 0),
        "reward_items": _parse_reward_items(fd.get("reward_items", "")),
        "tier": fd.get("tier", "easy").strip() or "easy",
    }
    append_to_list(filename, entry)
    return RedirectResponse(f"/admin/quests?q={code}&scope={scope}", status_code=303)


# --- World Bosses ---
@router.get("/world-bosses/new", response_class=HTMLResponse)
async def bosses_new_form(request: Request, user: AdminUser = Depends(require_admin)):
    return get_templates().TemplateResponse(
        request, "admin/world_bosses/form.html",
        context={"user": user, "errors": {}, "form_data": {}},
    )


@router.post("/world-bosses")
async def bosses_create(request: Request, user: AdminUser = Depends(require_admin)):
    fd = {k: str(v) for k, v in (await request.form()).items()}
    errors = {}
    code = fd.get("code", "").strip()
    name = fd.get("name", "").strip()
    if not code:
        errors["code"] = "Code requis."
    if not name:
        errors["name"] = "Nom requis."
    existing = _writer_load("boss_definitions.json", default=[]) or []
    if any(b.get("code") == code for b in existing):
        errors["code"] = f"Code `{code}` existe déjà."
    if errors:
        return get_templates().TemplateResponse(
            request, "admin/world_bosses/form.html",
            context={"user": user, "errors": errors, "form_data": fd},
            status_code=400,
        )
    # modifiers format : "damage_immunity_threshold=5, enrage_below_pct=20"
    modifiers = _parse_kv_pairs(fd.get("modifiers", ""))
    entry = {
        "code": code,
        "name": name,
        "description": fd.get("description", "").strip(),
        "image_name": fd.get("image_name", "").strip(),
        "tier": fd.get("tier", "intro").strip() or "intro",
        "spawn_weight": _parse_int(fd.get("spawn_weight"), 100),
        "max_hp": _parse_int(fd.get("max_hp"), 10000),
        "attack": _parse_int(fd.get("attack"), 50),
        "defense": _parse_int(fd.get("defense"), 20),
        "speed": _parse_int(fd.get("speed"), 5),
        "crit_chance": _parse_int(fd.get("crit_chance"), 0),
        "crit_damage": _parse_int(fd.get("crit_damage"), 100),
        "dodge": _parse_int(fd.get("dodge"), 0),
        "modifiers": modifiers,
        "lore": fd.get("lore", "").strip(),
    }
    append_to_list("boss_definitions.json", entry)
    return RedirectResponse(f"/admin/world-bosses?q={code}", status_code=303)


# --- Panoplies ---
@router.get("/panoplies/new", response_class=HTMLResponse)
async def panoplies_new_form(request: Request, user: AdminUser = Depends(require_admin)):
    return get_templates().TemplateResponse(
        request, "admin/panoplies/form.html",
        context={"user": user, "errors": {}, "form_data": {}},
    )


@router.post("/panoplies")
async def panoplies_create(request: Request, user: AdminUser = Depends(require_admin)):
    fd = {k: str(v) for k, v in (await request.form()).items()}
    errors = {}
    family = fd.get("family", "").strip().lower()
    if not family:
        errors["family"] = "Famille (code) requis."
    existing = _writer_load("sets.json", default={}) or {}
    if isinstance(existing, dict) and family in existing:
        errors["family"] = f"Famille `{family}` existe déjà."
    if errors:
        return get_templates().TemplateResponse(
            request, "admin/panoplies/form.html",
            context={"user": user, "errors": errors, "form_data": fd},
            status_code=400,
        )
    # Tiers : 2/4/8/12 pièces, bonus parsé via kv pairs
    tiers = {}
    for n in ("2", "4", "8", "12"):
        raw = fd.get(f"tier_{n}", "").strip()
        if raw:
            tiers[n] = _parse_kv_pairs(raw)
    entry = {
        "name": fd.get("name", "").strip() or family.capitalize(),
        "description": fd.get("description", "").strip(),
        "tiers": tiers,
    }
    # sets.json est parfois une liste (legacy), parfois un dict. On force dict.
    if not isinstance(existing, dict):
        existing = {k: {} for k in (existing or [])}
    existing[family] = entry
    from webapp.admin.json_writer import atomic_write_json
    atomic_write_json("sets.json", existing)
    return RedirectResponse(f"/admin/panoplies?q={family}", status_code=303)


# --- Skill Tree node ---
@router.get("/skill-tree/new", response_class=HTMLResponse)
async def skills_new_form(request: Request, user: AdminUser = Depends(require_admin)):
    data = _writer_load("skill_tree.json", default={"skills": {}}) or {"skills": {}}
    existing_codes = sorted((data.get("skills") or {}).keys())
    return get_templates().TemplateResponse(
        request, "admin/skill_tree/form.html",
        context={
            "user": user, "errors": {}, "form_data": {},
            "existing_codes": existing_codes,
        },
    )


@router.post("/skill-tree")
async def skills_create(request: Request, user: AdminUser = Depends(require_admin)):
    fd = {k: str(v) for k, v in (await request.form()).items()}
    errors = {}
    code = fd.get("code", "").strip()
    name = fd.get("name", "").strip()
    if not code:
        errors["code"] = "Code requis."
    if not name:
        errors["name"] = "Nom requis."
    data = _writer_load("skill_tree.json", default={"skills": {}}) or {"skills": {}}
    if code in (data.get("skills") or {}):
        errors["code"] = f"Skill `{code}` existe déjà."
    if errors:
        existing_codes = sorted((data.get("skills") or {}).keys())
        return get_templates().TemplateResponse(
            request, "admin/skill_tree/form.html",
            context={
                "user": user, "errors": errors, "form_data": fd,
                "existing_codes": existing_codes,
            },
            status_code=400,
        )

    # Effects : "type:val1,val2,val3 / type:val1,val2"
    effects = []
    for chunk in fd.get("effects", "").split("/"):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        type_, values_str = chunk.split(":", 1)
        values = []
        for v in values_str.split(","):
            v = v.strip()
            try:
                values.append(int(v))
            except ValueError:
                try:
                    values.append(float(v))
                except ValueError:
                    continue
        if values:
            effects.append({"type": type_.strip(), "values": values})

    node = {
        "name": name,
        "description": fd.get("description", "").strip(),
        "icon": fd.get("icon", "").strip() or "✨",
        "max_level": _parse_int(fd.get("max_level"), 5),
        "costs": _parse_int_list(fd.get("costs", "1,1,1,1,1")) or [1],
        "effects": effects,
        "prerequisites": _parse_csv(fd.get("prerequisites", "")),
        "position": {
            "x": _parse_int(fd.get("position_x"), 0),
            "y": _parse_int(fd.get("position_y"), 0),
        },
    }
    add_skill_node(code, node)
    return RedirectResponse(f"/admin/skill-tree?q={code}", status_code=303)


# --- Crafts (DB + sync JSON) ---

# Labels FR pour les catégories d'items dans le form de craft. L'ordre
# détermine l'affichage dans le select.
CATEGORY_LABELS_FR: list[tuple[str, str]] = [
    ("resource", "Ressources"),
    ("weapon", "Armes"),
    ("shield", "Boucliers"),
    ("helmet", "Casques"),
    ("chest", "Plastrons"),
    ("legs", "Jambières"),
    ("boots", "Bottes"),
    ("necklace", "Colliers"),
    ("bracelet", "Bracelets"),
    ("ring", "Bagues"),
    ("belt", "Ceintures"),
    ("cape", "Capes"),
    ("earring", "Boucles d'oreilles"),
    ("consumable", "Consommables"),
]


def _craft_form_context(items):
    """Construit items_by_category + labels pour le template."""
    items_by_cat: dict[str, list[dict]] = {}
    for it in items:
        items_by_cat.setdefault(it.category, []).append({
            "code": it.code, "name": it.name,
        })
    # Tri alphabétique des items dans chaque catégorie
    for cat in items_by_cat:
        items_by_cat[cat].sort(key=lambda x: x["name"])
    return {
        "categories": [
            {"code": cat, "label": label}
            for cat, label in CATEGORY_LABELS_FR
            if cat in items_by_cat
        ],
        "items_by_category": items_by_cat,
        "items": [{"code": it.code, "name": it.name, "category": it.category} for it in items],
    }


@router.get("/crafts/new", response_class=HTMLResponse)
async def crafts_new_form(request: Request, user: AdminUser = Depends(require_admin)):
    with get_db_session() as session:
        items = ItemRepository(session).list_all()
    return get_templates().TemplateResponse(
        request, "admin/crafts/form.html",
        context={
            "user": user, "errors": {}, "form_data": {},
            **_craft_form_context(items),
        },
    )


@router.post("/crafts")
async def crafts_create(request: Request, user: AdminUser = Depends(require_admin)):
    from app.infrastructure.db.models.craft_model import (
        CraftRecipeModel, CraftRecipeIngredientModel,
    )
    from sqlalchemy import select
    from datetime import datetime, UTC

    form = await request.form()
    # Champs scalaires
    fd: dict[str, str] = {}
    for k in ("code", "name", "result_item_code", "result_quantity",
              "result_category"):
        fd[k] = str(form.get(k, ""))

    errors = {}
    code = fd.get("code", "").strip()
    name = fd.get("name", "").strip()
    result_code = fd.get("result_item_code", "").strip()
    result_qty = _parse_int(fd.get("result_quantity"), 1)
    if not code:
        errors["code"] = "Code requis."
    if not name:
        errors["name"] = "Nom requis."
    if not result_code:
        errors["result_item_code"] = "Item résultat requis."

    # Ingrédients : champs répétés ingredient_category[], ingredient_item_code[],
    # ingredient_quantity[]. On les zippe par index.
    ing_codes = form.getlist("ingredient_item_code")
    ing_qtys = form.getlist("ingredient_quantity")
    ingredients = []
    for ic, qty in zip(ing_codes, ing_qtys):
        ic = (ic or "").strip()
        if not ic:
            continue
        try:
            q = int(qty)
            if q < 1:
                continue
        except (ValueError, TypeError):
            continue
        ingredients.append((ic, q))

    if not ingredients:
        errors["ingredients"] = "Au moins 1 ingrédient requis."

    if errors:
        with get_db_session() as session:
            items = ItemRepository(session).list_all()
        # Reconstruit la liste des rows ingrédients pour re-pré-remplir
        ingredients_rows = [
            {"category": c, "item_code": ic, "quantity": q}
            for c, ic, q in zip(
                form.getlist("ingredient_category"),
                ing_codes, ing_qtys,
            )
        ]
        return get_templates().TemplateResponse(
            request, "admin/crafts/form.html",
            context={
                "user": user, "errors": errors, "form_data": fd,
                "ingredients_rows": ingredients_rows,
                **_craft_form_context(items),
            },
            status_code=400,
        )

    with get_db_session() as session:
        repo = ItemRepository(session)
        result_item = repo.get_by_code(result_code)
        if result_item is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Item résultat `{result_code}` introuvable.")
        # Verif existence code
        existing = session.execute(
            select(CraftRecipeModel).where(CraftRecipeModel.code == code)
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Recette `{code}` existe déjà.")
        # Insert recipe
        now = datetime.now(UTC)
        recipe = CraftRecipeModel(
            code=code, name=name,
            result_item_definition_id=result_item.id,
            result_quantity=result_qty,
            created_at=now, updated_at=now,
        )
        session.add(recipe)
        session.flush()
        # Insert ingredients
        for ing_code, ing_qty in ingredients:
            ing_item = repo.get_by_code(ing_code)
            if ing_item is None:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"Ingrédient `{ing_code}` introuvable.",
                )
            session.add(CraftRecipeIngredientModel(
                craft_recipe_id=recipe.id,
                item_definition_id=ing_item.id,
                quantity=ing_qty,
            ))
        session.commit()

    return RedirectResponse(f"/admin/crafts?q={code}", status_code=303)


# ============ Edit forms ============

# Helpers de formatage inverse (struct → string compact pour pré-remplir un form)

def _fmt_kv_pairs(d: dict | None) -> str:
    """{max_hp: 20, attack: 3} → 'max_hp=20, attack=3'"""
    if not d:
        return ""
    return ", ".join(f"{k}={v}" for k, v in d.items())


def _fmt_csv(lst: list | None) -> str:
    return ", ".join(str(x) for x in (lst or []))


def _fmt_reward_items(lst: list | None) -> str:
    """[['potion_soin_i', 1]] → 'potion_soin_i:1'"""
    if not lst:
        return ""
    return ", ".join(f"{c}:{q}" for c, q in lst)


def _fmt_title_effects(effects: list | None) -> str:
    """[{type, target?, value}] → 'type:target:value, type::value'"""
    out = []
    for e in (effects or []):
        type_ = e.get("type", "")
        target = e.get("target") or ""
        val = e.get("value", "")
        out.append(f"{type_}:{target}:{val}")
    return ", ".join(out)


def _fmt_skill_effects(effects: list | None) -> str:
    """[{type, values}] → 'type:v1,v2,v3 / type2:v1,v2'"""
    out = []
    for e in (effects or []):
        type_ = e.get("type", "")
        values = e.get("values", [])
        out.append(f"{type_}:" + ",".join(str(v) for v in values))
    return " / ".join(out)


def _fmt_unlock_class(reqs: list | None) -> str:
    """[{type, profession_code?, level}] → 'profession_level:mining:2, level:5'"""
    out = []
    for r in (reqs or []):
        if r.get("type") == "profession_level":
            out.append(f"profession_level:{r.get('profession_code', '')}:{r.get('level', '')}")
        elif r.get("type") == "level":
            out.append(f"level:{r.get('level', '')}")
    return ", ".join(out)


# --- Classes ---
@router.get("/classes/{code}/edit", response_class=HTMLResponse)
async def classes_edit_form(
    code: str, request: Request, user: AdminUser = Depends(require_admin),
):
    from webapp.admin.json_writer import find_in_list_by_key
    entry = find_in_list_by_key("classes.json", code)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Classe `{code}` introuvable.")
    fd = {
        "code": entry.get("code", ""),
        "name": entry.get("name", ""),
        "description": entry.get("description", ""),
        "stat_bonuses": _fmt_kv_pairs(entry.get("stat_bonuses")),
        "unlock": _fmt_unlock_class(entry.get("unlock_requirements")),
    }
    return get_templates().TemplateResponse(
        request, "admin/classes/form.html",
        context={"user": user, "errors": {}, "form_data": fd, "edit_code": code},
    )


@router.post("/classes/{code}")
async def classes_update(
    code: str, request: Request, user: AdminUser = Depends(require_admin),
):
    from webapp.admin.json_writer import find_in_list_by_key, update_in_list_by_key
    existing = find_in_list_by_key("classes.json", code)
    if existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Classe `{code}` introuvable.")
    fd = {k: str(v) for k, v in (await request.form()).items()}
    entry = {
        "code": code,  # immuable
        "name": fd.get("name", "").strip(),
        "description": fd.get("description", "").strip(),
        "stat_bonuses": _parse_kv_pairs(fd.get("stat_bonuses", "")),
    }
    # Toujours écrire la clé (même vide) → vider le champ retire les prérequis
    # explicitement, sans dépendre de la stratégie de merge. Cf. audit (cohérence).
    entry["unlock_requirements"] = _parse_unlock_requirements(fd.get("unlock", ""))
    update_in_list_by_key("classes.json", code, entry)
    return RedirectResponse(f"/admin/classes?q={code}", status_code=303)


# --- Titres ---
@router.get("/titles/{code}/edit", response_class=HTMLResponse)
async def titles_edit_form(
    code: str, request: Request, user: AdminUser = Depends(require_admin),
):
    from webapp.admin.json_writer import find_in_list_by_key
    entry = find_in_list_by_key("titles.json", code)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Titre `{code}` introuvable.")
    fd = {
        "code": entry.get("code", ""),
        "name": entry.get("name", ""),
        "description": entry.get("description", ""),
        "icon": entry.get("icon", ""),
        "condition_type": entry.get("condition_type", ""),
        "condition_target": entry.get("condition_target", "") or "",
        "condition_value": entry.get("condition_value", 0),
        "effects": _fmt_title_effects(entry.get("effects")),
    }
    return get_templates().TemplateResponse(
        request, "admin/titles/form.html",
        context={"user": user, "errors": {}, "form_data": fd, "edit_code": code},
    )


@router.post("/titles/{code}")
async def titles_update(
    code: str, request: Request, user: AdminUser = Depends(require_admin),
):
    from webapp.admin.json_writer import find_in_list_by_key, update_in_list_by_key
    if find_in_list_by_key("titles.json", code) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Titre `{code}` introuvable.")
    fd = {k: str(v) for k, v in (await request.form()).items()}
    effects = []
    for chunk in fd.get("effects", "").split(","):
        parts = [p.strip() for p in chunk.split(":")]
        if len(parts) == 3 and parts[0]:
            try:
                value = int(parts[2]) if parts[2] else 0
            except ValueError:
                value = parts[2]
            effects.append({"type": parts[0], "target": parts[1] or None, "value": value})
        elif len(parts) == 2 and parts[0]:
            try:
                value = int(parts[1]) if parts[1] else 0
            except ValueError:
                value = parts[1]
            effects.append({"type": parts[0], "value": value})
    entry = {
        "code": code,
        "name": fd.get("name", "").strip(),
        "description": fd.get("description", "").strip(),
        "icon": fd.get("icon", "").strip(),
        "condition_type": fd.get("condition_type", "").strip(),
        "condition_target": fd.get("condition_target", "").strip() or None,
        "condition_value": _parse_int(fd.get("condition_value"), 0),
        "effects": effects,
    }
    update_in_list_by_key("titles.json", code, entry)
    return RedirectResponse(f"/admin/titles?q={code}", status_code=303)


# --- Quêtes ---
@router.get("/quests/{scope}/{code}/edit", response_class=HTMLResponse)
async def quests_edit_form(
    scope: str, code: str, request: Request,
    user: AdminUser = Depends(require_admin),
):
    from webapp.admin.json_writer import find_in_list_by_key
    filename = "weekly_quests.json" if scope == "weekly" else "daily_quests.json"
    entry = find_in_list_by_key(filename, code)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Quête `{code}` introuvable dans {filename}.")
    fd = {
        "code": entry.get("code", ""),
        "name": entry.get("name", ""),
        "description": entry.get("description", ""),
        "objective_type": entry.get("objective_type", ""),
        "objective_target": entry.get("objective_target", "") or "",
        "objective_quantity": entry.get("objective_quantity", 1),
        "reward_gold": entry.get("reward_gold", 0),
        "reward_xp": entry.get("reward_xp", 0),
        "reward_items": _fmt_reward_items(entry.get("reward_items")),
        "tier": entry.get("tier", "easy"),
    }
    return get_templates().TemplateResponse(
        request, "admin/quests/form.html",
        context={
            "user": user, "errors": {}, "form_data": fd,
            "scope": scope, "edit_code": code,
        },
    )


@router.post("/quests/{scope}/{code}")
async def quests_update(
    scope: str, code: str, request: Request,
    user: AdminUser = Depends(require_admin),
):
    from webapp.admin.json_writer import find_in_list_by_key, update_in_list_by_key
    filename = "weekly_quests.json" if scope == "weekly" else "daily_quests.json"
    if find_in_list_by_key(filename, code) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Quête `{code}` introuvable.")
    fd = {k: str(v) for k, v in (await request.form()).items()}
    entry = {
        "code": code,
        "name": fd.get("name", "").strip(),
        "description": fd.get("description", "").strip(),
        "objective_type": fd.get("objective_type", "").strip(),
        "objective_target": fd.get("objective_target", "").strip() or None,
        "objective_quantity": _parse_int(fd.get("objective_quantity"), 1),
        "reward_gold": _parse_int(fd.get("reward_gold"), 0),
        "reward_xp": _parse_int(fd.get("reward_xp"), 0),
        "reward_items": _parse_reward_items(fd.get("reward_items", "")),
        "tier": fd.get("tier", "easy").strip() or "easy",
    }
    update_in_list_by_key(filename, code, entry)
    return RedirectResponse(f"/admin/quests?q={code}&scope={scope}", status_code=303)


# --- World Bosses ---
@router.get("/world-bosses/{code}/edit", response_class=HTMLResponse)
async def bosses_edit_form(
    code: str, request: Request, user: AdminUser = Depends(require_admin),
):
    from webapp.admin.json_writer import find_in_list_by_key
    entry = find_in_list_by_key("boss_definitions.json", code)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Boss `{code}` introuvable.")
    fd = {
        "code": entry.get("code", ""),
        "name": entry.get("name", ""),
        "description": entry.get("description", ""),
        "image_name": entry.get("image_name", ""),
        "tier": entry.get("tier", ""),
        "spawn_weight": entry.get("spawn_weight", 100),
        "max_hp": entry.get("max_hp", 10000),
        "attack": entry.get("attack", 50),
        "defense": entry.get("defense", 20),
        "speed": entry.get("speed", 5),
        "crit_chance": entry.get("crit_chance", 0),
        "crit_damage": entry.get("crit_damage", 100),
        "dodge": entry.get("dodge", 0),
        "modifiers": _fmt_kv_pairs(entry.get("modifiers")),
        "lore": entry.get("lore", ""),
    }
    return get_templates().TemplateResponse(
        request, "admin/world_bosses/form.html",
        context={"user": user, "errors": {}, "form_data": fd, "edit_code": code},
    )


@router.post("/world-bosses/{code}")
async def bosses_update(
    code: str, request: Request, user: AdminUser = Depends(require_admin),
):
    from webapp.admin.json_writer import find_in_list_by_key, update_in_list_by_key
    if find_in_list_by_key("boss_definitions.json", code) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Boss `{code}` introuvable.")
    fd = {k: str(v) for k, v in (await request.form()).items()}
    entry = {
        "code": code,
        "name": fd.get("name", "").strip(),
        "description": fd.get("description", "").strip(),
        "image_name": fd.get("image_name", "").strip(),
        "tier": fd.get("tier", "intro").strip() or "intro",
        "spawn_weight": _parse_int(fd.get("spawn_weight"), 100),
        "max_hp": _parse_int(fd.get("max_hp"), 10000),
        "attack": _parse_int(fd.get("attack"), 50),
        "defense": _parse_int(fd.get("defense"), 20),
        "speed": _parse_int(fd.get("speed"), 5),
        "crit_chance": _parse_int(fd.get("crit_chance"), 0),
        "crit_damage": _parse_int(fd.get("crit_damage"), 100),
        "dodge": _parse_int(fd.get("dodge"), 0),
        "modifiers": _parse_kv_pairs(fd.get("modifiers", "")),
        "lore": fd.get("lore", "").strip(),
    }
    update_in_list_by_key("boss_definitions.json", code, entry)
    return RedirectResponse(f"/admin/world-bosses?q={code}", status_code=303)


# --- Panoplies (dict-keyed) ---
@router.get("/panoplies/{family}/edit", response_class=HTMLResponse)
async def panoplies_edit_form(
    family: str, request: Request, user: AdminUser = Depends(require_admin),
):
    data = _writer_load("sets.json", default={}) or {}
    if not isinstance(data, dict) or family not in data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Panoplie `{family}` introuvable.")
    entry = data[family] or {}
    tiers = entry.get("tiers", entry.get("bonuses", {})) if isinstance(entry, dict) else {}
    fd = {
        "family": family,
        "name": entry.get("name", "") if isinstance(entry, dict) else "",
        "description": entry.get("description", "") if isinstance(entry, dict) else "",
        "tier_2": _fmt_kv_pairs(tiers.get("2") if isinstance(tiers, dict) else None),
        "tier_4": _fmt_kv_pairs(tiers.get("4") if isinstance(tiers, dict) else None),
        "tier_8": _fmt_kv_pairs(tiers.get("8") if isinstance(tiers, dict) else None),
        "tier_12": _fmt_kv_pairs(tiers.get("12") if isinstance(tiers, dict) else None),
    }
    return get_templates().TemplateResponse(
        request, "admin/panoplies/form.html",
        context={"user": user, "errors": {}, "form_data": fd, "edit_code": family},
    )


@router.post("/panoplies/{family}")
async def panoplies_update(
    family: str, request: Request, user: AdminUser = Depends(require_admin),
):
    data = _writer_load("sets.json", default={}) or {}
    if not isinstance(data, dict) or family not in data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Panoplie `{family}` introuvable.")
    fd = {k: str(v) for k, v in (await request.form()).items()}
    tiers = {}
    for n in ("2", "4", "8", "12"):
        raw = fd.get(f"tier_{n}", "").strip()
        if raw:
            tiers[n] = _parse_kv_pairs(raw)
    entry = {
        "name": fd.get("name", "").strip() or family.capitalize(),
        "description": fd.get("description", "").strip(),
        "tiers": tiers,
    }
    data[family] = entry
    from webapp.admin.json_writer import atomic_write_json
    atomic_write_json("sets.json", data)
    return RedirectResponse(f"/admin/panoplies?q={family}", status_code=303)


# --- Skill Tree node ---
@router.get("/skill-tree/{code}/edit", response_class=HTMLResponse)
async def skills_edit_form(
    code: str, request: Request, user: AdminUser = Depends(require_admin),
):
    data = _writer_load("skill_tree.json", default={"skills": {}}) or {"skills": {}}
    skills = data.get("skills", {})
    if code not in skills:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Skill `{code}` introuvable.")
    node = skills[code]
    pos = node.get("position", {})
    fd = {
        "code": code,
        "name": node.get("name", ""),
        "description": node.get("description", ""),
        "icon": node.get("icon", ""),
        "max_level": node.get("max_level", 5),
        "costs": _fmt_csv(node.get("costs", [])),
        "prerequisites": _fmt_csv(node.get("prerequisites", [])),
        "effects": _fmt_skill_effects(node.get("effects")),
        "position_x": pos.get("x", 0),
        "position_y": pos.get("y", 0),
    }
    existing_codes = sorted(c for c in skills.keys() if c != code)
    return get_templates().TemplateResponse(
        request, "admin/skill_tree/form.html",
        context={
            "user": user, "errors": {}, "form_data": fd,
            "edit_code": code, "existing_codes": existing_codes,
        },
    )


@router.post("/skill-tree/{code}")
async def skills_update(
    code: str, request: Request, user: AdminUser = Depends(require_admin),
):
    from webapp.admin.json_writer import update_skill_node
    fd = {k: str(v) for k, v in (await request.form()).items()}
    effects = []
    for chunk in fd.get("effects", "").split("/"):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        type_, values_str = chunk.split(":", 1)
        values = []
        for v in values_str.split(","):
            v = v.strip()
            try:
                values.append(int(v))
            except ValueError:
                try:
                    values.append(float(v))
                except ValueError:
                    continue
        if values:
            effects.append({"type": type_.strip(), "values": values})
    node = {
        "name": fd.get("name", "").strip(),
        "description": fd.get("description", "").strip(),
        "icon": fd.get("icon", "").strip() or "✨",
        "max_level": _parse_int(fd.get("max_level"), 5),
        "costs": _parse_int_list(fd.get("costs", "1")) or [1],
        "effects": effects,
        "prerequisites": _parse_csv(fd.get("prerequisites", "")),
        "position": {
            "x": _parse_int(fd.get("position_x"), 0),
            "y": _parse_int(fd.get("position_y"), 0),
        },
    }
    update_skill_node(code, node)
    return RedirectResponse(f"/admin/skill-tree?q={code}", status_code=303)


# --- Crafts edit ---
@router.get("/crafts/{code}/edit", response_class=HTMLResponse)
async def crafts_edit_form(
    code: str, request: Request, user: AdminUser = Depends(require_admin),
):
    from app.infrastructure.db.models.craft_model import (
        CraftRecipeModel, CraftRecipeIngredientModel,
    )
    from app.infrastructure.db.models.item_model import ItemDefinitionModel
    from sqlalchemy import select

    with get_db_session() as session:
        recipe = session.execute(
            select(CraftRecipeModel).where(CraftRecipeModel.code == code)
        ).scalar_one_or_none()
        if recipe is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Recette `{code}` introuvable.")
        items = ItemRepository(session).list_all()
        items_by_id = {it.id: it for it in items}
        result_item = items_by_id.get(recipe.result_item_definition_id)
        ingredients_rows = []
        for ing in session.execute(
            select(CraftRecipeIngredientModel).where(
                CraftRecipeIngredientModel.craft_recipe_id == recipe.id
            )
        ).scalars().all():
            it = items_by_id.get(ing.item_definition_id)
            if it is None:
                continue
            ingredients_rows.append({
                "category": it.category,
                "item_code": it.code,
                "quantity": ing.quantity,
            })

    fd = {
        "code": code,
        "name": recipe.name,
        "result_item_code": result_item.code if result_item else "",
        "result_category": result_item.category if result_item else "",
        "result_quantity": recipe.result_quantity,
    }
    return get_templates().TemplateResponse(
        request, "admin/crafts/form.html",
        context={
            "user": user, "errors": {}, "form_data": fd,
            "edit_code": code,
            "ingredients_rows": ingredients_rows,
            **_craft_form_context(items),
        },
    )


@router.post("/crafts/{code}")
async def crafts_update(
    code: str, request: Request, user: AdminUser = Depends(require_admin),
):
    from app.infrastructure.db.models.craft_model import (
        CraftRecipeModel, CraftRecipeIngredientModel,
    )
    from sqlalchemy import select, delete
    from datetime import datetime, UTC

    form = await request.form()
    name = str(form.get("name", "")).strip()
    result_code = str(form.get("result_item_code", "")).strip()
    result_qty = _parse_int(str(form.get("result_quantity", "1")), 1)

    ing_codes = form.getlist("ingredient_item_code")
    ing_qtys = form.getlist("ingredient_quantity")
    ingredients = []
    for ic, qty in zip(ing_codes, ing_qtys):
        ic = (ic or "").strip()
        if not ic:
            continue
        try:
            q = int(qty)
            if q < 1:
                continue
        except (ValueError, TypeError):
            continue
        ingredients.append((ic, q))

    if not ingredients or not name or not result_code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Champs requis manquants.")

    with get_db_session() as session:
        recipe = session.execute(
            select(CraftRecipeModel).where(CraftRecipeModel.code == code)
        ).scalar_one_or_none()
        if recipe is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Recette `{code}` introuvable.")
        repo = ItemRepository(session)
        result_item = repo.get_by_code(result_code)
        if result_item is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Item résultat `{result_code}` introuvable.")
        recipe.name = name
        recipe.result_item_definition_id = result_item.id
        recipe.result_quantity = result_qty
        recipe.updated_at = datetime.now(UTC)
        # Replace ingredients : delete all + reinsert
        session.execute(
            delete(CraftRecipeIngredientModel).where(
                CraftRecipeIngredientModel.craft_recipe_id == recipe.id
            )
        )
        for ic, q in ingredients:
            ing_item = repo.get_by_code(ic)
            if ing_item is None:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"Ingrédient `{ic}` introuvable.",
                )
            session.add(CraftRecipeIngredientModel(
                craft_recipe_id=recipe.id,
                item_definition_id=ing_item.id,
                quantity=q,
            ))
        session.commit()

    return RedirectResponse(f"/admin/crafts?q={code}", status_code=303)
