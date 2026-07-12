from dataclasses import dataclass
from datetime import datetime


@dataclass
class PlayerManaState:
    """Mana COURANT d'un joueur (miroir de PlayerHealthState pour les PV).

    Le mana courant vit ici, pas sur `Player`. Il descend à chaque compétence
    active lancée en combat et remonte HORS combat via `ManaRegenerationService`
    selon le temps écoulé (mana_regeneration/minute)."""

    player_id: int
    current_mana: int
    updated_at: datetime
