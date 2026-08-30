"""Accès aux commandes d'artisan et à la maîtrise.

Convention des repos récents (cf. audit) : on `flush()` et on laisse
l'appelant committer — la frontière transactionnelle appartient au use case.
"""

from __future__ import annotations

from datetime import datetime, timedelta, UTC

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.infrastructure.db.models.work_order_model import (
    PlayerArtisanMasteryModel,
    PlayerWorkOrderModel,
    STATUS_CANCELLED,
    STATUS_COLLECTED,
    STATUS_IN_PROGRESS,
    STATUS_READY,
)

ACTIVE_STATUSES = (STATUS_IN_PROGRESS, STATUS_READY)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite rend des datetimes naïfs — on les recolle en UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class WorkOrderRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------ lecture --
    def get_active(
        self, player_id: int, artisan_code: str,
    ) -> PlayerWorkOrderModel | None:
        return self.session.execute(
            select(PlayerWorkOrderModel).where(
                PlayerWorkOrderModel.player_id == player_id,
                PlayerWorkOrderModel.artisan_code == artisan_code,
                PlayerWorkOrderModel.status.in_(ACTIVE_STATUSES),
            )
        ).scalars().first()

    def list_active_for_player(self, player_id: int) -> list[PlayerWorkOrderModel]:
        return list(
            self.session.execute(
                select(PlayerWorkOrderModel).where(
                    PlayerWorkOrderModel.player_id == player_id,
                    PlayerWorkOrderModel.status.in_(ACTIVE_STATUSES),
                )
            ).scalars()
        )

    def get_by_id(self, order_id: int) -> PlayerWorkOrderModel | None:
        return self.session.get(PlayerWorkOrderModel, order_id)

    # ------------------------------------------------------------ écriture --
    def create(
        self,
        *,
        player_id: int,
        artisan_code: str,
        recipe_code: str,
        result_item_definition_id: int,
        result_quantity: int,
        gold_paid: int,
        item_power: int,
        duration_seconds: int,
        notify_channel_id: int = 0,
    ) -> PlayerWorkOrderModel:
        now = datetime.now(UTC)
        ready_at = now + timedelta(seconds=max(0, duration_seconds))
        order = PlayerWorkOrderModel(
            player_id=player_id,
            artisan_code=artisan_code,
            recipe_code=recipe_code,
            result_item_definition_id=result_item_definition_id,
            result_quantity=result_quantity,
            # Un travail instantané naît déjà prêt : pas d'aller-retour inutile
            # par la boucle de complétion.
            status=STATUS_READY if duration_seconds <= 0 else STATUS_IN_PROGRESS,
            gold_paid=gold_paid,
            item_power=item_power,
            started_at=now,
            ready_at=ready_at,
            notify_channel_id=notify_channel_id,
            notified=1 if duration_seconds <= 0 else 0,
        )
        self.session.add(order)
        self.session.flush()
        return order

    def mark_ready_due(self) -> list[PlayerWorkOrderModel]:
        """Passe en « prêt » les travaux dont l'échéance est atteinte et renvoie
        ceux qu'il reste à annoncer. Idempotent : survit à un redémarrage."""
        now = datetime.now(UTC)
        self.session.execute(
            update(PlayerWorkOrderModel)
            .where(
                PlayerWorkOrderModel.status == STATUS_IN_PROGRESS,
                PlayerWorkOrderModel.ready_at <= now,
            )
            .values(status=STATUS_READY)
        )
        self.session.flush()
        return list(
            self.session.execute(
                select(PlayerWorkOrderModel).where(
                    PlayerWorkOrderModel.status == STATUS_READY,
                    PlayerWorkOrderModel.notified == 0,
                )
            ).scalars()
        )

    def mark_notified(self, order_id: int) -> None:
        self.session.execute(
            update(PlayerWorkOrderModel)
            .where(PlayerWorkOrderModel.id == order_id)
            .values(notified=1)
        )
        self.session.flush()

    def mark_collected(self, order_id: int) -> None:
        self.session.execute(
            update(PlayerWorkOrderModel)
            .where(PlayerWorkOrderModel.id == order_id)
            .values(status=STATUS_COLLECTED, collected_at=datetime.now(UTC))
        )
        self.session.flush()

    def mark_cancelled(self, order_id: int) -> None:
        self.session.execute(
            update(PlayerWorkOrderModel)
            .where(PlayerWorkOrderModel.id == order_id)
            .values(status=STATUS_CANCELLED, collected_at=datetime.now(UTC))
        )
        self.session.flush()

    # ------------------------------------------------------------ maîtrise --
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

    def all_mastery_for_player(self, player_id: int) -> dict[str, int]:
        rows = self.session.execute(
            select(PlayerArtisanMasteryModel).where(
                PlayerArtisanMasteryModel.player_id == player_id,
            )
        ).scalars()
        return {r.artisan_code: r.orders_completed for r in rows}

    def increment_mastery(
        self, player_id: int, artisan_code: str, gold_spent: int = 0,
    ) -> int:
        """+1 commande terminée. Renvoie le nouveau total."""
        row = self.get_mastery(player_id, artisan_code)
        if row is None:
            row = PlayerArtisanMasteryModel(
                player_id=player_id,
                artisan_code=artisan_code,
                orders_completed=0,
                gold_spent=0,
            )
            self.session.add(row)
        row.orders_completed += 1
        row.gold_spent += max(0, gold_spent)
        row.updated_at = datetime.now(UTC)
        self.session.flush()
        return row.orders_completed
