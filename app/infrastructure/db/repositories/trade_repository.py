from datetime import datetime, UTC, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.entities.trade import Trade, TradeItemOffer, TradeSide, TradeStatus
from app.infrastructure.db.models.item_model import ItemDefinitionModel
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.trade_model import TradeItemModel, TradeModel


class TradeRepository:
    def __init__(self, session: Session):
        self.session = session

    # ---------- création ----------

    def create_pending(
        self,
        initiator_player_id: int,
        target_player_id: int,
        initiator_gold_offered: int,
        target_gold_offered: int,
        items: list[tuple[TradeSide, int, int]],  # (side, item_definition_id, quantity)
        ttl_minutes: int = 5,
    ) -> Trade:
        now = datetime.now(UTC)
        trade = TradeModel(
            initiator_player_id=initiator_player_id,
            target_player_id=target_player_id,
            status=TradeStatus.PENDING.value,
            initiator_gold_offered=initiator_gold_offered,
            target_gold_offered=target_gold_offered,
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(minutes=ttl_minutes),
        )
        self.session.add(trade)
        self.session.flush()

        for side, item_def_id, quantity in items:
            self.session.add(
                TradeItemModel(
                    trade_id=trade.id,
                    offered_by=side.value,
                    item_definition_id=item_def_id,
                    quantity=quantity,
                    created_at=now,
                )
            )
        self.session.commit()
        return self.get_by_id(trade.id)

    # ---------- lecture ----------

    def get_by_id(self, trade_id: int) -> Trade | None:
        model = self.session.get(TradeModel, trade_id)
        if model is None:
            return None
        return self._to_domain(model)

    def list_pending_for_pair(
        self,
        initiator_player_id: int,
        target_player_id: int,
    ) -> list[Trade]:
        stmt = select(TradeModel).where(
            TradeModel.status == TradeStatus.PENDING.value,
            (
                (TradeModel.initiator_player_id == initiator_player_id)
                & (TradeModel.target_player_id == target_player_id)
            )
            | (
                (TradeModel.initiator_player_id == target_player_id)
                & (TradeModel.target_player_id == initiator_player_id)
            ),
        )
        return [self._to_domain(m) for m in self.session.execute(stmt).scalars().all()]

    # ---------- transitions de statut ----------

    def expire_overdue_pending(self) -> int:
        """Marque tous les trades pending dont expires_at est dépassé en
        status=expired. Bulk UPDATE pour efficacité.

        Renvoie le nombre de trades affectés. Idempotent : si appelé deux fois
        de suite, le 2e appel renvoie 0.
        """
        now = datetime.now(UTC)
        # SQLite ne préserve pas tzinfo : on compare avec un datetime naïf
        # pour matcher la sérialisation côté DB. La cohérence est assurée car
        # tout est implicitement UTC (cf. CooldownService._normalize).
        stmt = (
            update(TradeModel)
            .where(TradeModel.status == TradeStatus.PENDING.value)
            .where(TradeModel.expires_at < now)
            .values(status=TradeStatus.EXPIRED.value, updated_at=now)
        )
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount or 0

    def update_status(
        self, trade_id: int, status: TradeStatus, completed: bool = False
    ) -> None:
        trade = self.session.get(TradeModel, trade_id)
        if trade is None:
            return
        now = datetime.now(UTC)
        trade.status = status.value
        trade.updated_at = now
        if completed:
            trade.completed_at = now
        self.session.commit()

    # ---------- conversion en domain ----------

    def _to_domain(self, model: TradeModel) -> Trade:
        initiator = self.session.get(PlayerModel, model.initiator_player_id)
        target = self.session.get(PlayerModel, model.target_player_id)

        items_stmt = select(TradeItemModel).where(
            TradeItemModel.trade_id == model.id
        )
        item_models = self.session.execute(items_stmt).scalars().all()

        items: list[TradeItemOffer] = []
        for item_model in item_models:
            item_def = self.session.get(ItemDefinitionModel, item_model.item_definition_id)
            if item_def is None:
                continue
            items.append(
                TradeItemOffer(
                    item_code=item_def.code,
                    item_name=item_def.name,
                    quantity=item_model.quantity,
                    offered_by=TradeSide(item_model.offered_by),
                )
            )

        return Trade(
            id=model.id,
            initiator_player_id=model.initiator_player_id,
            initiator_discord_id=initiator.discord_id if initiator else 0,
            initiator_display_name=initiator.display_name if initiator else "",
            target_player_id=model.target_player_id,
            target_discord_id=target.discord_id if target else 0,
            target_display_name=target.display_name if target else "",
            status=TradeStatus(model.status),
            initiator_gold_offered=model.initiator_gold_offered,
            target_gold_offered=model.target_gold_offered,
            items=items,
            created_at=model.created_at,
            updated_at=model.updated_at,
            expires_at=model.expires_at,
            completed_at=model.completed_at,
        )
