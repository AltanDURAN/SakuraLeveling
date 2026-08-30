"""Règles métier des artisans : maîtrise, prix du travail, délai.

Service PUR — aucune dépendance à la base ni à Discord. Tout ce qui varie
(seuils, coefficients, durées) vient de `artisans.json`.

Le prix et le délai dérivent tous deux de la puissance MARGINALE de la pièce
(cf. `ItemPowerService`) : une pièce deux fois plus forte coûte plus du double
et prend plus longtemps. C'est ce qui fait du travail d'artisan le premier vrai
puits d'or du jeu, et ce qui donne du poids aux pièces de haut rang.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.domain.entities.artisan import ArtisanDefinition, MasteryTier, PricingRules


@dataclass(frozen=True)
class WorkQuote:
    """Le devis d'un artisan pour une pièce donnée."""

    gold_cost: int
    duration_seconds: int
    item_power: int
    tier: MasteryTier
    #: Le palier courant suffit-il ? Champ EXPLICITE : le déduire de
    #: `required_tier is None` faisait passer pour « accepté » une pièce qu'AUCUN
    #: palier ne peut traiter (aucun palier requis trouvé ⇒ None).
    accepted: bool = True
    #: Palier qu'il faudrait atteindre ; None si aucun n'en est capable.
    required_tier: MasteryTier | None = None

    @property
    def instant(self) -> bool:
        return self.duration_seconds <= 0


class ArtisanService:
    def __init__(self, pricing: PricingRules | None = None) -> None:
        self.pricing = pricing or PricingRules()

    # ------------------------------------------------------------ maîtrise --
    def tier_for(
        self, definition: ArtisanDefinition, orders_completed: int,
    ) -> MasteryTier:
        """Palier courant : le plus haut dont le seuil est atteint."""
        reached = [
            t for t in definition.tiers if orders_completed >= t.orders_required
        ]
        if not reached:
            # Contenu mal formé (aucun palier à 0) : on prend le plus bas.
            return min(definition.tiers, key=lambda t: t.orders_required)
        return max(reached, key=lambda t: t.level)

    def next_tier(
        self, definition: ArtisanDefinition, orders_completed: int,
    ) -> MasteryTier | None:
        current = self.tier_for(definition, orders_completed)
        higher = [t for t in definition.tiers if t.level > current.level]
        return min(higher, key=lambda t: t.level) if higher else None

    def orders_until_next_tier(
        self, definition: ArtisanDefinition, orders_completed: int,
    ) -> int:
        nxt = self.next_tier(definition, orders_completed)
        return max(0, nxt.orders_required - orders_completed) if nxt else 0

    def tier_progress(
        self, definition: ArtisanDefinition, orders_completed: int,
    ) -> float:
        """Avancement 0..1 vers le palier suivant (1.0 au palier maximum)."""
        current = self.tier_for(definition, orders_completed)
        nxt = self.next_tier(definition, orders_completed)
        if nxt is None:
            return 1.0
        span = nxt.orders_required - current.orders_required
        if span <= 0:
            return 1.0
        done = orders_completed - current.orders_required
        return max(0.0, min(1.0, done / span))

    def tier_required_for(
        self, definition: ArtisanDefinition, power: int,
    ) -> MasteryTier | None:
        """Le palier le plus bas capable de traiter cette puissance."""
        capable = [t for t in definition.tiers if t.accepts_power(power)]
        return min(capable, key=lambda t: t.level) if capable else None

    # --------------------------------------------------------------- devis --
    def gold_cost(self, power: int, tier: MasteryTier) -> int:
        """Prix du travail, hors ingrédients. Croît plus vite que la puissance."""
        p = self.pricing
        raw = p.gold_base + p.gold_coef * math.pow(max(0, power), p.gold_exponent)
        discounted = raw * (1 - tier.gold_discount_pct / 100)
        return max(1, round(discounted))

    def duration_seconds(self, power: int, tier: MasteryTier) -> int:
        """Durée du travail. `duration_pct = 0` ⇒ instantané."""
        if tier.duration_pct <= 0:
            return 0
        p = self.pricing
        raw = p.duration_base_s + p.duration_coef_s * max(0, power)
        raw = min(raw, p.duration_max_s)
        return max(0, round(raw * tier.duration_pct / 100))

    def refund_for(self, gold_paid: int) -> int:
        """Remboursement en cas d'annulation d'une commande en cours."""
        return max(0, round(gold_paid * self.pricing.cancel_refund_pct / 100))

    def quote(
        self,
        definition: ArtisanDefinition,
        power: int,
        orders_completed: int,
    ) -> WorkQuote:
        tier = self.tier_for(definition, orders_completed)
        accepted = tier.accepts_power(power)
        needed = None if accepted else self.tier_required_for(definition, power)
        return WorkQuote(
            gold_cost=self.gold_cost(power, tier),
            duration_seconds=self.duration_seconds(power, tier),
            item_power=power,
            tier=tier,
            accepted=accepted,
            required_tier=needed,
        )
