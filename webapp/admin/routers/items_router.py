"""Routes admin pour gérer les items (CRUD, V1 sans delete)."""

from __future__ import annotations

import io
import json
import logging
import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from PIL import Image

from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.session import get_db_session
from app.shared.enums import (
    EQUIPMENT_SLOT_LABELS,
    ITEM_CATEGORY_DEFAULT_SLOT,
    ITEM_CATEGORY_EMOJIS,
    ITEM_CATEGORY_LABELS,
    ITEM_RARITY_LABELS,
    STAT_EMOJIS,
    STAT_LABELS,
    EquipmentSlot,
    ItemCategory,
    ItemRarity,
)
from app.shared.paths import ITEMS_ASSETS_DIR
from webapp.admin import content_sync, git_sync, image_gen, uploads
from webapp.admin.auth import AdminUser, require_admin
from webapp.admin._shared import get_templates


_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/items", tags=["admin-items"])

_RARITY_COLORS = {
    "common": "#9aa0aa", "uncommon": "#3fb950", "rare": "#4a9eff",
    "epic": "#a371f7", "legendary": "#e3b341",
}


async def _save_item_image(form, code: str) -> tuple[str | None, str | None]:
    """Enregistre l'image uploadée (le cas échéant) en assets/items/<code>.png
    (convertie en PNG pour rester compatible avec les rendus qui lisent
    <code>.png/.jpg). Nettoie les autres extensions du même code. Renvoie
    (asset_path_git | None, error | None)."""
    upload = form.get("image_file")
    if upload is None or not getattr(upload, "filename", ""):
        return None, None
    data = await upload.read()
    if not data:
        return None, None
    try:
        img = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None, "Image illisible (formats acceptés : PNG/JPG/WebP/GIF)."
    if len(data) > 8 * 1024 * 1024:
        return None, "Image trop lourde (max 8 Mo)."
    _clear_item_assets(code)
    img.save(ITEMS_ASSETS_DIR / f"{code}.png", "PNG")
    return f"assets/items/{code}.png", None


def _clear_item_assets(code: str) -> None:
    """Supprime toute image existante <code>.<ext> (avant d'en écrire une neuve)."""
    ITEMS_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        p = ITEMS_ASSETS_DIR / f"{code}{ext}"
        if p.exists():
            p.unlink()


# Stats supportées par le système (cf StatsService)
SUPPORTED_STATS = [
    "max_hp", "attack", "defense", "speed",
    "crit_chance", "crit_damage", "dodge", "hp_regeneration",
]




def _parse_stat_bonuses(form_data: dict[str, str]) -> dict[str, int]:
    """Le form envoie stat_bonus_max_hp, stat_bonus_attack, etc.
    On extrait les non-zéros vers un dict propre."""
    out: dict[str, int] = {}
    for stat in SUPPORTED_STATS:
        raw = form_data.get(f"stat_bonus_{stat}", "").strip()
        if not raw:
            continue
        try:
            value = int(raw)
        except ValueError:
            continue
        if value != 0:
            out[stat] = value
    return out


def _labels_ctx() -> dict:
    """Maps FR + icônes + couleurs injectées dans la page cartes."""
    return {
        "categories": [c.value for c in ItemCategory],
        "rarities": [r.value for r in ItemRarity],
        "slots": [s.value for s in EquipmentSlot],
        "supported_stats": SUPPORTED_STATS,
        "category_labels": ITEM_CATEGORY_LABELS,
        "category_emojis": ITEM_CATEGORY_EMOJIS,
        "rarity_labels": ITEM_RARITY_LABELS,
        "rarity_colors": _RARITY_COLORS,
        "slot_labels": EQUIPMENT_SLOT_LABELS,
        "stat_labels": STAT_LABELS,
        "stat_emojis": STAT_EMOJIS,
        "category_slot": ITEM_CATEGORY_DEFAULT_SLOT,
    }


def _auto_code(name: str, repo: ItemRepository) -> str:
    """Code technique unique dérivé du nom (invisible pour l'admin)."""
    base = _slugify(name)
    code, i = base, 2
    while repo.get_by_code(code) is not None:
        code, i = f"{base}_{i}", i + 1
    return code


def _item_card_state(item) -> dict:
    """État consommé par le composant Alpine de la carte (data-item)."""
    return {
        "code": item.code, "name": item.name, "description": item.description or "",
        "category": item.category, "rarity": item.rarity,
        "family": item.family or "", "equipment_slot": item.equipment_slot or "",
        "requires_two_hands": bool(item.requires_two_hands),
        "stackable": bool(item.stackable),
        "max_stack": item.max_stack, "sell_price": item.sell_price or 0,
        "buy_price": item.buy_price, "stats": dict(item.stat_bonuses or {}),
        "icon": item.icon or "",
    }


