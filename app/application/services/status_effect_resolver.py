"""Helper centralisé pour récupérer les effets temporaires (buff/debuff) d'un
joueur — calqué sur `resolve_title_bonuses`. À appeler partout où on calcule
les stats (profil, combats, leaderboard, admin) pour que les buff/debuff soient
pris en compte."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.services.status_effect_service import StatusEffectService
from app.domain.value_objects.status_effect_bonuses import StatusEffectBonuses
from app.infrastructure.db.repositories.player_status_effect_repository import (
    PlayerStatusEffectRepository,
)


def resolve_status_effects(session: Session, player_id: int) -> StatusEffectBonuses:
    multipliers = PlayerStatusEffectRepository(session).list_active_multipliers(
        player_id
    )
    return StatusEffectService().aggregate(multipliers)
