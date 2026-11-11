"""Routes admin pour gérer les items (CRUD, V1 sans delete)."""

from __future__ import annotations

import io
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from PIL import Image
from starlette.concurrency import run_in_threadpool

from app.domain.services.gear_passives import PASSIVES
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.session import get_db_session
from app.shared.enums import (
    EQUIPABLE_CATEGORIES,
    EQUIPMENT_SLOT_LABELS,
    ItemSlotType,
    ITEM_CATEGORY_DEFAULT_SLOT,
    ITEM_CATEGORY_EMOJIS,
    ITEM_CATEGORY_LABELS,
    ITEM_RARITY_LABELS,
    STAT_EMOJIS,
    STAT_LABELS,
    ItemCategory,
    ItemRarity,
)
from app.shared.image_tools import prepare_item_image
from webapp.admin import item_sources
from app.shared.paths import ITEMS_ASSETS_DIR
from webapp.admin import content_sync, git_sync, image_gen
from webapp.admin.auth import AdminUser, require_admin
from webapp.admin._shared import get_templates


_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/items", tags=["admin-items"])

_RARITY_COLORS = {
    "common": "#9aa0aa", "uncommon": "#3fb950", "rare": "#4a9eff",
    "epic": "#a371f7", "legendary": "#e3b341",
}


MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _store_item_image(code: str, data: bytes) -> str | None:
    """Écrit `data` en assets/items/<code>.png (converti en PNG pour rester
    compatible avec les rendus qui lisent <code>.png/.jpg, réduit à 512 px et
    détouré s'il est sur fond blanc, cf. `prepare_item_image`) et nettoie les
    autres extensions du même code. Renvoie un message d'erreur, ou None."""
    if len(data) > MAX_IMAGE_BYTES:
        return "Image trop lourde (max 8 Mo)."
    try:
        img = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return "Image illisible (formats acceptés : PNG/JPG/WebP/GIF)."
    ready = prepare_item_image(img)
    _clear_item_assets(code)
    ready.save(ITEMS_ASSETS_DIR / f"{code}.png", "PNG", optimize=True)
    return None


async def _save_item_image(form, code: str) -> tuple[str | None, str | None]:
    """Enregistre l'image uploadée (le cas échéant) avec la fiche de l'objet.
    Renvoie (asset_path_git | None, error | None)."""
    upload = form.get("image_file")
    if upload is None or not getattr(upload, "filename", ""):
        return None, None
    data = await upload.read()
    if not data:
        return None, None
    err = _store_item_image(code, data)
    return (None, err) if err else (f"assets/items/{code}.png", None)


def _clear_item_assets(code: str) -> None:
    """Supprime toute image existante <code>.<ext> (avant d'en écrire une neuve)."""
    ITEMS_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        p = ITEMS_ASSETS_DIR / f"{code}{ext}"
        if p.exists():
            p.unlink()


