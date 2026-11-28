"""Portraits des personnages (28/11/2026, demande de l'auteur : déposer les
portraits depuis le site). Une page : Hana, Borak, Elna, Sorn, Ysaline, leur
portrait actuel et où il se voit ; on dépose une image, elle remplace le
portrait (assets/npcs/<fichier>, réduite à 1 024 px, en PNG) et part tout de
suite dans le dépôt. Le bot la lit à chaque affichage : aucun redémarrage. La
carte du personnage suit aussi (sauf si elle a sa propre image)."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from PIL import Image, UnidentifiedImageError

from app.shared.paths import NPCS_ASSETS_DIR
from webapp.admin import git_sync
from webapp.admin._shared import get_templates
from webapp.admin.auth import AdminUser, require_admin
from webapp.admin.uploads import MAX_UPLOAD_BYTES, read_limited

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/npcs", tags=["admin-npcs"])

MAX_SIDE = 1024


@dataclass(frozen=True)
class Npc:
    key: str
    name: str
    role: str
    file: str
    shown: str


NPCS: tuple[Npc, ...] = (
    Npc("hana", "Hana", "Gardienne du Grand Cerisier", "hana.png",
        "Tutoriel (/tuto, panneau du salon tutoriel), sa carte"),
    Npc("borak", "Borak", "Forgeron", "forgeron.png", "/forgeron (fusion), sa carte"),
    Npc("elna", "Elna", "Alchimiste", "alchimiste.png", "/alchimiste (potions), sa carte"),
    Npc("sorn", "Sorn", "Marchand", "marchand.png", "/marchand, sa carte"),
    Npc("ysaline", "Ysaline", "Voyante", "voyante.png", "/voyante, /affinites, sa carte"),
)
BY_KEY = {n.key: n for n in NPCS}


def _version(npc: Npc) -> int:
    path = NPCS_ASSETS_DIR / npc.file
    return int(path.stat().st_mtime) if path.is_file() else 0


def prepare_portrait(data: bytes) -> bytes:
    """L'image déposée telle qu'on la range : PNG, au plus 1 024 px de côté.
    Lève ValueError si ce n'est pas une image."""
    if not data:
        raise ValueError("Aucune image reçue.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"Image trop lourde (max {MAX_UPLOAD_BYTES // (1024 * 1024)} Mo).")
    try:
        with Image.open(io.BytesIO(data)) as source:
            image = source.convert("RGBA" if "A" in source.getbands() else "RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Ce fichier n'est pas une image (PNG, JPG ou WebP).") from exc
    image.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _store(npc: Npc, data: bytes) -> None:
    png = prepare_portrait(data)
    NPCS_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = NPCS_ASSETS_DIR / f".{npc.file}.tmp"
    tmp.write_bytes(png)
    tmp.replace(NPCS_ASSETS_DIR / npc.file)
    git_sync.push_content([f"assets/npcs/{npc.file}"], f"admin: portrait de {npc.name}")


@router.get("")
async def npcs_page(request: Request, user: AdminUser = Depends(require_admin)):
    npcs = [{"npc": n, "version": _version(n), "exists": (NPCS_ASSETS_DIR / n.file).is_file()} for n in NPCS]
    return get_templates().TemplateResponse(request, "admin/npcs/index.html", context={
        "user": user, "npcs": npcs,
        "saved": request.query_params.get("ok"), "error": request.query_params.get("erreur"),
    })


@router.post("/{key}")
async def npc_upload(key: str, request: Request, user: AdminUser = Depends(require_admin)):
    npc = BY_KEY.get(key)
    if npc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Personnage inconnu.")
    form = await request.form()
    upload = form.get("image")
    data = await read_limited(upload) if upload is not None and hasattr(upload, "read") else b""
    try:
        await run_in_threadpool(_store, npc, data)
    except ValueError as exc:
        from urllib.parse import quote
        return RedirectResponse(f"/admin/npcs?erreur={quote(str(exc))}#{npc.key}", status_code=303)
    _logger.info("Admin %s a changé le portrait de %s", user.discord_id, npc.name)
    return RedirectResponse(f"/admin/npcs?ok={npc.key}#{npc.key}", status_code=303)
