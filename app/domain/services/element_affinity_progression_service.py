from dataclasses import dataclass


MAX_AFFINITY = 100


@dataclass(frozen=True)
class AffinityConversion:
    """Résultat de la conversion d'essences en niveaux d'affinité."""

    new_affinity: int
    remaining_essences: int
    levels_gained: int


class ElementAffinityProgressionService:
    """Logique pure de progression d'affinité par essences.

    Coût pour passer de l'affinité N à N+1 = **N+1 essences** du même élément
    (0→1 coûte 1, 1→2 coûte 2, …, 99→100 coûte 100). L'affinité est plafonnée
    à 100 ; au max, les essences ne se consomment plus (elles s'accumulent sans
    effet). Conversion AUTOMATIQUE : on dépense tant qu'on peut payer le palier
    suivant.
    """

    def cost_for_next_level(self, current_affinity: int) -> int | None:
        """Coût du prochain palier, ou None si déjà au max."""
        if current_affinity >= MAX_AFFINITY:
            return None
        return current_affinity + 1

    def apply_essences(
        self,
        current_affinity: int,
        current_essences: int,
        added_essences: int,
    ) -> AffinityConversion:
        affinity = max(0, min(MAX_AFFINITY, int(current_affinity)))
        essences = max(0, int(current_essences)) + max(0, int(added_essences))
        levels = 0

        while affinity < MAX_AFFINITY and essences >= (affinity + 1):
            essences -= affinity + 1
            affinity += 1
            levels += 1

        return AffinityConversion(
            new_affinity=affinity,
            remaining_essences=essences,
            levels_gained=levels,
        )
