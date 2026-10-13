"""Reset de saison — tout le monde repart de zéro (seule l'identité Discord reste).

Usage (sur le VPS, bot ARRÊTÉ de préférence) :

    .venv/bin/python -m scripts.season_reset                       # aperçu, rien n'est modifié
    .venv/bin/python -m scripts.season_reset --confirm "SAISON 1"  # exécute

Avant toute écriture, la base est sauvegardée (API de sauvegarde SQLite,
cohérente même en mode WAL) dans `lita_v2_avant_reset_<date>.db`. Les rôles de
rang Discord sont remis au Rang F par le bot au démarrage suivant (action
`reset_rank_roles` mise en file) — il doit donc tourner après le reset.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from app.application.use_cases.reset_season import preview_season_reset, reset_season
from app.infrastructure.config.settings import settings
from app.infrastructure.db.session import get_db_session

CONFIRMATION = "SAISON 1"


def _import_all_models() -> None:
    """Enregistre TOUS les modèles ORM avant la première requête.

    Le bot le fait implicitement en chargeant ses cogs ; un script isolé non :
    sans ça, SQLAlchemy ne sait pas résoudre les relations entre tables.
    """
    import importlib
    import pkgutil

    import app.infrastructure.db.models as models_pkg

    for module in pkgutil.iter_modules(models_pkg.__path__):
        importlib.import_module(f"{models_pkg.__name__}.{module.name}")


def _sqlite_path() -> Path | None:
    url = settings.database_url
    prefix = "sqlite:///"
    return Path(url[len(prefix):]) if url.startswith(prefix) else None


def _backup() -> Path:
    src = _sqlite_path()
    if src is None or not src.exists():
        sys.exit(f"❌ Base SQLite introuvable ({settings.database_url}) : sauvegarde impossible, arrêt.")
    dst = src.with_name(f"{src.stem}_avant_reset_{datetime.now():%Y%m%d_%H%M%S}{src.suffix}")
    with sqlite3.connect(src) as source, sqlite3.connect(dst) as target:
        source.backup(target)
    return dst


def _print_report(title: str, report) -> None:
    print(title)
    print(f"  joueurs remis à zéro : {report.players}")
    for table, count in report.cleared.items():
        print(f"  {table:<28} {count} ligne(s) effacée(s)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--confirm", default="", help=f'taper exactement "{CONFIRMATION}"')
    args = parser.parse_args()
    _import_all_models()

    with get_db_session() as session:
        preview = preview_season_reset(session)
    if args.confirm != CONFIRMATION:
        _print_report("APERÇU — rien n'a été modifié :", preview)
        print(f'\nPour exécuter : --confirm "{CONFIRMATION}"')
        return

    backup = _backup()
    print(f"💾 Sauvegarde : {backup}")
    with get_db_session() as session:
        report = reset_season(session)
    _print_report("✅ Saison remise à zéro :", report)
    if report.roles_queued:
        print("🎭 Rôles de rang : remise au Rang F en file, exécutée par le bot (≤ 5 s une fois lancé).")


if __name__ == "__main__":
    main()
