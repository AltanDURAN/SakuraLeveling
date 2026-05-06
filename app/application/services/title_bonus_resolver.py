"""Helper centralisé pour récupérer les bonus de titres d'un joueur.

Évite de plomber tous les callers de StatsService avec la chaîne
PlayerTitleRepository → title_loader → TitleBonusService.aggregate.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.services.title_bonus_service import TitleBonuses, TitleBonusService
from app.infrastructure.db.repositories.player_title_repository import (
    PlayerTitleRepository,
)
from app.infrastructure.titles.title_loader import get_definition as _get_title_def


def resolve_title_bonuses(session: Session, player_id: int) -> TitleBonuses:
    """Charge tous les titres débloqués du joueur (peu importe `is_active`)
    et retourne l'agrégation de leurs bonus passifs."""
    codes = PlayerTitleRepository(session).list_codes_for_player(player_id)
    titles = []
    for code in codes:
        defn = _get_title_def(code)
        if defn is not None:
            titles.append(defn)
    return TitleBonusService().aggregate(titles)
