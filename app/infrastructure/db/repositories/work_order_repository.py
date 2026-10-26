"""Maîtrise relationnelle des artisans (Borak, Elna), par joueur.

Elle monte à chaque FUSION (équipement v2). Le nom de la classe vient de
l'époque des commandes de fabrication ; la colonne `orders_completed` compte
désormais les fusions.

Convention des repos récents (cf. audit) : on `flush()` et on laisse
l'appelant committer — la frontière transactionnelle appartient au use case.
"""

from __future__ import annotations

from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.db.models.work_order_model import PlayerArtisanMasteryModel


class WorkOrderRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_mastery(
        self, player_id: int, artisan_code: str,
    ) -> PlayerArtisanMasteryModel | None:
        return self.session.execute(
            select(PlayerArtisanMasteryModel).where(
                PlayerArtisanMasteryModel.player_id == player_id,
                PlayerArtisanMasteryModel.artisan_code == artisan_code,
            )
        ).scalars().first()

    def orders_completed(self, player_id: int, artisan_code: str) -> int:
        row = self.get_mastery(player_id, artisan_code)
        return row.orders_completed if row else 0

    def increment_mastery(
        self, player_id: int, artisan_code: str, gold_spent: int = 0, amount: int = 1,
    ) -> int:
        """+`amount` travaux terminés (une fusion, ou une potion chez
        l'alchimiste). Renvoie le nouveau total."""
        row = self.get_mastery(player_id, artisan_code)
        if row is None:
            row = PlayerArtisanMasteryModel(
                player_id=player_id,
                artisan_code=artisan_code,
                orders_completed=0,
                gold_spent=0,
            )
            self.session.add(row)
        row.orders_completed += max(0, int(amount))
        row.gold_spent += max(0, gold_spent)
        row.updated_at = datetime.now(UTC)
        self.session.flush()
        return row.orders_completed
