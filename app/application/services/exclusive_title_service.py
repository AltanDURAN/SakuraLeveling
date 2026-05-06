"""Service de gestion des titres exclusifs (1 seul détenteur à la fois).

Couvre les titres `champion_1v1` (rang 1 du ladder) et `farmer_fou` (record
absolu de kills). Le mécanisme est uniforme :
    - `award_to(title_code, new_holder_id)` retire le titre à TOUS les
      autres joueurs (y compris s'il était actif visible) puis le donne au
      nouveau détenteur. Idempotent si le détenteur est déjà le bon.

Pour les titres "record battu" (Farmer Fou), un appel `transfer_record(...)`
plus opinionated regarde le top du leaderboard et ne transfère que si le
candidat dépasse strictement le détenteur actuel (égalité ⇒ pas de transfert,
le premier arrivé garde).

Les récupérations de "qui détient ?" sont basées sur la table `player_titles`
(le titre est marqué unlocked + éventuellement is_active). Pas besoin d'une
table séparée — on garantit l'unicité au niveau application.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.infrastructure.db.models.player_title_model import PlayerTitleModel


class ExclusiveTitleService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def current_holder(self, title_code: str) -> int | None:
        """Renvoie le player_id du détenteur actuel, ou None s'il n'y en a pas."""
        stmt = select(PlayerTitleModel.player_id).where(
            PlayerTitleModel.title_code == title_code
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def award_to(self, title_code: str, new_holder_id: int) -> bool:
        """Donne le titre exclusif au joueur indiqué, en le retirant à tous
        les autres détenteurs. Renvoie True si un changement a eu lieu,
        False si `new_holder_id` était déjà le détenteur (no-op).

        Si l'un des détenteurs déchus avait le titre comme `is_active`
        (visible dans /profile), il sera nettoyé du même coup — la ligne
        est supprimée donc `get_active_title_code` retombera sur None.
        """
        current = self.current_holder(title_code)
        if current == new_holder_id:
            return False

        # Retire à tous les anciens détenteurs (même s'il y en avait
        # plusieurs en cas d'incohérence).
        self.session.execute(
            delete(PlayerTitleModel).where(
                PlayerTitleModel.title_code == title_code,
                PlayerTitleModel.player_id != new_holder_id,
            )
        )

        # Vérifie que le nouveau ne le possède pas déjà (cas où plusieurs
        # rows existaient — defensive). Si pas, l'ajoute via la même
        # mécanique que PlayerTitleRepository.unlock.
        from datetime import UTC, datetime

        already_has = self.session.execute(
            select(PlayerTitleModel.id).where(
                PlayerTitleModel.player_id == new_holder_id,
                PlayerTitleModel.title_code == title_code,
            )
        ).scalar_one_or_none()
        if already_has is None:
            self.session.add(
                PlayerTitleModel(
                    player_id=new_holder_id,
                    title_code=title_code,
                    unlocked_at=datetime.now(UTC),
                    is_active=False,
                )
            )

        self.session.commit()
        return True

    def revoke(self, title_code: str) -> bool:
        """Retire le titre à tout le monde (utilisé quand on n'a pas de
        successeur — ex : ladder 1v1 vide). Renvoie True si suppression."""
        result = self.session.execute(
            delete(PlayerTitleModel).where(PlayerTitleModel.title_code == title_code)
        )
        self.session.commit()
        return (result.rowcount or 0) > 0
