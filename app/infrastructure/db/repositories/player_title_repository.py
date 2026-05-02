"""Repository pour les titres débloqués par les joueurs."""

from datetime import datetime, UTC

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.infrastructure.db.models.player_title_model import PlayerTitleModel


class PlayerTitleRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_codes_for_player(self, player_id: int) -> list[str]:
        stmt = select(PlayerTitleModel.title_code).where(
            PlayerTitleModel.player_id == player_id
        )
        return [row[0] for row in self.session.execute(stmt).all()]

    def has_title(self, player_id: int, title_code: str) -> bool:
        stmt = select(PlayerTitleModel.id).where(
            PlayerTitleModel.player_id == player_id,
            PlayerTitleModel.title_code == title_code,
        )
        return self.session.execute(stmt).scalar_one_or_none() is not None

    def unlock(self, player_id: int, title_code: str) -> bool:
        """Crée la ligne si absente. Retourne True si nouveau, False sinon."""
        if self.has_title(player_id, title_code):
            return False
        now = datetime.now(UTC)
        self.session.add(
            PlayerTitleModel(
                player_id=player_id,
                title_code=title_code,
                unlocked_at=now,
                is_active=False,
            )
        )
        self.session.commit()
        return True

    def get_active_title_code(self, player_id: int) -> str | None:
        stmt = select(PlayerTitleModel.title_code).where(
            PlayerTitleModel.player_id == player_id,
            PlayerTitleModel.is_active.is_(True),
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def set_active(self, player_id: int, title_code: str | None) -> bool:
        """Désactive tous les titres puis active celui demandé. Si title_code
        est None, désactive juste l'actif. Retourne True si succès."""
        # 1. Reset tous les actifs
        self.session.execute(
            update(PlayerTitleModel)
            .where(PlayerTitleModel.player_id == player_id)
            .values(is_active=False)
        )

        if title_code is None:
            self.session.commit()
            return True

        # 2. Activer le code demandé (refus si pas débloqué)
        stmt = select(PlayerTitleModel).where(
            PlayerTitleModel.player_id == player_id,
            PlayerTitleModel.title_code == title_code,
        )
        model = self.session.execute(stmt).scalar_one_or_none()
        if model is None:
            self.session.rollback()
            return False
        model.is_active = True
        self.session.commit()
        return True

    def delete_for_player(self, player_id: int) -> None:
        """Supprime toutes les lignes d'un joueur (utilisé par /admin reset_player)."""
        from sqlalchemy import delete
        self.session.execute(
            delete(PlayerTitleModel).where(PlayerTitleModel.player_id == player_id)
        )
        self.session.commit()
