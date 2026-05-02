"""Repository pour la brocante (marketplace P2P).

⚠️ Sécurité atomicité : ce repository expose des méthodes individuelles
mais les use cases (create/buy/cancel) doivent enchaîner les opérations
inventaire ↔ listing dans une seule unité de travail (commit final). Les
opérations exposées ici font des commits intermédiaires acceptables car
chacune est elle-même atomique sur une ligne précise.
"""

from datetime import datetime, UTC

from sqlalchemy import select, update
from sqlalchemy.orm import Session, joinedload

from app.domain.entities.marketplace_listing import (
    ListingStatus,
    MarketplaceListing,
)
from app.infrastructure.db.models.marketplace_listing_model import (
    MarketplaceListingModel,
)


class MarketplaceRepository:
    def __init__(self, session: Session):
        self.session = session

    # ---------- create ----------

    def create(
        self,
        seller_player_id: int,
        item_definition_id: int,
        quantity: int,
        price_per_unit: int,
        expires_at: datetime,
    ) -> MarketplaceListing:
        now = datetime.now(UTC)
        model = MarketplaceListingModel(
            seller_player_id=seller_player_id,
            item_definition_id=item_definition_id,
            quantity=quantity,
            price_per_unit=price_per_unit,
            status=ListingStatus.ACTIVE.value,
            listed_at=now,
            expires_at=expires_at,
            closed_at=None,
        )
        self.session.add(model)
        self.session.commit()
        return self._to_domain(model)

    # ---------- read ----------

    def get_by_id(self, listing_id: int) -> MarketplaceListing | None:
        model = self.session.get(MarketplaceListingModel, listing_id)
        return self._to_domain(model) if model else None

    def list_active(
        self, limit: int = 50, item_code: str | None = None
    ) -> list[MarketplaceListing]:
        from app.infrastructure.db.models.item_model import ItemDefinitionModel
        stmt = (
            select(MarketplaceListingModel)
            .where(MarketplaceListingModel.status == ListingStatus.ACTIVE.value)
            .order_by(MarketplaceListingModel.listed_at.desc())
        )
        if item_code is not None:
            stmt = stmt.join(
                ItemDefinitionModel,
                ItemDefinitionModel.id == MarketplaceListingModel.item_definition_id,
            ).where(ItemDefinitionModel.code == item_code)
        stmt = stmt.limit(limit)
        return [
            self._to_domain(m)
            for m in self.session.execute(stmt).scalars().all()
        ]

    def list_active_for_seller(
        self, seller_player_id: int
    ) -> list[MarketplaceListing]:
        stmt = (
            select(MarketplaceListingModel)
            .where(
                MarketplaceListingModel.seller_player_id == seller_player_id,
                MarketplaceListingModel.status == ListingStatus.ACTIVE.value,
            )
            .order_by(MarketplaceListingModel.listed_at.desc())
        )
        return [
            self._to_domain(m)
            for m in self.session.execute(stmt).scalars().all()
        ]

    # ---------- état ----------

    def mark_sold(
        self, listing_id: int, buyer_player_id: int
    ) -> MarketplaceListing | None:
        model = self.session.get(MarketplaceListingModel, listing_id)
        if model is None:
            return None
        model.status = ListingStatus.SOLD.value
        model.last_buyer_player_id = buyer_player_id
        model.closed_at = datetime.now(UTC)
        self.session.commit()
        return self._to_domain(model)

    def mark_cancelled(self, listing_id: int) -> MarketplaceListing | None:
        model = self.session.get(MarketplaceListingModel, listing_id)
        if model is None:
            return None
        model.status = ListingStatus.CANCELLED.value
        model.closed_at = datetime.now(UTC)
        self.session.commit()
        return self._to_domain(model)

    def expire_overdue(self) -> list[MarketplaceListing]:
        """Bulk : marque toutes les listings actifs et dépassés en expired.
        Retourne la liste des listings affectés (pour permettre la restitution
        des items aux vendeurs côté caller)."""
        now = datetime.now(UTC)
        stmt = select(MarketplaceListingModel).where(
            MarketplaceListingModel.status == ListingStatus.ACTIVE.value,
            MarketplaceListingModel.expires_at < now,
        )
        models = list(self.session.execute(stmt).scalars().all())
        for m in models:
            m.status = ListingStatus.EXPIRED.value
            m.closed_at = now
        self.session.commit()
        return [self._to_domain(m) for m in models]

    # ---------- conversion ----------

    def _to_domain(self, model: MarketplaceListingModel) -> MarketplaceListing:
        return MarketplaceListing(
            id=model.id,
            seller_player_id=model.seller_player_id,
            item_definition_id=model.item_definition_id,
            quantity=model.quantity,
            price_per_unit=model.price_per_unit,
            status=ListingStatus(model.status),
            listed_at=model.listed_at,
            expires_at=model.expires_at,
            closed_at=model.closed_at,
            last_buyer_player_id=model.last_buyer_player_id,
        )
