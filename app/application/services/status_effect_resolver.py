"""Helper centralisé pour récupérer les effets temporaires (buff/debuff) d'un
joueur — calqué sur `resolve_title_bonuses`. À appeler partout où on calcule
les stats (profil, combats, leaderboard, admin) pour que les buff/debuff soient
pris en compte.

Les ÉLIXIRS d'Elna (+ATK, +DEF, +PV) ne comptent qu'en combat de zone et au
world boss (`elixirs=True`) — jamais dans les épreuves de rang, les défis ni le
rang affiché : sinon ce serait une course à l'or (décision de l'auteur,
26/10/2026).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.services.status_effect_service import StatusEffectService
from app.domain.value_objects.status_effect_bonuses import StatusEffectBonuses
from app.infrastructure.db.repositories.player_status_effect_repository import (
    PlayerStatusEffectRepository,
)


def resolve_status_effects(session: Session, player_id: int, *,
                           elixirs: bool = False) -> StatusEffectBonuses:
    repo = PlayerStatusEffectRepository(session)
    active_elixirs = (
        {kind: e.multiplier for kind, e in repo.list_active_elixirs(player_id).items()}
        if elixirs else None
    )
    return StatusEffectService().aggregate(repo.list_active_multipliers(player_id), active_elixirs)


def resolve_regen_boosts(session: Session, player_id: int) -> list:
    """Fenêtres de l'élixir de récupération, à passer en `boosts=` aux
    services de régénération hors combat (PV et mana)."""
    return PlayerStatusEffectRepository(session).regen_windows(player_id)
