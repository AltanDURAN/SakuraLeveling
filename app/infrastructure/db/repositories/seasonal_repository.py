"""Événements saisonniers : cases prises, achats en boutique d'événement,
annonces postées (cf. `seasonal_model`)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.db.models.event_model import ActiveEventModel, EventParticipationModel
from app.infrastructure.db.models.seasonal_model import (
    EventShopPurchaseModel,
    SeasonalAnnouncementModel,
    SeasonalClaimModel,
)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class SeasonalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------- prises
    def claim_keys(self, player_id: int, event_code: str) -> set[str]:
        rows = self.session.execute(
            select(SeasonalClaimModel.claim_key).where(
                SeasonalClaimModel.player_id == player_id, SeasonalClaimModel.event_code == event_code)
        ).scalars()
        return set(rows)

    def has_claimed(self, player_id: int, event_code: str, claim_key: str) -> bool:
        return self.session.execute(
            select(SeasonalClaimModel.id).where(
                SeasonalClaimModel.player_id == player_id, SeasonalClaimModel.event_code == event_code,
                SeasonalClaimModel.claim_key == claim_key)
        ).first() is not None

    def add_claim(self, player_id: int, event_code: str, claim_key: str, payload: dict | None = None,
                  now: datetime | None = None) -> None:
        self.session.add(SeasonalClaimModel(
            player_id=player_id, event_code=event_code, claim_key=claim_key,
            claimed_at=(now or datetime.now(UTC)).astimezone(UTC).replace(tzinfo=None),
            payload_json=json.dumps(payload or {}, ensure_ascii=False)))
        self.session.flush()

    def claim_counts(self, event_code: str) -> dict[str, int]:
        """Nombre de joueurs par clé (site admin)."""
        rows = self.session.execute(
            select(SeasonalClaimModel.claim_key, func.count())
            .where(SeasonalClaimModel.event_code == event_code)
            .group_by(SeasonalClaimModel.claim_key)
        ).all()
        return {key: int(n) for key, n in rows}

    # ------------------------------------------------------- gentillesse
    def little_girl_choices(self, player_id: int, before: datetime) -> dict[str, int]:
        """Choix du joueur face à la petite fille (« aider » / « ignorer »)
        pour les apparitions d'AVANT `before` (UTC)."""
        rows = self.session.execute(
            select(EventParticipationModel.choice, func.count())
            .join(ActiveEventModel, ActiveEventModel.id == EventParticipationModel.event_id)
            .where(EventParticipationModel.player_id == player_id,
                   ActiveEventModel.event_type == "little_girl",
                   ActiveEventModel.created_at < before.astimezone(UTC).replace(tzinfo=None))
            .group_by(EventParticipationModel.choice)
        ).all()
        return {choice: int(n) for choice, n in rows}

    # ------------------------------------------------------------ boutique
    def purchases(self, player_id: int, shop_code: str) -> dict[str, int]:
        rows = self.session.execute(
            select(EventShopPurchaseModel.item_code, EventShopPurchaseModel.quantity).where(
                EventShopPurchaseModel.player_id == player_id, EventShopPurchaseModel.shop_code == shop_code)
        ).all()
        return {code: int(qty) for code, qty in rows}

    def add_purchase(self, player_id: int, shop_code: str, item_code: str, quantity: int) -> None:
        row = self.session.get(EventShopPurchaseModel, (player_id, shop_code, item_code))
        if row is None:
            row = EventShopPurchaseModel(player_id=player_id, shop_code=shop_code, item_code=item_code, quantity=0)
            self.session.add(row)
        row.quantity = int(row.quantity or 0) + int(quantity)
        row.updated_at = _now()
        self.session.flush()

    def shop_sales(self, shop_code: str) -> dict[str, tuple[int, int]]:
        """Par article : (exemplaires vendus, acheteurs) — site admin."""
        rows = self.session.execute(
            select(EventShopPurchaseModel.item_code, func.sum(EventShopPurchaseModel.quantity), func.count())
            .where(EventShopPurchaseModel.shop_code == shop_code)
            .group_by(EventShopPurchaseModel.item_code)
        ).all()
        return {code: (int(qty or 0), int(n)) for code, qty, n in rows}

    # ------------------------------------------------------------ annonces
    def announced(self) -> set[str]:
        return set(self.session.execute(select(SeasonalAnnouncementModel.key)).scalars())

    def mark_announced(self, key: str, channel_id: int | None = None, message_id: int | None = None) -> None:
        row = self.session.get(SeasonalAnnouncementModel, key)
        if row is None:
            row = SeasonalAnnouncementModel(key=key)
            self.session.add(row)
        row.posted_at = _now()
        row.channel_id = channel_id
        row.message_id = message_id
        self.session.flush()

    def get_announcement(self, key: str) -> SeasonalAnnouncementModel | None:
        return self.session.get(SeasonalAnnouncementModel, key)
