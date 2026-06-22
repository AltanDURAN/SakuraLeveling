import random
from datetime import datetime, UTC

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.infrastructure.db.models.element_affinity_model import PlayerElementAffinityModel
from app.shared.enums import ALL_ELEMENTS


class ElementAffinityRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_affinities(self, player_id: int) -> dict[str, int]:
        """Renvoie {element_value: affinité} pour le joueur. Manquants = 0."""
        stmt = select(PlayerElementAffinityModel).where(
            PlayerElementAffinityModel.player_id == player_id,
        )
        rows = self.session.execute(stmt).scalars().all()
        out = {e.value: 0 for e in ALL_ELEMENTS}
        for row in rows:
            out[row.element] = row.value
        return out

    def init_for_player(
        self,
        player_id: int,
        rng: random.Random | None = None,
        low: int = 0,
        high: int = 100,
    ) -> dict[str, int]:
        """Tire une affinité aléatoire (low..high) par élément pour un nouveau
        joueur. Idempotent : ne touche pas aux éléments déjà présents."""
        rng = rng or random
        existing = {
            row.element
            for row in self.session.execute(
                select(PlayerElementAffinityModel.element).where(
                    PlayerElementAffinityModel.player_id == player_id,
                )
            )
        }
        now = datetime.now(UTC)
        created: dict[str, int] = {}
        for elem in ALL_ELEMENTS:
            if elem.value in existing:
                continue
            value = rng.randint(low, high)
            self.session.add(
                PlayerElementAffinityModel(
                    player_id=player_id,
                    element=elem.value,
                    value=value,
                    created_at=now,
                    updated_at=now,
                )
            )
            created[elem.value] = value
        if created:
            self.session.commit()
        return created

    def set_affinity(self, player_id: int, element: str, value: int) -> None:
        """Définit (upsert) l'affinité d'un élément. Bornée 0..100."""
        value = max(0, min(100, value))
        stmt = select(PlayerElementAffinityModel).where(
            PlayerElementAffinityModel.player_id == player_id,
            PlayerElementAffinityModel.element == element,
        )
        row = self.session.execute(stmt).scalar_one_or_none()
        now = datetime.now(UTC)
        if row is None:
            self.session.add(
                PlayerElementAffinityModel(
                    player_id=player_id,
                    element=element,
                    value=value,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            row.value = value
            row.updated_at = now
        self.session.commit()

    def add_affinity(self, player_id: int, element: str, delta: int) -> int:
        """Incrémente (item d'affinité / admin). Renvoie la nouvelle valeur."""
        current = self.get_affinities(player_id).get(element, 0)
        new_value = max(0, min(100, current + delta))
        self.set_affinity(player_id, element, new_value)
        return new_value

    def reset_for_player(self, player_id: int) -> None:
        self.session.execute(
            delete(PlayerElementAffinityModel).where(
                PlayerElementAffinityModel.player_id == player_id,
            )
        )
        self.session.commit()
