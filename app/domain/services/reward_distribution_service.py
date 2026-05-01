from app.domain.value_objects.player_contribution import PlayerContribution


class RewardDistributionService:
    """Calcule la répartition des récompenses entre survivants d'un combat de groupe.

    Or : pondéré par un *score de contribution* multi-métriques. Pour chaque
        métrique active dans l'équipe (dégâts infligés, dégâts tankés, PV
        régénérés), chaque survivant reçoit `sa_part / total_équipe` points.
        Cela rend la répartition role-agnostic : un Tank pur, un Healer pur ou
        un DPS pur gagnent tous 1 point dans leur spécialité, un polyvalent
        cumule. Une métrique inutilisée par toute l'équipe est ignorée.

    XP : inverse à la puissance. Les joueurs plus faibles que le mob gagnent
        plus d'XP (apprentissage). Multiplicateur clampé entre 0.5 et 2.5.
    """

    XP_RATIO_MIN = 0.5
    XP_RATIO_MAX = 2.5

    CONTRIBUTION_METRICS = ("damage_dealt", "damage_tanked", "hp_healed")

    def compute_contribution_shares(
        self,
        contributions: list[PlayerContribution],
    ) -> dict[int, float]:
        """Renvoie pour chaque survivant sa part de contribution (0..1) au combat."""

        survivors = [c for c in contributions if c.survived]
        result: dict[int, float] = {c.player_id: 0.0 for c in contributions}

        if not survivors:
            return result

        team_totals = {
            metric: sum(getattr(c, metric) for c in survivors)
            for metric in self.CONTRIBUTION_METRICS
        }

        scores: dict[int, float] = {c.player_id: 0.0 for c in survivors}

        for metric in self.CONTRIBUTION_METRICS:
            team_total = team_totals[metric]
            if team_total <= 0:
                continue
            for survivor in survivors:
                scores[survivor.player_id] += getattr(survivor, metric) / team_total

        total_score = sum(scores.values())

        if total_score <= 0:
            equal = 1.0 / len(survivors)
            for survivor in survivors:
                result[survivor.player_id] = equal
            return result

        for survivor in survivors:
            result[survivor.player_id] = scores[survivor.player_id] / total_score

        return result

    def distribute_gold(
        self,
        mob_gold_reward: int,
        contributions: list[PlayerContribution],
    ) -> dict[int, int]:
        survivors = [c for c in contributions if c.survived]
        result: dict[int, int] = {c.player_id: 0 for c in contributions}

        if not survivors or mob_gold_reward <= 0:
            return result

        pool = mob_gold_reward * len(survivors)
        shares = self.compute_contribution_shares(contributions)

        for survivor in survivors:
            result[survivor.player_id] = int(pool * shares[survivor.player_id])

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