# Stats supportées par le système (cf StatsService). Saison 1 : ATK / DEF /
# PV de l'équipement sont en % du socle (`*_pct`) — sans ces clés, enregistrer
# une pièce (même pour changer son image) effaçait ses stats principales.
SUPPORTED_STATS = [
    "attack_pct", "defense_pct", "max_hp_pct",
    "max_hp", "attack", "defense", "speed",
    "crit_chance", "crit_damage", "dodge", "hp_regeneration",
    # Mana : déjà lu par StatsService sur l'équipement — il ne manquait que
    # l'exposition côté admin pour pouvoir en mettre sur un objet.
    "mana_max", "mana_regeneration",
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
        "categories": [c.value for c in ItemCategory if c is not ItemCategory.CARD],
        "rarities": [r.value for r in ItemRarity],
        # Un item déclare un TYPE d'emplacement (tete, corps, accessoire,
        # arme), jamais un emplacement physique numéroté : c'est le use case
        # d'équipement qui choisit `accessoire_2` ou `arme_1` à la pose.
        "slots": [s.value for s in ItemSlotType],
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
        "passive": getattr(item, "passive", "") or "",
        "stackable": bool(item.stackable),
        "max_stack": item.max_stack, "sell_price": item.sell_price or 0,
        "buy_price": item.buy_price, "stats": dict(item.stat_bonuses or {}),
        "icon": item.icon or "",
        "gen_prompt": image_gen.build_item_prompt(
            item.code, item.name, item.category, item.rarity),
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
        # Passif d'équipement (actif dès l'épique) ; inconnu ⇒ aucun.
        "passive": (p if (p := form_data.get("passive", "").strip()) in PASSIVES else "")
                   if category in EQUIPABLE_CATEGORIES else "",
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
    if form_data.get("category", "").strip() not in {c.value for c in ItemCategory if c is not ItemCategory.CARD}:
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
        # Les cartes à collectionner se gèrent dans cards.json, pas ici.
        items = [i for i in ItemRepository(session).list_all() if i.category != ItemCategory.CARD.value]
        # D'où vient chaque objet (monstre qui le porte, famille, butin, Elna,
        # Sorn, fêtes) : affiché sur la carte, filtrable par famille de monstre.
        sources = item_sources.load(session, {i.code: i.name for i in items})
    items.sort(key=lambda i: (i.category, i.name))

    cards = []
    for it in items:
        search = " ".join([
            it.name or "", ITEM_CATEGORY_LABELS.get(it.category, it.category),
            ITEM_RARITY_LABELS.get(it.rarity, it.rarity), it.family or "", sources.search_text(it.code),
        ]).lower()
        cards.append({
            "item": it, "state": _item_card_state(it), "search": search,
            "stat_bonuses": it.stat_bonuses or {},
            "sources": sources.by_item.get(it.code, []),
            "families": " ".join(sources.families_of(it.code)),
            "order": sources.order.get(it.code, {}),
        })

    return get_templates().TemplateResponse(
        request, "admin/items/list.html",
        context={
            "user": user, "cards": cards,
            "mob_families": [{**f, "count": sum(1 for c in cards if f["code"] in c["families"].split())}
                             for f in sources.families],
            "no_monster": sum(1 for c in cards if not c["families"]),
            "all_families": sorted({i.family for i in items if i.family}),
            # Une pièce par passif : on indique où chacun est déjà posé.
            "all_passives": [
                {"code": p.code, "name": p.name, "description": p.description,
                 "used_by": ", ".join(i.name for i in items if getattr(i, "passive", "") == p.code)}
                for p in PASSIVES.values()
            ],
            "saved": saved, "err": err,
            **_labels_ctx(),
        },
    )


# --------------------------------------------------------------------------
# Images en lot : déposer toutes les images d'un coup, un seul Enregistrer.
# Seules les images sont écrites — jamais la fiche de l'objet (ni la base, ni
# items.json) : rien d'autre ne peut changer par erreur.
# --------------------------------------------------------------------------

def _image_version(code: str) -> int:
    path = ITEMS_ASSETS_DIR / f"{code}.png"
    return int(path.stat().st_mtime) if path.exists() else 0


@router.get("/images", response_class=HTMLResponse)
async def items_images(request: Request, user: AdminUser = Depends(require_admin)):
    with get_db_session() as session:
        items = [i for i in ItemRepository(session).list_all() if i.category != ItemCategory.CARD.value]
    order = {c.value: i for i, c in enumerate(ItemCategory)}
    items.sort(key=lambda i: (order.get(i.category, 99), i.name))
    tiles = [{"code": it.code, "name": it.name, "category": it.category,
              "version": _image_version(it.code)} for it in items]
    return get_templates().TemplateResponse(
        request, "admin/items/images.html",
        context={"user": user, "tiles": tiles, "category_labels": ITEM_CATEGORY_LABELS,
                 "category_emojis": ITEM_CATEGORY_EMOJIS},
    )


@router.post("/images/upload/{code}")
async def items_image_upload(code: str, request: Request, user: AdminUser = Depends(require_admin)):
    """Écrit l'image d'UN objet, sans pousser sur git (cf. `/images/push`,
    appelé une fois à la fin du lot)."""
    with get_db_session() as session:
        if ItemRepository(session).get_by_code(code) is None:
            return JSONResponse({"ok": False, "error": f"Objet `{code}` introuvable."}, status_code=404)
    upload = (await request.form()).get("image")
    data = await upload.read() if upload is not None and hasattr(upload, "read") else b""
    if not data:
        return JSONResponse({"ok": False, "error": "Aucune image reçue."}, status_code=400)
    err = await run_in_threadpool(_store_item_image, code, data)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    return {"ok": True, "url": f"/assets/items/{code}.png?v={_image_version(code)}"}


@router.post("/images/push")
async def items_images_push(request: Request, user: AdminUser = Depends(require_admin)):
    """Un seul commit (et un seul push) pour toutes les images du lot."""
    try:
        codes = (await request.json()).get("codes") or []
    except Exception:  # noqa: BLE001
        codes = []
    paths = sorted({f"assets/items/{c}.png" for c in codes
                    if isinstance(c, str) and re.fullmatch(r"[a-z0-9_]+", c)
                    and (ITEMS_ASSETS_DIR / f"{c}.png").exists()})
    pushed = False
    if paths:
        noun = "image d'objet" if len(paths) == 1 else "images d'objets"
        pushed = await run_in_threadpool(git_sync.push_content, paths, f"admin: {len(paths)} {noun}")
    return {"ok": True, "count": len(paths), "pushed": pushed}


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
        item.code, item.name, item.category, item.rarity)
    try:
        png = image_gen.generate_image(prompt)
    except image_gen.ImageGenError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    _clear_item_assets(code)
    (ITEMS_ASSETS_DIR / f"{code}.png").write_bytes(png)
    git_sync.push_content([f"assets/items/{code}.png"], f"admin: image générée pour {code}")
    _logger.info("Admin %s a généré l'image de l'item %s (via %s)",
                 user.discord_id, code, image_gen.active_provider())
    return JSONResponse({"ok": True, "code": code, "prompt": prompt,
                         "provider": image_gen.active_provider()})


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
        # Un consommable porte son EFFET (soin, mana, élixir, outil de Sorn) et
        # un cosmétique son APPARENCE dans stat_bonuses, que le formulaire
        # (stats numériques) ne sait pas éditer : on les garde.
        kept = existing.stat_bonuses or {}
        if ((fields["category"] == "consumable" and kept.get("effect"))
                or (fields["category"] == "cosmetic" and kept.get("cosmetic"))):
            fields["stat_bonuses"] = kept
        else:
            # Une clé que le formulaire ne connaît pas n'est jamais effacée.
            unknown = {k: v for k, v in kept.items() if k not in SUPPORTED_STATS}
            if unknown:
                fields["stat_bonuses"] = {**unknown, **(fields["stat_bonuses"] or {})}
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
    _logger.info("Admin %s a supprimé l'item %s (refs DB: %s, json: %s)",
                 user.discord_id, code, result.removed_refs, touched)
    if touched:
        git_sync.push_content([f"app/infrastructure/content/{f}" for f in touched],
                              f"admin: item {code} supprimé (cascade)")
    return RedirectResponse("/admin/items", status_code=303)
