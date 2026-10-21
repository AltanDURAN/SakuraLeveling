import random
from datetime import datetime, UTC

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.domain.services.element_talent_service import ElementTalent, roll_talents
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
        high: int = 10,
    ) -> dict[str, int]:
        """Garantit que le joueur a ses 8 éléments, talents tirés.

        Tout le monde démarre à 0 d'affinité ; le TALENT (caché) règle le
        rythme de progression (cf. element_talent_service). Idempotent : ne
        retire rien si les talents existent déjà. `low`/`high` : ignorés,
        conservés pour compatibilité des appels."""
        self.ensure_talents(player_id, rng)
        return {}

    def ensure_talents(self, player_id: int, rng: random.Random | None = None) -> None:
        """Tire les talents si l'un des 8 éléments manque ou n'est pas tiré
        (nouveau personnage, nouvelle saison). Affinités et essences repartent
        alors de 0."""
        rows = self._rows(player_id)
        codes = [e.value for e in ALL_ELEMENTS]
        if len(rows) == len(codes) and all(r.talent is not None for r in rows.values()):
            return
        talents = roll_talents(rng)
        now = datetime.now(UTC)
        for code in codes:
            t = talents[code]
            row = rows.get(code)
            if row is None:
                row = PlayerElementAffinityModel(
                    player_id=player_id, element=code, created_at=now,
                )
                self.session.add(row)
            row.value = 0
            row.talent = t.talent
            row.affinity_cap = t.cap
            row.revealed = False
            row.updated_at = now
        from app.infrastructure.db.repositories.element_essence_repository import (
            ElementEssenceRepository,
        )
        ElementEssenceRepository(self.session).reset_for_player(player_id)
        self.session.commit()

    def _rows(self, player_id: int) -> dict:
        stmt = select(PlayerElementAffinityModel).where(
            PlayerElementAffinityModel.player_id == player_id,
        )
        return {r.element: r for r in self.session.execute(stmt).scalars().all()}

    def get_talents(self, player_id: int) -> dict[str, ElementTalent]:
        """Talents du joueur (tirés si besoin). Réservé au moteur et aux
        lectures de la voyante : le joueur ne les voit qu'une fois découverts."""
        self.ensure_talents(player_id)
        return {
            code: ElementTalent(
                talent=int(r.talent or 0),
                boosts=max(0, (int(r.affinity_cap) - 100) // 100),
                cap=int(r.affinity_cap),
            )
            for code, r in self._rows(player_id).items()
        }

    def dead_elements(self, player_id: int) -> set[str]:
        """Éléments morts (talent 0) — inutilisables en combat. Ne tire PAS
        de talent (lecture pure, appelée en plein combat)."""
        return {
            code for code, r in self._rows(player_id).items()
            if r.talent is not None and r.talent <= 0
        }

    def revealed_elements(self, player_id: int) -> set[str]:
        return {code for code, r in self._rows(player_id).items() if r.revealed}

    def reveal(self, player_id: int, element: str) -> ElementTalent | None:
        """Marque le talent de l'élément comme découvert et le renvoie."""
        self.ensure_talents(player_id)
        row = self._rows(player_id).get(element)
        if row is None:
            return None
        row.revealed = True
        row.updated_at = datetime.now(UTC)
        self.session.flush()
        return ElementTalent(
            talent=int(row.talent or 0),
            boosts=max(0, (int(row.affinity_cap) - 100) // 100),
            cap=int(row.affinity_cap),
        )

    def set_affinity(self, player_id: int, element: str, value: int) -> None:
        """Définit (upsert) l'affinité d'un élément, bornée par son plafond
        (100, +100 par tirage bonus reçu)."""
        stmt = select(PlayerElementAffinityModel).where(
            PlayerElementAffinityModel.player_id == player_id,
            PlayerElementAffinityModel.element == element,
        )
        row = self.session.execute(stmt).scalar_one_or_none()
        cap = int(row.affinity_cap) if row is not None and row.affinity_cap else 100
        value = max(0, min(cap, value))
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
        self.set_affinity(player_id, element, max(0, current + delta))
        return self.get_affinities(player_id).get(element, 0)

    def reset_for_player(self, player_id: int) -> None:
        self.session.execute(
            delete(PlayerElementAffinityModel).where(
                PlayerElementAffinityModel.player_id == player_id,
            )
        )
        self.session.commit()
