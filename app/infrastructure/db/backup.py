"""Sauvegarde de la base SQLite avant une opération irréversible (reset de
saison).

API de sauvegarde de SQLite : la copie est cohérente même en mode WAL et
pendant que le bot écrit (un `cp` du fichier ne l'est pas).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from app.infrastructure.config.settings import settings


class BackupError(RuntimeError):
    pass


def sqlite_path(url: str | None = None) -> Path | None:
    url = url or settings.database_url
    prefix = "sqlite:///"
    return Path(url[len(prefix):]) if url.startswith(prefix) else None


def backup_sqlite(label: str, url: str | None = None) -> Path:
    """Copie la base à côté d'elle (`<base>_<label>_<date>.db`) et renvoie le
    chemin. Lève `BackupError` si ce n'est pas une base SQLite sur disque."""
    src = sqlite_path(url)
    if src is None or not src.exists():
        raise BackupError(f"Base SQLite introuvable ({url or settings.database_url}) : sauvegarde impossible.")
    dst = src.with_name(f"{src.stem}_{label}_{datetime.now():%Y%m%d_%H%M%S}{src.suffix}")
    source, target = sqlite3.connect(src), sqlite3.connect(dst)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return dst
