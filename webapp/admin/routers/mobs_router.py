"""Routes admin pour gérer les mobs (CRUD, V1 sans delete)."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi import HTTPException

from app.bot.rendering.element_visuals import ELEMENT_COLORS
from app.domain.services.power_score_service import PowerScoreService
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.encounters import farm_zone_loader, mob_element_weight_loader
from app.shared.enums import ELEMENT_EMOJIS, ELEMENT_LABELS
from app.shared.paths import MOBS_ASSETS_DIR
from webapp.admin import content_sync, git_sync, json_writer, uploads
from webapp.admin.auth import AdminUser, require_admin
from webapp.admin._shared import get_templates


_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/mobs", tags=["admin-mobs"])

_RARITY_COLORS = {
    "common": "#9aa0aa", "uncommon": "#3fb950", "rare": "#4a9eff",
    "epic": "#a371f7", "legendary": "#e3b341",
}


def _hex(rgb) -> str:
    try:
        r, g, b = rgb
        return f"#{int(r):02x}{int(g):02x}{int(b):02x}"
    except (TypeError, ValueError):
        return "#96969b"


def _mob_zone_ctx(mob) -> dict:
    """Zone du monstre + ses éléments (spots) avec le poids actuel du monstre.
    Sert de palette pour les tags élémentaires de la carte."""
    farm_zone_loader.clear_cache()
    ch = farm_zone_loader.get_spawn_channel_for_family(mob.family)
    zone = farm_zone_loader.get_zone_by_channel(ch)
    weights = mob_element_weight_loader.get_weights(mob.code)
    elements = []
    for s in farm_zone_loader.get_spots(ch):
        el = str(s.get("element", "")).strip().lower()
        if not el:
            continue
        elements.append({
            "code": el, "label": ELEMENT_LABELS.get(el, el),
            "emoji": ELEMENT_EMOJIS.get(el, ""),
            "color": _hex(ELEMENT_COLORS.get(el)),
            "time": s.get("time", "always"),
            "weight": weights.get(el, 0),
        })
    return {
        "name": (zone or {}).get("name", "") if zone else "",
        "channel_id": ch, "elements": elements,
    }


def _loot_rows(mob, item_map: dict) -> list[dict]:
    """Lignes de drop enrichies (nom + rareté de l'item) pour l'affichage."""
    rows = []
    for d in (mob.loot_table or []):
        code = d.get("item_code")
        it = item_map.get(code) or {}
        rows.append({
            "item_code": code,
            "name": it.get("name", code),
            "rarity": it.get("rarity", "common"),
            "drop_rate": d.get("drop_rate", 0),
            "min_quantity": d.get("min_quantity", 1),
            "max_quantity": d.get("max_quantity", 1),
        })
    return rows

_WEIGHTS_FILE = "mob_element_weights.json"
_WEIGHTS_COMMENT = (
    "Poids de spawn élémentaires par monstre (édités sur la fiche du monstre) : "
    "weights[mob][element] = poids (>0). Un monstre sans poids hérite d'un tirage "
    "uniforme sur les éléments de sa zone."
)


def _mob_weight_elements(mob) -> list[dict]:
    """Éléments de la zone du monstre + son poids actuel pour chacun. Sert à la
    section « Poids de spawn élémentaires » de la fiche."""
    farm_zone_loader.clear_cache()
    ch = farm_zone_loader.get_spawn_channel_for_family(mob.family)
    weights = mob_element_weight_loader.get_weights(mob.code)
    out: list[dict] = []
    for s in farm_zone_loader.get_spots(ch):
        el = str(s.get("element", "")).strip().lower()
        if not el:
            continue
        out.append({
            "code": el, "label": ELEMENT_LABELS.get(el, el),
            "emoji": ELEMENT_EMOJIS.get(el, ""), "time": s.get("time", "always"),
            "weight": weights.get(el, 0),
        })
    return out


def _save_mob_weights(code: str, form_data: dict, elements: list[dict]) -> bool:
    """Écrit les poids élémentaires du monstre depuis le form (champs
    `elem_weight_<el>`). Renvoie True si le fichier a changé."""
    new_weights: dict[str, int] = {}
    for el in elements:
        raw = form_data.get(f"elem_weight_{el['code']}")
        w = _parse_int(raw, el["weight"])
        if w > 0:
            new_weights[el["code"]] = w
    data = json_writer.load_json(_WEIGHTS_FILE, {"weights": {}}) or {"weights": {}}
    weights = data.get("weights", {})
    if not isinstance(weights, dict):
        weights = {}
    before = weights.get(code)
    if new_weights:
        weights[code] = new_weights
    else:
        weights.pop(code, None)
    if weights.get(code) == before:
        return False
    json_writer.atomic_write_json(_WEIGHTS_FILE, {"_comment": _WEIGHTS_COMMENT, "weights": weights})
    mob_element_weight_loader.reload_cache()
    return True


async def _save_mob_image(form, code: str, fallback: str) -> tuple[str, str | None, str | None]:
    """Si un fichier image a été uploadé, l'enregistre dans assets/mobs/ sous
    `<code>.<ext>` et renvoie (image_name, asset_path_git, error). Sinon renvoie
    (fallback, None, None). asset_path_git sert au git push."""
    upload = form.get("image_file")
    if upload is None or not getattr(upload, "filename", ""):
        return fallback, None, None
    data = await upload.read()
    try:
        saved = uploads.save_asset_bytes(
            data, upload.filename, MOBS_ASSETS_DIR, preferred_stem=code,
        )
    except uploads.UploadError as exc:
        return fallback, None, str(exc)
    return saved, f"assets/mobs/{saved}", None




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


def _parse_int(raw: str | None, default: int = 0) -> int:
    v = _parse_optional_int(raw)
    return v if v is not None else default


def _parse_loot_table(raw: str | None) -> list[dict] | None:
    """Le form envoie un textarea JSON. Liste vide → None."""
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        return None
    except json.JSONDecodeError:
        return None


def _clamp_mob_stats(
    *, max_hp: int, attack: int, defense: int, speed: int,
    crit_chance: int, crit_damage: int, dodge: int, hp_regeneration: int,
    xp_reward: int, gold_reward: int, spawn_weight: int,
    current_hp: int | None = None,
) -> dict:
    """Borne les stats aux conventions de combat V2 (crit_chance/dodge 0..100,
    crit_damage ≥ 0 avec 100=neutre, current_hp ≤ max_hp). Clampage silencieux
    pour que l'admin puisse itérer sans avoir à corriger lui-même les overflows."""
    mh = max(1, max_hp)
    out = {
        "max_hp": mh,
        "attack": max(0, attack),
        "defense": max(0, defense),
        "speed": max(0, speed),
        "crit_chance": max(0, min(crit_chance, 100)),
        "crit_damage": max(0, crit_damage),
        "dodge": max(0, min(dodge, 100)),
        "hp_regeneration": max(0, hp_regeneration),
        "xp_reward": max(0, xp_reward),
        "gold_reward": max(0, gold_reward),
        "spawn_weight": max(1, spawn_weight),
    }
    if current_hp is not None:
        out["current_hp"] = max(0, min(current_hp, mh))
    return out


@router.get("", response_class=HTMLResponse)
async def mobs_list(
    request: Request,
    user: AdminUser = Depends(require_admin),
    saved: str | None = None,
    err: str | None = None,
):
    pss = PowerScoreService()
    with get_db_session() as session:
        mobs = MobRepository(session).list_all()
        items = ItemRepository(session).list_all()
    item_map = {it.code: {"name": it.name, "rarity": it.rarity, "category": it.category}
                for it in items}
    mobs.sort(key=lambda m: (m.family or "zzz", m.name))

    _stat_keys = ("max_hp", "attack", "defense", "speed",
                  "crit_chance", "crit_damage", "dodge", "hp_regeneration")
    # Total de poids de spawn PAR SALON (quel monstre sort dans la zone) → sert
    # à afficher le poids d'un mob en proportion (40 / total (X%)).
    farm_zone_loader.clear_cache()
    channel_total: dict[int, int] = {}
    for m in mobs:
        ch = farm_zone_loader.get_spawn_channel_for_family(m.family)
        channel_total[ch] = channel_total.get(ch, 0) + max(0, m.spawn_weight)

    cards = []
    for m in mobs:
        score = pss.calculate_from_mob(m)
        zone = _mob_zone_ctx(m)
        loot_rows = _loot_rows(m, item_map)
        # État complet consommé par le composant Alpine de la carte (data-card).
        state = {
            "code": m.code, "name": m.name, "family": m.family or "",
            "element": m.element or "", "description": m.description or "",
            "image": m.image_name or "",
            "weights": {e["code"]: e["weight"] for e in zone["elements"]},
            "elements": zone["elements"],
            "stats": {k: getattr(m, k) for k in _stat_keys},
            "rewards": {"xp_reward": m.xp_reward, "gold_reward": m.gold_reward,
                        "spawn_weight": m.spawn_weight},
            "spawn_total": channel_total.get(
                farm_zone_loader.get_spawn_channel_for_family(m.family), 0),
            "loot": [{"item_code": r["item_code"], "drop_rate": r["drop_rate"],
                      "min_quantity": r["min_quantity"], "max_quantity": r["max_quantity"]}
                     for r in loot_rows],
        }
        search = " ".join([m.name or "", m.family or ""]
                          + [e["label"] for e in zone["elements"] if e["weight"] > 0]).lower()
        cards.append({
            "mob": m, "zone": zone, "state": state, "loot_rows": loot_rows,
            "power_score": pss.format_score(score), "rank": pss.compute_rank(score),
            "search": search,
        })

    items_catalog = sorted(
        ({"code": it.code, "name": it.name, "rarity": it.rarity, "category": it.category}
         for it in items),
        key=lambda x: (x["category"], x["name"]),
    )
    item_categories = sorted({it.category for it in items if it.category})
    return get_templates().TemplateResponse(
        request, "admin/mobs/list.html",
        context={
            "user": user, "cards": cards,
            "all_families": sorted({m.family for m in mobs if m.family}),
            "items_catalog": items_catalog,
            "item_categories": item_categories,
            "rarity_colors": _RARITY_COLORS,
            "rarities": ["common", "uncommon", "rare", "epic", "legendary"],
            "element_emojis": ELEMENT_EMOJIS, "element_labels": ELEMENT_LABELS,
            "saved": saved, "err": err,
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def mobs_new_form(
    request: Request,
    user: AdminUser = Depends(require_admin),
):
    with get_db_session() as session:
        item_codes = [it.code for it in ItemRepository(session).list_all()]
    return get_templates().TemplateResponse(
        request, "admin/mobs/form.html",
        context={"user": user, "mob": None, "errors": {},
                 "loot_table_json": "[]", "item_codes": item_codes},
    )


@router.post("")
async def mobs_create(
    request: Request,
    user: AdminUser = Depends(require_admin),
):
    form = await request.form()
    form_data = {k: str(v) for k, v in form.items()}
    errors: dict[str, str] = {}

    code = form_data.get("code", "").strip()
    name = form_data.get("name", "").strip()
    if not code:
        errors["code"] = "Code requis."
    if not name:
        errors["name"] = "Nom requis."

    max_hp = _parse_int(form_data.get("max_hp"), 1)
    if max_hp < 1:
        errors["max_hp"] = "PV max doit être ≥ 1."

    if errors:
        return get_templates().TemplateResponse(
            request, "admin/mobs/form.html",
            context={
                "user": user, "mob": None,
                "form_data": form_data, "errors": errors,
            },
            status_code=400,
        )

    with get_db_session() as session:
        repo = MobRepository(session)
        if repo.get_by_code(code) is not None:
            errors["code"] = f"Le code `{code}` existe déjà."
            return get_templates().TemplateResponse(
                request, "admin/mobs/form.html",
                context={
                    "user": user, "mob": None,
                    "form_data": form_data, "errors": errors,
                },
                status_code=400,
            )

        stats = _clamp_mob_stats(
            max_hp=max_hp,
            attack=_parse_int(form_data.get("attack"), 1),
            defense=_parse_int(form_data.get("defense"), 0),
            speed=_parse_int(form_data.get("speed"), 1),
            crit_chance=_parse_int(form_data.get("crit_chance"), 0),
            crit_damage=_parse_int(form_data.get("crit_damage"), 100),
            dodge=_parse_int(form_data.get("dodge"), 0),
            hp_regeneration=_parse_int(form_data.get("hp_regeneration"), 0),
            xp_reward=_parse_int(form_data.get("xp_reward"), 0),
            gold_reward=_parse_int(form_data.get("gold_reward"), 0),
            spawn_weight=_parse_int(form_data.get("spawn_weight"), 1),
        )
        description = form_data.get("description", "").strip()
        image_name = form_data.get("image_name", "").strip()
        family = form_data.get("family", "").strip() or "unknown"
        element = form_data.get("element", "").strip()
        loot_table = _parse_loot_table(form_data.get("loot_table"))

        # Upload d'image (optionnel) → écrase image_name par le fichier sauvé.
        image_name, asset_path, upload_err = await _save_mob_image(form, code, image_name)
        if upload_err:
            errors["image_file"] = upload_err
            return get_templates().TemplateResponse(
                request, "admin/mobs/form.html",
                context={"user": user, "mob": None, "form_data": form_data, "errors": errors},
                status_code=400,
            )

        repo.create(
            code=code,
            name=name,
            description=description,
            image_name=image_name,
            family=family,
            element=element,
            loot_table=loot_table,
            **stats,
        )

    # Reseed-safe : réécrit aussi mobs.json (sinon le mob est perdu au reseed).
    content_sync.upsert_mob_json(content_sync.build_mob_dict(
        code=code, name=name, family=family, description=description,
        current_hp=stats["max_hp"], image_name=image_name, element=element,
        loot_table=loot_table, **stats,
    ))
    push_paths = ["app/infrastructure/content/mobs.json"]
    if asset_path:
        push_paths.append(asset_path)
    git_sync.push_content(push_paths, f"admin: mob {code} créé")
    return RedirectResponse(f"/admin/mobs?saved={code}#mob-{code}", status_code=303)


@router.get("/{code}/edit")
async def mobs_edit_form(code: str, user: AdminUser = Depends(require_admin)):
    """L'édition se fait désormais en place sur la carte du monstre : on
    redirige vers la carte (deep-link `#mob-<code>`, dépliée à l'arrivée)."""
    return RedirectResponse(f"/admin/mobs#mob-{code}", status_code=303)


@router.post("/{code}")
async def mobs_update(
    code: str, request: Request,
    user: AdminUser = Depends(require_admin),
):
    form = await request.form()
    form_data = {k: str(v) for k, v in form.items()}

    with get_db_session() as session:
        repo = MobRepository(session)
        existing = repo.get_by_code(code)
        if existing is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Mob `{code}` introuvable.",
            )
        stats = _clamp_mob_stats(
            max_hp=_parse_int(form_data.get("max_hp"), existing.max_hp),
            current_hp=_parse_int(form_data.get("current_hp"), existing.current_hp),
            attack=_parse_int(form_data.get("attack"), existing.attack),
            defense=_parse_int(form_data.get("defense"), existing.defense),
            speed=_parse_int(form_data.get("speed"), existing.speed),
            crit_chance=_parse_int(form_data.get("crit_chance"), existing.crit_chance),
            crit_damage=_parse_int(form_data.get("crit_damage"), existing.crit_damage),
            dodge=_parse_int(form_data.get("dodge"), existing.dodge),
            hp_regeneration=_parse_int(form_data.get("hp_regeneration"), existing.hp_regeneration),
            xp_reward=_parse_int(form_data.get("xp_reward"), existing.xp_reward),
            gold_reward=_parse_int(form_data.get("gold_reward"), existing.gold_reward),
            spawn_weight=_parse_int(form_data.get("spawn_weight"), existing.spawn_weight),
        )
        name = form_data.get("name", existing.name)
        description = form_data.get("description", existing.description)
        image_name = form_data.get("image_name", existing.image_name).strip() or existing.image_name
        family = form_data.get("family", existing.family or "").strip() or existing.family
        element = form_data.get("element", existing.element or "").strip()
        loot_table = _parse_loot_table(form_data.get("loot_table"))

        # Upload d'image (optionnel) → écrase image_name par le fichier sauvé.
        image_name, asset_path, upload_err = await _save_mob_image(form, code, image_name)
        if upload_err:
            _logger.warning("Upload image mob %s refusé : %s", code, upload_err)
            return RedirectResponse(f"/admin/mobs?err=upload#mob-{code}", status_code=303)

        repo.update_by_code(
            code=code,
            name=name,
            description=description,
            image_name=image_name,
            family=family,
            element=element,
            loot_table=loot_table,
            **stats,
        )

    # Reseed-safe : réécrit aussi mobs.json.
    content_sync.upsert_mob_json(content_sync.build_mob_dict(
        code=code, name=name, family=family, description=description,
        image_name=image_name, element=element, loot_table=loot_table, **stats,
    ))
    push_paths = ["app/infrastructure/content/mobs.json"]
    if asset_path:
        push_paths.append(asset_path)
    git_sync.push_content(push_paths, f"admin: mob {code} édité")

    # Poids de spawn élémentaires (fichier + push séparés via json_writer).
    with get_db_session() as session:
        updated = MobRepository(session).get_by_code(code)
    if updated is not None:
        _save_mob_weights(code, form_data, _mob_weight_elements(updated))
    return RedirectResponse(f"/admin/mobs?saved={code}#mob-{code}", status_code=303)


@router.post("/{code}/delete")
async def mobs_delete(code: str, user: AdminUser = Depends(require_admin)):
    """Suppression en cascade : retire le mob de la DB (+ compteurs de kills)
    et de mobs.json."""
    from app.application.use_cases.delete_mob import DeleteMobUseCase
    with get_db_session() as session:
        result = DeleteMobUseCase().execute(session, code)
    if not result.deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Mob `{code}` introuvable.")
    touched = content_sync.delete_mob_json(code)
    _logger.info("Admin %s a supprimé le mob %s (kills retirés: %s, json: %s)",
                 user.discord_id, code, result.kills_removed, touched)
    if touched:
        git_sync.push_content([f"app/infrastructure/content/{f}" for f in touched],
                              f"admin: mob {code} supprimé (cascade)")
    return RedirectResponse("/admin/mobs", status_code=303)
