"""Purge des fichiers PNG générés à la volée (banners, encounters, equip).

Les rendus Pillow s'écrivent sur disque pour être attachés aux messages
Discord. Une fois envoyés, ils ne servent plus — Discord héberge sa propre
copie via le CDN. On purge tout ce qui dépasse un certain âge pour éviter
de saturer `assets/generated_*/` (le dossier encounters peut grossir
indéfiniment sinon : ~2 MB par fichier × 4 turns × N spawns/jour).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def purge_old_files(directory: Path, max_age_seconds: float) -> int:
    """Supprime les fichiers de `directory` plus vieux que `max_age_seconds`.

    Retourne le nombre de fichiers supprimés. Ignore silencieusement les
    fichiers en cours d'écriture ou déjà supprimés. Ne touche pas aux
    sous-dossiers.
    """
    if not directory.exists():
        return 0
    cutoff = time.time() - max_age_seconds
    removed = 0
    for path in directory.iterdir():
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except (FileNotFoundError, PermissionError):
            continue
    if removed:
        logger.info(
            "Purged %d stale files from %s (>%ds old)",
            removed, directory.name, int(max_age_seconds),
        )
    return removed
