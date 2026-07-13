"""Upload d'assets images depuis l'admin (mob images, décors de zone).

Sauvegarde le fichier dans le bon dossier d'assets (trackés en git → survivent
au déploiement une fois committés) avec un nom SÛR. Validation type + taille."""

from __future__ import annotations

import logging
import re
from pathlib import Path

_logger = logging.getLogger(__name__)

# Extensions d'image autorisées.
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
# Taille max d'un upload (8 Mo) — au-delà on refuse.
MAX_UPLOAD_BYTES = 8 * 1024 * 1024


class UploadError(ValueError):
    """Erreur d'upload (type non autorisé, trop gros, vide)."""


def _slug(value: str) -> str:
    """Nom de fichier sûr : alphanum + _ - uniquement, minuscules."""
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9_-]+", "_", value)
    value = value.strip("_-")
    return value or "asset"


def save_asset_bytes(
    data: bytes,
    original_filename: str,
    dest_dir: Path,
    preferred_stem: str | None = None,
) -> str:
    """Écrit `data` dans `dest_dir` sous un nom sûr et renvoie ce nom de fichier
    (à stocker comme `image_name` / `background`). Lève UploadError si invalide.

    - L'extension vient du fichier uploadé (validée contre ALLOWED_EXTENSIONS).
    - Le radical vient de `preferred_stem` (ex: le code du mob) sinon du nom
      d'origine, slugifié.
    """
    if not data:
        raise UploadError("Fichier vide.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadError(
            f"Fichier trop volumineux ({len(data) // 1024} Ko, max "
            f"{MAX_UPLOAD_BYTES // (1024 * 1024)} Mo)."
        )

    ext = Path(original_filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadError(
            f"Type de fichier non autorisé ({ext or 'inconnu'}). "
            f"Autorisés : {', '.join(sorted(ALLOWED_EXTENSIONS))}."
        )

    stem = _slug(preferred_stem or Path(original_filename or "asset").stem)
    filename = f"{stem}{ext}"

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename
    # Écriture atomique (tmp + rename) pour éviter un fichier partiel servi.
    tmp_path = dest_dir / f".{filename}.tmp"
    tmp_path.write_bytes(data)
    tmp_path.replace(dest_path)
    _logger.info("Asset uploadé : %s (%d Ko)", dest_path, len(data) // 1024)
    return filename