def _collect_item_fields(form_data: dict[str, str], code: str, fallback_rarity: str = "common") -> dict:
    """Construit le dict de champs commun à create (repo.create) et update
    (repo.update_by_code) + à la sync JSON. Source unique de vérité du parsing.

    Le slot d'équipement est DÉDUIT du type (plus de champ à saisir)."""
    category = form_data["category"].strip()
    return {
        "code": code,
        "name": form_data["name"].strip(),
        "description": form_data.get("description", "").strip(),
        "category": category,
        "rarity": form_data.get("rarity", fallback_rarity).strip() or fallback_rarity,
        "stackable": form_data.get("stackable") == "on",
        "max_stack": _parse_optional_int(form_data.get("max_stack")),
        "sell_price": _parse_optional_int(form_data.get("sell_price")) or 0,
        "buy_price": _parse_optional_int(form_data.get("buy_price")),
        "icon": form_data.get("icon", "").strip() or None,
        "stat_bonuses": _parse_stat_bonuses(form_data) or None,
        "equipment_slot": ITEM_CATEGORY_DEFAULT_SLOT.get(category),
        "requires_two_hands": form_data.get("requires_two_hands") == "on",
        "family": form_data.get("family", "").strip(),
    }


def _validate_item_form(form_data: dict[str, str], require_code: bool) -> dict[str, str]:
    """Validation partagée create/update. Pour update, code vient de l'URL → on
    ne le revalide pas. Sans ça, items_update acceptait une catégorie arbitraire
    ou un nom vide qu'items_create aurait refusés (asymétrie de l'audit)."""
    errors: dict[str, str] = {}
    if require_code and not form_data.get("code", "").strip():
        errors["code"] = "Code requis."
    if not form_data.get("name", "").strip():
        errors["name"] = "Nom requis."
    if form_data.get("category", "").strip() not in {c.value for c in ItemCategory}:
        errors["category"] = "Catégorie invalide."
    return errors


@router.get("", response_class=HTMLResponse)
async def items_list(
    request: Request,
    user: AdminUser = Depends(require_admin),
    saved: str | None = None,
    err: str | None = None,
):
    with get_db_session() as session:
        items = ItemRepository(session).list_all()
    items.sort(key=lambda i: (i.category, i.name))

    cards = []
    for it in items:
        search = " ".join([
            it.name or "", ITEM_CATEGORY_LABELS.get(it.category, it.category),
            ITEM_RARITY_LABELS.get(it.rarity, it.rarity), it.family or "",
        ]).lower()
        cards.append({
            "item": it, "state": _item_card_state(it), "search": search,
            "stat_bonuses": it.stat_bonuses or {},
        })

    return get_templates().TemplateResponse(
        request, "admin/items/list.html",
        context={
            "user": user, "cards": cards,
            "all_families": sorted({i.family for i in items if i.family}),
            "saved": saved, "err": err,
            **_labels_ctx(),
        },
    )


@router.get("/new")
async def items_new_form(user: AdminUser = Depends(require_admin)):
    """La création se fait en place (carte « Nouvel item »)."""
    return RedirectResponse("/admin/items#new", status_code=303)


@router.post("")
async def items_create(
    request: Request,
    user: AdminUser = Depends(require_admin),
):
    """Crée un item. Le code technique est GÉNÉRÉ à partir du nom (invisible)."""
    form = await request.form()
    form_data = {k: str(v) for k, v in form.items() if k != "image_file"}
    name = form_data.get("name", "").strip()
    category = form_data.get("category", "").strip()
    if not name or category not in {c.value for c in ItemCategory}:
        return RedirectResponse("/admin/items?err=invalid#new", status_code=303)

    with get_db_session() as session:
        repo = ItemRepository(session)
        code = _auto_code(name, repo)
        fields = _collect_item_fields(form_data, code)
        repo.create(**fields)

    asset_path, img_err = await _save_item_image(form, code)
    content_sync.upsert_item_json(content_sync.build_item_dict(**fields))
    push_paths = ["app/infrastructure/content/items.json"]
    if asset_path:
        push_paths.append(asset_path)
    git_sync.push_content(push_paths, f"admin: item {code} créé")
    suffix = "&err=upload" if img_err else ""
    _logger.info("Admin %s a créé l'item %s", user.discord_id, code)
    return RedirectResponse(f"/admin/items?saved={code}{suffix}#item-{code}", status_code=303)


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return s or "item"


