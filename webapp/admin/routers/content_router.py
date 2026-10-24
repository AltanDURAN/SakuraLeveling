"""Routes admin pour le contenu JSON-backed : titres, quêtes, world bosses.
L'arbre de compétences s'édite dans le builder (`skill_builder_router`).

Listings : read complet via filtres + tri ; création, édition et
suppression avec écriture atomique dans le JSON.

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

from webapp.admin import git_sync
from webapp.admin.auth import AdminUser, require_admin
from webapp.admin._shared import get_templates
from webapp.admin.json_writer import (
    append_to_list,
    delete_in_list_by_key,
    load_json as _writer_load,
)


_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin-content"])

CONTENT_DIR = Path(__file__).resolve().parents[3] / "app" / "infrastructure" / "content"


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
# ============ Crafts (DB) ============


# ============ Skill Tree ============


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
            "__delete_url__": f"/admin/titles/{t.get('code', '')}/delete",
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
            "__delete_url__": f"/admin/quests/{scope}/{q.get('code', '')}/delete",
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
            "__delete_url__": f"/admin/world-bosses/{b.get('code', '')}/delete",
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
        "exclusive": fd.get("exclusive") == "on",
        "condition_type": fd.get("condition_type", "").strip(),
        "condition_target": fd.get("condition_target", "").strip() or None,
        "condition_value": _parse_int(fd.get("condition_value"), 0),
        "effects": effects,
    }
    append_to_list("titles.json", entry)
    git_sync.push_content(["app/infrastructure/content/titles.json"],
                          f"admin: titre {code} créé")
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


# ============ Edit forms ============

# Helpers de formatage inverse (struct → string compact pour pré-remplir un form)

def _fmt_kv_pairs(d: dict | None) -> str:
    """{max_hp: 20, attack: 3} → 'max_hp=20, attack=3'"""
    if not d:
        return ""
    return ", ".join(f"{k}={v}" for k, v in d.items())


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


# --- Classes ---
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
        "exclusive": entry.get("exclusive", False),
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
        "exclusive": fd.get("exclusive") == "on",
        "condition_type": fd.get("condition_type", "").strip(),
        "condition_target": fd.get("condition_target", "").strip() or None,
        "condition_value": _parse_int(fd.get("condition_value"), 0),
        "effects": effects,
    }
    update_in_list_by_key("titles.json", code, entry)
    git_sync.push_content(["app/infrastructure/content/titles.json"],
                          f"admin: titre {code} modifié")
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


# --- Skill Tree node ---


# --- Crafts edit ---


# ========================= Suppressions (DELETE) =========================
# Entités JSON-backed uniquement (classes, titres, quêtes, bosses, panoplies,
# skill nodes). Les entités DB-backed (items, mobs, crafts) ne sont pas
# supprimables ici (référencées par les joueurs — à traiter séparément).

def _delete_from_list(filename: str, code: str, label: str, redirect: str):
    try:
        delete_in_list_by_key(filename, code)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} `{code}` introuvable.")
    git_sync.push_content([f"app/infrastructure/content/{filename}"],
                          f"admin: {label} {code} supprimé(e)")
    return RedirectResponse(redirect, status_code=303)


@router.post("/titles/{code}/delete")
async def titles_delete(code: str, user: AdminUser = Depends(require_admin)):
    return _delete_from_list("titles.json", code, "Titre", "/admin/titles")


@router.post("/world-bosses/{code}/delete")
async def bosses_delete(code: str, user: AdminUser = Depends(require_admin)):
    return _delete_from_list("boss_definitions.json", code, "Boss", "/admin/world-bosses")


@router.post("/quests/{scope}/{code}/delete")
async def quests_delete(scope: str, code: str, user: AdminUser = Depends(require_admin)):
    filename = "weekly_quests.json" if scope == "weekly" else "daily_quests.json"
    return _delete_from_list(filename, code, "Quête", f"/admin/quests?scope={scope}")


@router.get("/skill-tree", response_class=HTMLResponse)
async def skill_tree_list(user: AdminUser = Depends(require_admin)):
    """L'arbre (format v2 : nodes, links, palettes) s'édite dans le builder."""
    return RedirectResponse("/admin/skill-tree/builder", status_code=303)
