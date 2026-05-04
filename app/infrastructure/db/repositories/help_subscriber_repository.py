"""Repository pour la liste des chads (joueurs taguables sur appel à l'aide)."""

from datetime import datetime, UTC

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from app.infrastructure.db.models.help_subscriber_model import HelpSubscriberModel
from app.infrastructure.db.models.player_model import PlayerModel


class HelpSubscriberRepository:
    def __init__(self, session: Session):
        self.session = session

    def is_subscribed(self, player_id: int) -> bool:
        stmt = select(HelpSubscriberModel.id).where(
            HelpSubscriberModel.player_id == player_id
        )
        return self.session.execute(stmt).scalar_one_or_none() is not None

    def subscribe(self, player_id: int) -> bool:
        """Ajoute le joueur. Retourne True si nouveau, False si déjà inscrit."""
        if self.is_subscribed(player_id):
            return False
        self.session.add(
            HelpSubscriberModel(
                player_id=player_id,
                subscribed_at=datetime.now(UTC),
            )
        )
        self.session.commit()
        return True

    def unsubscribe(self, player_id: int) -> bool:
        """Retire le joueur. Retourne True si retiré, False si pas inscrit."""
        if not self.is_subscribed(player_id):
            return False
        self.session.execute(
            delete(HelpSubscriberModel).where(
                HelpSubscriberModel.player_id == player_id
            )
        )
        self.session.commit()
        return True

    def list_all_discord_ids(self) -> list[int]:
        """Retourne les Discord IDs de tous les chads inscrits.
        Utilisé par le bouton 'Demander de l'aide' pour générer les mentions."""
        stmt = (
            select(PlayerModel.discord_id)
            .join(
                HelpSubscriberModel,
                HelpSubscriberModel.player_id == PlayerModel.id,
            )
            .order_by(HelpSubscriberModel.subscribed_at.asc())
        )
        return [row[0] for row in self.session.execute(stmt).all()]
