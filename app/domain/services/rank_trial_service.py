"""Éligibilité aux épreuves de rang — service PUR.

Le rang d'un joueur est porté par un RÔLE Discord (accès aux zones de farm).
Jusqu'ici il ne pouvait monter que par `/admin set_rank` : la progression de
rang n'était donc pas un système de jeu mais une tâche manuelle.

Une épreuve se déroule en deux temps :
  1. un SEUIL de power score ouvre l'épreuve du rang suivant ;
  2. il faut ensuite réussir l'épreuve de SON rôle face au gardien.

Le seuil dit « tu as la puissance », l'épreuve dit « tu sais t'en servir ».

Depuis le 26/10/2026 (décision de l'auteur), l'épreuve reprend les trois
épreuves des défis (`role_trial_service`), face au gardien et au niveau du
rang : ⚔️ DPS (dégâts infligés en 40 s), 🛡️ Tank (dégâts encaissés avant de
tomber), 💚 Soutien (PV soignés avant la chute de la recrue). Le joueur choisit
son rôle ; il est promu si son score atteint celui du rang (`thresholds`).
Avant, il fallait ABATTRE le gardien en 60 actions : une course aux dégâts —
mesuré, un pur soutien restait bloqué au rang D et un pur tank au rang B.
"""

from __future__ import annotations

from dataclasses import dataclass


#: Ce que chaque rôle doit faire face au gardien (texte joueur).
ROLE_GOALS: dict[str, str] = {
    "dps": "inflige {n} dégâts en 40 secondes — il ne riposte pas",
    "tank": "encaisse {n} dégâts avant de tomber — il frappe fort et s'énerve",
    "soutien": "soigne {n} PV avant que la recrue ne tombe — il ne frappe qu'elle",
}


@dataclass(frozen=True)
class GuardianStats:
    name: str
    lore: str


@dataclass(frozen=True)
class RankTrial:
    rank: str
    required_power: int
    guardian: GuardianStats
    #: Niveau du rang : celui du gardien et de la recrue.
    level: int = 1
    #: Score requis par rôle (« dps », « tank », « soutien ») ; un rôle absent
    #: ou à 0 n'est pas proposé à ce rang (ex. Soutien avant de savoir soigner).
    thresholds: dict = None

    def roles(self) -> list[str]:
        """Rôles proposés à ce rang, dans l'ordre DPS, Tank, Soutien."""
        return [r for r in ROLE_GOALS if (self.thresholds or {}).get(r, 0) > 0]

    def passed(self, role: str, score: int) -> bool:
        required = (self.thresholds or {}).get(role, 0)
        return required > 0 and score >= required


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
