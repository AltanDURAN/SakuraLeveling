"""Entités des PNJ artisans (forgeron, artisane) et de leurs paliers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MasteryTier:
    """Un palier de maîtrise d'un artisan, vis-à-vis d'UN joueur.

    La maîtrise est relationnelle : elle mesure ce que l'artisan a déjà
    fabriqué POUR ce joueur. Deux joueurs voient donc le même PNJ à des
    paliers différents.
    """

    level: int
    code: str
    name: str
    orders_required: int
    max_item_power: int  # 0 = aucune limite
    gold_discount_pct: int
    duration_pct: int  # 100 = durée normale, 0 = instantané
    quote: str = ""

    def accepts_power(self, power: int) -> bool:
        return self.max_item_power <= 0 or power <= self.max_item_power


@dataclass(frozen=True)
class ArtisanDefinition:
    code: str
    name: str
    title: str
    verb: str  # « forger » / « confectionner »
    work_noun: str  # « forge » / « confection »
    image: str
    categories: tuple[str, ...]
    greeting: str
    accent: tuple[int, int, int]
    tiers: tuple[MasteryTier, ...] = field(default_factory=tuple)

    @property
    def display_name(self) -> str:
        return f"{self.name}, {self.title.lower()}"

    def handles_category(self, category: str) -> bool:
        return category in self.categories


@dataclass(frozen=True)
class PricingRules:
    gold_base: int = 25
    gold_coef: float = 2.5
    gold_exponent: float = 1.15
    duration_base_s: int = 60
    duration_coef_s: float = 4.0
    duration_max_s: int = 3600
    cancel_refund_pct: int = 50


@dataclass(frozen=True)
class MerchantDefinition:
    code: str
    name: str
    title: str
    image: str
    greeting: str
    accent: tuple[int, int, int]

    @property
    def display_name(self) -> str:
        return f"{self.name}, {self.title.lower()}"
