from app.domain.value_objects.player_contribution import PlayerContribution

CONTRIBUTION_METRICS = ("damage_dealt", "damage_tanked", "hp_healed")
#: Une catégorie compte pleinement dès qu'elle pèse ce quart de la plus grosse.
#: En dessous, son poids fond d'autant : chaque catégorie valait un tiers quoi
#: qu'il arrive, et 8 PV soignés ramassaient un tiers de l'or (audit de
#: novembre 2026). Un vrai soigneur, un vrai tank pèsent bien plus que ça.
FULL_WEIGHT_SHARE = 0.25


def contribution_scores(rows: list, key=lambda row: row.player_id) -> dict:
    """Score de chaque joueur : sa part de chaque catégorie, pondérée par le
    poids réel de la catégorie dans le combat."""
    totals = {metric: sum(getattr(row, metric) for row in rows) for metric in CONTRIBUTION_METRICS}
    biggest = max(totals.values(), default=0)
    scores = {key(row): 0.0 for row in rows}
    if biggest <= 0:
        return scores
    for metric, total in totals.items():
        if total <= 0:
            continue
        weight = min(1.0, total / (FULL_WEIGHT_SHARE * biggest))
        for row in rows:
            scores[key(row)] += weight * getattr(row, metric) / total
    return scores


class RewardDistributionService:
    """Calcule la répartition des récompenses d'un combat de groupe.

    Or : pool FIXE (= or_base du mob, PAS multiplié par le nombre de joueurs),
        réparti entre les SURVIVANTS au prorata d'un score de contribution
        multi-métriques (dégâts infligés, dégâts tankés, PV soignés, chaque
        catégorie pesant selon `contribution_scores`). Pool fixe
        ⇒ l'or/heure d'un groupe ≈ l'or/heure d'un solo (on tue plus vite mais
        chacun touche une part plus petite). C'est le régulateur de l'économie :
        les power-levelés en co-op montent vite en XP mais manquent d'or ⇒
        sous-équipés ⇒ gatés par la difficulté. Mort en combat ⇒ 0 or.

    XP : ÉQUITABLE. Chaque participant reçoit le MÊME montant = xp_base du mob
        (plein, aucune variance de puissance), morts INCLUS. En co-op, l'XP
        totale créée est donc multipliée par la taille du groupe (récompense
        sociale assumée — l'or reste, lui, le frein).
    """

    def compute_contribution_shares(
        self,
        contributions: list[PlayerContribution],
    ) -> dict[int, float]:
        """Renvoie pour chaque survivant sa part de contribution (0..1) au combat."""

        survivors = [c for c in contributions if c.survived]
        result: dict[int, float] = {c.player_id: 0.0 for c in contributions}

        if not survivors:
            return result

        scores = contribution_scores(survivors)
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
        """Or = pool FIXE (or_base), réparti entre survivants par contribution.

        Le pool n'est PAS multiplié par le nombre de joueurs : un groupe de 5
        partage le même or_base qu'un solo. Couplé au fait qu'on tue plus vite
        en groupe, l'or/heure reste ≈ celui du solo → c'est le régulateur éco.
        """
        survivors = [c for c in contributions if c.survived]
        result: dict[int, int] = {c.player_id: 0 for c in contributions}

        if not survivors or mob_gold_reward <= 0:
            return result

        shares = self.compute_contribution_shares(contributions)

        for survivor in survivors:
            result[survivor.player_id] = int(mob_gold_reward * shares[survivor.player_id])

        return result

    def distribute_xp(
        self,
        mob_xp_reward: int,
        contributions: list[PlayerContribution],
    ) -> dict[int, int]:
        """XP = même montant plein pour TOUS les participants, morts inclus.

        Aucune variance de puissance (supprimée) : chaque participant reçoit
        `mob_xp_reward`. Les morts gagnent l'XP (mais pas l'or, géré ailleurs).
        """
        result: dict[int, int] = {c.player_id: 0 for c in contributions}

        if mob_xp_reward <= 0:
            return result

        for contribution in contributions:
            result[contribution.player_id] = mob_xp_reward

        return result
