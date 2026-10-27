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
    """Fenêtres de l'élixir de récupération — et de la bénédiction de Sylve
    (offrande commune) — à passer en `boosts=` aux services de régénération
    hors combat (PV et mana). Deux fenêtres qui se chevauchent s'ajoutent."""
    windows = list(PlayerStatusEffectRepository(session).regen_windows(player_id))
    from app.application.use_cases.offering import blessing_window
    from app.infrastructure.db.models.offering_model import OfferingStateModel
    from app.infrastructure.offering.offering_loader import get_deity

    state = session.get(OfferingStateModel, 1)
    deity = get_deity(state.deity_code) if state is not None else None
    window = blessing_window(session)
    if deity is not None and deity.effect == "regen_mult" and window is not None:
        windows.append((window[0], window[1], deity.value))
    return windows
