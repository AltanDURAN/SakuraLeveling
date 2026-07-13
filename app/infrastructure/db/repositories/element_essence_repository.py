from datetime import datetime, UTC

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.infrastructure.db.models.element_essence_model import PlayerElementEssenceModel
from app.shared.enums import ALL_ELEMENTS


class ElementEssenceRepository:
    """Compteur d'essences élémentaires par joueur (miroir du repo d'affinités).

    Le `count` stocké = essences restantes après conversion en affinité
    (progression vers le palier suivant)."""

    def __init__(self, session: Session):
        self.session = session

    def get_essences(self, player_id: int) -> dict[str, int]:
        """Renvoie {element_value: essences} pour le joueur. Manquants = 0."""
        stmt = select(PlayerElementEssenceModel).where(
            PlayerElementEssenceModel.player_id == player_id,
        )
        rows = self.session.execute(stmt).scalars().all()
        out = {e.value: 0 for e in ALL_ELEMENTS}
        for row in rows:
            out[row.element] = row.count
        return out

    def set_essence(self, player_id: int, element: str, count: int) -> None:
        """Définit (upsert) le compteur d'essences d'un élément (borné ≥ 0)."""
        count = max(0, count)
        stmt = select(PlayerElementEssenceModel).where(
            PlayerElementEssenceModel.player_id == player_id,
            PlayerElementEssenceModel.element == element,
        )
        row = self.session.execute(stmt).scalar_one_or_none()
        now = datetime.now(UTC)
        if row is None:
            self.session.add(
                PlayerElementEssenceModel(
                    player_id=player_id,
                    element=element,
                    count=count,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            row.count = count
            row.updated_at = now
        self.session.commit()

    def reset_for_player(self, player_id: int) -> None:
        self.session.execute(
            delete(PlayerElementEssenceModel).where(
                PlayerElementEssenceModel.player_id == player_id,
            )
        )
        self.session.commit()
