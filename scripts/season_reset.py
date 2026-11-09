"""Reset de saison — tout le monde repart de zéro (seule l'identité Discord reste).

Depuis Discord, c'est `/admin lancer_saison` (aperçu, confirmation, annonce) ;
ce script est le recours si le bot ne tourne pas.

Usage (sur le VPS, bot ARRÊTÉ de préférence) :

    .venv/bin/python -m scripts.season_reset                       # aperçu, rien n'est modifié
    .venv/bin/python -m scripts.season_reset --confirm "SAISON 1"  # exécute
    .venv/bin/python -m scripts.season_reset --saison 2 --confirm "SAISON 2"

Avant toute écriture, la base est sauvegardée (API de sauvegarde SQLite,
cohérente même en mode WAL) dans `lita_v2_avant_saison_<N>_<date>.db`. Tout le
monde repart du règlement : les rangs et le rôle Aventurier sont retirés à
chaque membre par le bot au démarrage suivant (action `reset_journey_roles`
mise en file) — il doit donc tourner après le reset.
"""

from __future__ import annotations

import argparse
import sys

from app.application.use_cases.reset_season import preview_season_reset, reset_season
from app.infrastructure.db.backup import BackupError, backup_sqlite
from app.infrastructure.db.session import get_db_session


def confirmation(season: int) -> str:
    return f"SAISON {season}"


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


def _print_report(title: str, report) -> None:
    print(title)
    print(f"  joueurs remis à zéro : {report.players}")
    for table, count in report.cleared.items():
        print(f"  {table:<28} {count} ligne(s) effacée(s)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--saison", type=int, default=1, help="numéro de la saison qui commence")
    parser.add_argument("--confirm", default="", help='taper exactement "SAISON <numéro>"')
    args = parser.parse_args()
    _import_all_models()
    expected = confirmation(args.saison)

    with get_db_session() as session:
        preview = preview_season_reset(session)
    if args.confirm != expected:
        _print_report("APERÇU — rien n'a été modifié :", preview)
        print(f'\nPour exécuter : --confirm "{expected}"')
        return

    try:
        backup = backup_sqlite(f"avant_saison_{args.saison}")
    except BackupError as exc:
        sys.exit(f"❌ {exc} Arrêt.")
    print(f"💾 Sauvegarde : {backup}")
    with get_db_session() as session:
        report = reset_season(session, season=args.saison)
    _print_report("✅ Saison remise à zéro :", report)
    if report.roles_queued:
        print("🧭 Retour au règlement : rangs et Aventurier retirés à tous par le bot (≤ 5 s une fois lancé).")


if __name__ == "__main__":
    main()
