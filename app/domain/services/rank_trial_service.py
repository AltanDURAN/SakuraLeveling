"""Éligibilité aux épreuves de rang — service PUR.

Le rang d'un joueur est porté par un RÔLE Discord (accès aux zones de farm).
Jusqu'ici il ne pouvait monter que par `/admin set_rank` : la progression de
rang n'était donc pas un système de jeu mais une tâche manuelle.

Une épreuve se déroule en deux temps :
  1. un SEUIL de power score ouvre l'épreuve du rang suivant ;
  2. il faut ensuite BATTRE le gardien en combat solo.

Le seuil dit « tu as la puissance », le combat dit « tu sais t'en servir ».
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GuardianStats:
    name: str
    lore: str
    max_hp: int
    attack: int
    defense: int
    speed: int = 8
    crit_chance: int = 10
    crit_damage: int = 150
    dodge: int = 5


@dataclass(frozen=True)
class RankTrial:
    rank: str
    required_power: int
    guardian: GuardianStats


@dataclass(frozen=True)
class TrialEligibility:
    """Ce que le joueur peut faire, et sinon pourquoi il ne peut pas."""

    trial: RankTrial | None
    current_rank: str
    power: int
    #: None si l'épreuve est ouverte ; sinon la raison du blocage.
    blocked_reason: str | None = None
    missing_power: int = 0

    @property
    def can_attempt(self) -> bool:
        return self.trial is not None and self.blocked_reason is None

    @property
    def at_max_rank(self) -> bool:
        return self.trial is None and self.blocked_reason is None


class RankTrialService:
    def __init__(self, trials: list[RankTrial], rank_order: list[str]) -> None:
        self.trials = {t.rank: t for t in trials}
        self.rank_order = rank_order

    def next_rank(self, current_rank: str) -> str | None:
        """Rang immédiatement supérieur, None si déjà au sommet."""
        try:
            index = self.rank_order.index(current_rank)
        except ValueError:
            # Rang inconnu (rôle retiré à la main) : on repart du plus bas.
            return self.rank_order[0] if self.rank_order else None
        if index + 1 >= len(self.rank_order):
            return None
        return self.rank_order[index + 1]

    def trial_for(self, current_rank: str) -> RankTrial | None:
        nxt = self.next_rank(current_rank)
        return self.trials.get(nxt) if nxt else None

    def evaluate(
        self,
        current_rank: str,
        power: int,
        on_cooldown_until: str | None = None,
    ) -> TrialEligibility:
        trial = self.trial_for(current_rank)
        if trial is None:
            return TrialEligibility(
                trial=None, current_rank=current_rank, power=power,
            )

        if on_cooldown_until:
            return TrialEligibility(
                trial=trial, current_rank=current_rank, power=power,
                blocked_reason=(
                    f"Tu dois reprendre des forces — nouvelle tentative "
                    f"{on_cooldown_until}."
                ),
            )

        if power < trial.required_power:
            missing = trial.required_power - power
            return TrialEligibility(
                trial=trial, current_rank=current_rank, power=power,
                blocked_reason=(
                    f"Puissance insuffisante : {power} / "
                    f"{trial.required_power}."
                ),
                missing_power=missing,
            )

        return TrialEligibility(
            trial=trial, current_rank=current_rank, power=power,
        )