@router.post("/quick-create")
async def items_quick_create(request: Request, user: AdminUser = Depends(require_admin)):
    """Création MINIMALE d'un item (nom + catégorie + rareté), pensée pour être
    appelée depuis l'éditeur de drops d'un monstre. JSON in/out. Le code est
    dérivé du nom (unicité garantie). Éditable ensuite en détail dans Objets."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    name = str(payload.get("name", "")).strip()
    category = str(payload.get("category", "resource")).strip()
    rarity = str(payload.get("rarity", "common")).strip()
    if not name:
        return JSONResponse({"error": "Nom requis."}, status_code=400)
    if category not in {c.value for c in ItemCategory}:
        category = "resource"
    if rarity not in {r.value for r in ItemRarity}:
        rarity = "common"

    base = _slugify(name)
    with get_db_session() as session:
        repo = ItemRepository(session)
        code, i = base, 2
        while repo.get_by_code(code) is not None:
            code, i = f"{base}_{i}", i + 1
        fields = {
            "code": code, "name": name, "description": "", "category": category,
            "rarity": rarity, "stackable": category == "resource", "max_stack": None,
            "sell_price": 0, "buy_price": None, "icon": None, "stat_bonuses": None,
            "equipment_slot": None, "requires_two_hands": False, "family": "",
        }
        repo.create(**fields)
    content_sync.upsert_item_json(content_sync.build_item_dict(**fields))
    git_sync.push_content(["app/infrastructure/content/items.json"],
                          f"admin: item {code} créé (quick)")
    _logger.info("Admin %s a créé l'item %s (quick, depuis un drop)", user.discord_id, code)
    return JSONResponse({"code": code, "name": name, "category": category, "rarity": rarity})


@router.post("/{code}/generate-image")
async def items_generate_image(code: str, request: Request,
                               user: AdminUser = Depends(require_admin)):
    """Génère l'image de l'item via un service gratuit et la pose en
    assets/items/<code>.png. Corps JSON optionnel : {prompt}. Sans prompt, une
    description est dérivée du nom/type/rareté."""
    with get_db_session() as session:
        item = ItemRepository(session).get_by_code(code)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Item `{code}` introuvable.")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    prompt = str(payload.get("prompt", "")).strip() or image_gen.build_item_prompt(
        item.name, item.category, item.rarity)
    try:
        png = image_gen.generate_image(prompt)
    except image_gen.ImageGenError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    _clear_item_assets(code)
    (ITEMS_ASSETS_DIR / f"{code}.png").write_bytes(png)
    git_sync.push_content([f"assets/items/{code}.png"], f"admin: image générée pour {code}")
    _logger.info("Admin %s a généré l'image de l'item %s", user.discord_id, code)
    return JSONResponse({"ok": True, "code": code, "prompt": prompt})


@router.get("/{code}/edit")
async def items_edit_form(code: str, user: AdminUser = Depends(require_admin)):
    """L'édition se fait en place sur la carte de l'item (deep-link)."""
    return RedirectResponse(f"/admin/items#item-{code}", status_code=303)


@router.post("/{code}")
async def items_update(
    code: str, request: Request,
    user: AdminUser = Depends(require_admin),
):
    form = await request.form()
    form_data = {k: str(v) for k, v in form.items() if k != "image_file"}

    with get_db_session() as session:
        repo = ItemRepository(session)
        existing = repo.get_by_code(code)
        if existing is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Item `{code}` introuvable.",
            )
        errors = _validate_item_form(form_data, require_code=False)
        if errors:
            return RedirectResponse(f"/admin/items?err=invalid#item-{code}", status_code=303)
        fields = _collect_item_fields(form_data, code, fallback_rarity=existing.rarity)
        repo.update_by_code(**fields)

    asset_path, img_err = await _save_item_image(form, code)
    content_sync.upsert_item_json(content_sync.build_item_dict(**fields))
    push_paths = ["app/infrastructure/content/items.json"]
    if asset_path:
        push_paths.append(asset_path)
    git_sync.push_content(push_paths, f"admin: item {code} modifié")
    suffix = "&err=upload" if img_err else ""
    return RedirectResponse(f"/admin/items?saved={code}{suffix}#item-{code}", status_code=303)


def _parse_optional_int(raw: str | None) -> int | None:
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


@router.post("/{code}/delete")
async def items_delete(code: str, user: AdminUser = Depends(require_admin)):
    """Suppression en cascade : retire l'item de la DB (inventaires, équipement,
    sets, trades, marketplace, shop, crafts) ET des JSON de contenu."""
    from app.application.use_cases.delete_item import DeleteItemUseCase
    with get_db_session() as session:
        result = DeleteItemUseCase().execute(session, code)
    if not result.deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Item `{code}` introuvable.")
    touched = content_sync.delete_item_json(code)
    _logger.info("Admin %s a supprimé l'item %s (refs DB: %s, recettes: %s, json: %s)",
                 user.discord_id, code, result.removed_refs, result.recipes_removed, touched)
    if touched:
        git_sync.push_content([f"app/infrastructure/content/{f}" for f in touched],
                              f"admin: item {code} supprimé (cascade)")
    return RedirectResponse("/admin/items", status_code=303)
