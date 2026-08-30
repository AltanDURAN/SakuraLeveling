"""Loader des PNJ artisans — pattern identique à set_loader / title_loader.

Charge `artisans.json` une fois et le garde en cache module-level. Toute
modification du fichier demande un redémarrage du bot (comme les zones et les
événements), sauf appel explicite à `clear_cache()`.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.entities.artisan import (
    ArtisanDefinition,
    MasteryTier,
    MerchantDefinition,
    PricingRules,
)

CONTENT_PATH = (
    Path(__file__).resolve().parents[2]
    / "infrastructure"
    / "content"
    / "artisans.json"
)

_cache: dict | None = None


def _raw() -> dict:
    global _cache
    if _cache is None:
        with CONTENT_PATH.open("r", encoding="utf-8") as fh:
            _cache = json.load(fh)
    return _cache


def clear_cache() -> None:
    global _cache
    _cache = None


def _accent(value, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return (int(value[0]), int(value[1]), int(value[2]))
    return fallback


def _tier(data: dict) -> MasteryTier:
    return MasteryTier(
        level=int(data.get("level", 1)),
        code=str(data.get("code", "")),
        name=str(data.get("name", "")),
        orders_required=int(data.get("orders_required", 0)),
        max_item_power=int(data.get("max_item_power", 0)),
        gold_discount_pct=int(data.get("gold_discount_pct", 0)),
        duration_pct=int(data.get("duration_pct", 100)),
        quote=str(data.get("quote", "")),
    )


def load_pricing() -> PricingRules:
    data = _raw().get("pricing") or {}
    default = PricingRules()
    return PricingRules(
        gold_base=int(data.get("gold_base", default.gold_base)),
        gold_coef=float(data.get("gold_coef", default.gold_coef)),
        gold_exponent=float(data.get("gold_exponent", default.gold_exponent)),
        duration_base_s=int(data.get("duration_base_s", default.duration_base_s)),
        duration_coef_s=float(data.get("duration_coef_s", default.duration_coef_s)),
        duration_max_s=int(data.get("duration_max_s", default.duration_max_s)),
        cancel_refund_pct=int(
            data.get("cancel_refund_pct", default.cancel_refund_pct)
        ),
    )


def list_artisans() -> list[ArtisanDefinition]:
    out: list[ArtisanDefinition] = []
    for data in _raw().get("artisans", []):
        tiers = tuple(
            sorted((_tier(t) for t in data.get("tiers", [])), key=lambda t: t.level)
        )
        out.append(
            ArtisanDefinition(
                code=str(data.get("code", "")),
                name=str(data.get("name", "")),
                title=str(data.get("title", "")),
                verb=str(data.get("verb", "fabriquer")),
                work_noun=str(data.get("work_noun", "travail")),
                image=str(data.get("image", "")),
                categories=tuple(str(c) for c in data.get("categories", [])),
                greeting=str(data.get("greeting", "")),
                accent=_accent(data.get("accent"), (200, 140, 80)),
                tiers=tiers,
            )
        )
    return out


def get_artisan(code: str) -> ArtisanDefinition | None:
    return next((a for a in list_artisans() if a.code == code), None)


def artisan_for_category(category: str) -> ArtisanDefinition | None:
    """Quel PNJ traite cette catégorie d'item ? Source unique de répartition."""
    return next(
        (a for a in list_artisans() if a.handles_category(category)), None,
    )


def get_merchant() -> MerchantDefinition:
    data = _raw().get("marchand") or {}
    return MerchantDefinition(
        code=str(data.get("code", "marchand")),
        name=str(data.get("name", "Marchand")),
        title=str(data.get("title", "Marchand")),
        image=str(data.get("image", "marchand.png")),
        greeting=str(data.get("greeting", "")),
        accent=_accent(data.get("accent"), (150, 106, 200)),
    )
