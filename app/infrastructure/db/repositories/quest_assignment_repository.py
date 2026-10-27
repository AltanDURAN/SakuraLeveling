"""Assignations de quêtes (quotidiennes ou hebdomadaires) — base commune.

Chaque assignation porte sa quête CONCRÈTE (objectif, cible, quantité tirés
pour le joueur) : la progression se fait par objectif, sans relire le modèle.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from app.infrastructure.db.unit_of_work import commit


class QuestAssignmentRepository:
    #: Modèle SQLAlchemy et nom de sa colonne de période (à définir).
    model = None
    period_column = ""

    def __init__(self, session: Session):
        self.session = session

    def _period(self):
        return getattr(self.model, self.period_column)

    def list_for_player(self, player_id: int, period_start: datetime) -> list:
        stmt = select(self.model).where(
            self.model.player_id == player_id, self._period() == period_start)
        return list(self.session.execute(stmt).scalars().all())

    def has_assignments(self, player_id: int, period_start: datetime) -> bool:
        return bool(self.list_for_player(player_id, period_start))

    def assign(self, player_id: int, period_start: datetime, quests) -> None:
        """`quests` : ConcreteQuest (cf. quest_generation_service)."""
        now = datetime.now(UTC)
        for quest in quests:
            self.session.add(self.model(
                player_id=player_id, **{self.period_column: period_start},
                quest_code=quest.code, name=quest.name, description=quest.description,
                tier=quest.tier, objective_type=quest.objective_type,
                objective_target=quest.target, objective_quantity=quest.quantity,
                progress=0, completed=False, claimed=False, created_at=now, updated_at=now,
            ))
        commit(self.session)

    def add_progress_for(self, player_id: int, period_start: datetime, objective_type: str,
                         amount: int, target: str | None = None) -> list:
        """Fait avancer les quêtes du joueur pour cet objectif (et cette cible :
        une quête sans cible accepte tout). Renvoie celles que CET appel vient
        de terminer."""
        if amount <= 0:
            return []
        done = []
        for model in self.list_for_player(player_id, period_start):
            if model.completed or model.objective_type != objective_type:
                continue
            if model.objective_target and model.objective_target != (target or ""):
                continue
            model.progress = min(model.objective_quantity, model.progress + amount)
            if model.progress >= model.objective_quantity:
                model.completed = True
                done.append(model)
            model.updated_at = datetime.now(UTC)
        commit(self.session)
        return done

    def mark_claimed(self, player_id: int, period_start: datetime, quest_code: str) -> bool:
        for model in self.list_for_player(player_id, period_start):
            if model.quest_code == quest_code and model.completed and not model.claimed:
                model.claimed = True
                model.updated_at = datetime.now(UTC)
                commit(self.session)
                return True
        return False

    def delete_for_player(self, player_id: int) -> None:
        self.session.execute(delete(self.model).where(self.model.player_id == player_id))
        commit(self.session)
