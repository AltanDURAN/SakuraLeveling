from datetime import datetime, UTC

from sqlalchemy.orm import Session

from app.domain.entities.player_career_stats import PlayerCareerStats
from app.infrastructure.db.models.player_career_stats_model import PlayerCareerStatsModel


class PlayerCareerStatsRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_or_create(self, player_id: int) -> PlayerCareerStats:
        model = self.session.get(PlayerCareerStatsModel, player_id)
        if model is None:
            now = datetime.now(UTC)
            model = PlayerCareerStatsModel(
                player_id=player_id,
                gold_earned_total=0,
                damage_dealt_total=0,
                damage_tanked_total=0,
                hp_healed_total=0,
                dodges_total=0,
                combats_fought=0,
                combats_won=0,
                combats_lost=0,
                created_at=now,
                updated_at=now,
            )
            self.session.add(model)
            self.session.commit()
            self.session.refresh(model)
        return self._to_domain(model)

    def add(
        self,
        player_id: int,
        *,
        gold_earned: int = 0,
        damage_dealt: int = 0,
        damage_tanked: int = 0,
        hp_healed: int = 0,
        dodges: int = 0,
        combats_fought: int = 0,
        combats_won: int = 0,
        combats_lost: int = 0,
    ) -> None:
        """Incrémente atomiquement plusieurs compteurs. Crée la ligne si absente."""
        model = self.session.get(PlayerCareerStatsModel, player_id)
        now = datetime.now(UTC)

        if model is None:
            model = PlayerCareerStatsModel(
                player_id=player_id,
                gold_earned_total=0,
                damage_dealt_total=0,
                damage_tanked_total=0,
                hp_healed_total=0,
                dodges_total=0,
                combats_fought=0,
                combats_won=0,
                combats_lost=0,
                created_at=now,
                updated_at=now,
            )
            self.session.add(model)

        if gold_earned:
            model.gold_earned_total = (model.gold_earned_total or 0) + gold_earned
        if damage_dealt:
            model.damage_dealt_total = (model.damage_dealt_total or 0) + damage_dealt
        if damage_tanked:
            model.damage_tanked_total = (model.damage_tanked_total or 0) + damage_tanked
        if hp_healed:
            model.hp_healed_total = (model.hp_healed_total or 0) + hp_healed
        if dodges:
            model.dodges_total = (model.dodges_total or 0) + dodges
        if combats_fought:
            model.combats_fought = (model.combats_fought or 0) + combats_fought
        if combats_won:
            model.combats_won = (model.combats_won or 0) + combats_won
        if combats_lost:
            model.combats_lost = (model.combats_lost or 0) + combats_lost

        model.updated_at = now
        self.session.commit()

    def reset_for_player(self, player_id: int) -> None:
        model = self.session.get(PlayerCareerStatsModel, player_id)
        if model is None:
            return
        self.session.delete(model)
        self.session.commit()

    def _to_domain(self, model: PlayerCareerStatsModel) -> PlayerCareerStats:
        return PlayerCareerStats(
            player_id=model.player_id,
            gold_earned_total=model.gold_earned_total,
            damage_dealt_total=model.damage_dealt_total,
            damage_tanked_total=model.damage_tanked_total,
            hp_healed_total=model.hp_healed_total,
            dodges_total=model.dodges_total or 0,
            combats_fought=model.combats_fought,
            combats_won=model.combats_won,
            combats_lost=model.combats_lost,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
