from app.domain.value_objects.player_contribution import PlayerContribution


class RewardDistributionService:
    """Calcule la répartition des récompenses entre survivants d'un combat de groupe.

    Or : pondéré par les dégâts infligés. Pool = mob.gold_reward × nb_survivants.
        Si aucun dégât n'a été infligé (cas limite : tous les coups esquivés),
        partage à parts égales.
    XP : inverse à la puissance. Les joueurs plus faibles que le mob gagnent plus
        d'XP (apprentissage). Multiplicateur clampé entre 0.5 et 2.5.
    """

    XP_RATIO_MIN = 0.5
    XP_RATIO_MAX = 2.5

    def distribute_gold(
        self,
        mob_gold_reward: int,
        contributions: list[PlayerContribution],
    ) -> dict[int, int]:
        survivors = [c for c in contributions if c.survived]
        if not survivors or mob_gold_reward <= 0:
            return {c.player_id: 0 for c in contributions}

        pool = mob_gold_reward * len(survivors)
        total_damage = sum(c.damage_dealt for c in survivors)

        result: dict[int, int] = {c.player_id: 0 for c in contributions}

        if total_damage <= 0:
            equal_share = pool // len(survivors)
            for survivor in survivors:
                result[survivor.player_id] = equal_share
            return result

        for survivor in survivors:
            share = pool * survivor.damage_dealt // total_damage
            result[survivor.player_id] = share

        return result

    def distribute_xp(
        self,
        mob_xp_reward: int,
        mob_power: int,
        player_powers: dict[int, int],
        contributions: list[PlayerContribution],
    ) -> dict[int, int]:
        result: dict[int, int] = {c.player_id: 0 for c in contributions}

        if mob_xp_reward <= 0:
            return result

        for contribution in contributions:
            if not contribution.survived:
                continue

            player_power = max(1, player_powers.get(contribution.player_id, 1))
            ratio = mob_power / player_power
            multiplier = max(self.XP_RATIO_MIN, min(self.XP_RATIO_MAX, ratio))
            result[contribution.player_id] = round(mob_xp_reward * multiplier)

        return result
