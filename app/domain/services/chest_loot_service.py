from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class ChestLootEntry:
    """Une entrée de la table de loot d'un coffre.

    kind = "item"  → récompense item_code × quantity
    kind = "gold"  → récompense gold_amount pièces d'or
    kind = "nothing" → coffre vide (piège/déception)
    `weight` = poids relatif dans le tirage pondéré (entier > 0).
    """

    kind: str
    weight: int
    item_code: str = ""
    quantity: int = 0
    gold_amount: int = 0


@dataclass(frozen=True)
class ChestLootResult:
    kind: str
    item_code: str = ""
    quantity: int = 0
    gold_amount: int = 0

    @property
    def is_nothing(self) -> bool:
        return self.kind == "nothing"


class ChestLootService:
    """Tirage PONDÉRÉ UNIQUE : une seule récompense par coffre, choisie selon
    les poids des entrées. Déterministe si un `rng` seedé est fourni (tests)."""

    def parse_entries(self, raw_entries: list[dict]) -> list[ChestLootEntry]:
        out: list[ChestLootEntry] = []
        for e in raw_entries or []:
            try:
                weight = int(e.get("weight", 0))
            except (TypeError, ValueError):
                weight = 0
            if weight <= 0:
                continue
            kind = str(e.get("kind", "")).strip().lower()
            if kind not in ("item", "gold", "nothing"):
                continue
            out.append(
                ChestLootEntry(
                    kind=kind,
                    weight=weight,
                    item_code=str(e.get("item_code", "")).strip(),
                    quantity=max(0, int(e.get("quantity", 0) or 0)),
                    gold_amount=max(0, int(e.get("gold_amount", 0) or 0)),
                )
            )
        return out

    def scale_for_level(
        self, result: ChestLootResult, player_level: int, level_scaling_pct: float
    ) -> ChestLootResult:
        """Fait grossir le gain selon le niveau du joueur : multiplicateur
        `1 + niveau × pct/100`. Un joueur de plus haut niveau gagne plus.
        pct=0 → aucun scaling."""
        if result.is_nothing or level_scaling_pct <= 0:
            return result
        mult = 1.0 + max(0, player_level) * (level_scaling_pct / 100.0)
        if mult <= 1.0:
            return result
        if result.kind == "gold":
            return ChestLootResult(
                kind="gold", gold_amount=max(1, round(result.gold_amount * mult))
            )
        if result.kind == "item":
            return ChestLootResult(
                kind="item",
                item_code=result.item_code,
                quantity=max(result.quantity, round(result.quantity * mult)),
            )
        return result

    def roll(
        self, entries: list[ChestLootEntry], rng: random.Random | None = None
    ) -> ChestLootResult:
        rng = rng or random
        valid = [e for e in entries if e.weight > 0]
        if not valid:
            return ChestLootResult(kind="nothing")
        total = sum(e.weight for e in valid)
        pick = rng.uniform(0, total)
        acc = 0.0
        chosen = valid[-1]
        for e in valid:
            acc += e.weight
            if pick <= acc:
                chosen = e
                break
        if chosen.kind == "item" and chosen.item_code and chosen.quantity > 0:
            return ChestLootResult(
                kind="item", item_code=chosen.item_code, quantity=chosen.quantity
            )
        if chosen.kind == "gold" and chosen.gold_amount > 0:
            return ChestLootResult(kind="gold", gold_amount=chosen.gold_amount)
        return ChestLootResult(kind="nothing")
