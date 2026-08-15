"""Génération d'images PARTAGÉE par toutes les surfaces d'upload de l'admin.

Partout où l'admin peut déposer une image (item, monstre, décor de zone/spot,
illustration d'événement), il peut aussi :
  • la **générer** depuis une description (bouton ✨) ;
  • la **télécharger** (simple lien `download` côté template).

Un seul endpoint pour les 4 types : le `kind` détermine la direction artistique
du prompt par défaut, le dossier de destination et le traitement du fond
(transparent pour les monstres, qui sont composités sur un décor).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.shared.paths import (
    EVENTS_ASSETS_DIR,
    ITEMS_ASSETS_DIR,
    LANDSCAPES_ASSETS_DIR,
    MOBS_ASSETS_DIR,
)
from webapp.admin import git_sync, image_gen
from webapp.admin.auth import AdminUser, require_admin
from webapp.admin.uploads import _slug

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/image-gen", tags=["admin-image-gen"])

# kind → (dossier de destination, sous-chemin d'asset, fond transparent ?)
_KINDS = {
    "item": (ITEMS_ASSETS_DIR, "items", False),
    "mob": (MOBS_ASSETS_DIR, "mobs", True),
    "landscape": (LANDSCAPES_ASSETS_DIR, "landscapes", False),
    "event": (EVENTS_ASSETS_DIR, "events", False),
}


@router.post("/{kind}/{code}")
async def generate(
    kind: str, code: str, request: Request,
    user: AdminUser = Depends(require_admin),
):
    """Génère une image et l'écrit dans `assets/<kind>/<code>.png`.

    Body JSON optionnel : `{"prompt": "...", "name": "...", ...}`. Sans prompt,
    on construit celui par défaut du type (cf. `image_gen.build_prompt_for`)."""
    conf = _KINDS.get(kind)
    if conf is None:
        return JSONResponse({"ok": False, "error": f"Type inconnu : {kind}"}, status_code=400)
    dest_dir, asset_sub, transparent = conf

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        payload = {}

    stem = _slug(code)
    if not stem:
        return JSONResponse(
            {"ok": False, "error": "Code manquant : enregistre d'abord l'entité."},
            status_code=400,
        )

    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        prompt = image_gen.build_prompt_for(kind, code=code, **{
            k: str(payload.get(k, "")) for k in ("name", "family", "element", "category", "rarity")
        })

    try:
        png = image_gen.generate_image(prompt, transparent=transparent)
    except image_gen.ImageGenError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)

    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{stem}.png"
    dest = dest_dir / filename
    tmp = dest_dir / f".{filename}.tmp"
    tmp.write_bytes(png)
    tmp.replace(dest)

    git_sync.push_content(
        [f"assets/{asset_sub}/{filename}"],
        f"admin: image générée pour {kind} {stem}",
    )
    _logger.info(
        "Admin %s a généré une image %s pour %s (via %s)",
        user.discord_id, kind, stem, image_gen.active_provider(),
    )
    return JSONResponse({
        "ok": True,
        "filename": filename,
        "url": f"/assets/{asset_sub}/{filename}",
        "prompt": prompt,
        "provider": image_gen.active_provider(),
    })
