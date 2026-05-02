"""Bonus de stats accordé aux joueurs participants à un raid de world boss.

Spec : "plus il y a de joueur qui participe plus il gagne un léger bonus
de stats, pour favoriser les raid par équipe". Concrètement, **chaque
joueur** voit ses stats boostées pendant son combat solo contre le boss
en fonction du nombre total de participants inscrits à la session.

Formule (V1) : +5% par participant additionnel, capé à +50% (10 joueurs).
S'applique multiplicativement à attack, defense, max_hp. Speed/crit/dodge
ne sont PAS boostés (ce sont des stats "tactiques" qui n'ont pas vocation
à scaler avec le nombre de participants).
"""

from app.domain.value_objects.stats import Stats


class WorldBossScalingService:
    BONUS_PER_PARTICIPANT = 0.05  # +5% par joueur additionnel
    MAX_BONUS = 0.50  # capé à +50%

    def compute_team_bonus_multiplier(self, num_participants: int) -> float:
        """num_participants = total inscrits (joueur courant inclus)."""
        if num_participants <= 1:
            return 1.0
        bonus = (num_participants - 1) * self.BONUS_PER_PARTICIPANT
        return 1.0 + min(bonus, self.MAX_BONUS)

    def apply_team_bonus(self, base: Stats, num_participants: int) -> Stats:
        mult = self.compute_team_bonus_multiplier(num_participants)
        return Stats(
            max_hp=round(base.max_hp * mult),
            attack=round(base.attack * mult),
            defense=round(base.defense * mult),
            speed=base.speed,
            crit_chance=base.crit_chance,
            crit_damage=base.crit_damage,
            dodge=base.dodge,
            hp_regeneration=base.hp_regeneration,
        )
