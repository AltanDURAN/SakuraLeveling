"""Tests du TitleBonusService (agrégation des effets passifs)."""

from app.domain.entities.title_definition import TitleDefinition
from app.domain.services.title_bonus_service import (
    MAX_BONUS_PCT,
    TitleBonusService,
    TitleBonuses,
)


def _title(code: str, effects: list[dict]) -> TitleDefinition:
    return TitleDefinition(
        code=code,
        name=code.title(),
        description="",
        icon="🏷️",
        condition_type="kills_family",
        condition_target="slime",
        condition_value=100,
        effects=effects,
    )


def test_aggregate_empty_returns_neutral():
    service = TitleBonusService()
    out = service.aggregate([])
    assert out.damage_multiplier_vs("slime") == 1.0
    assert out.damage_received_multiplier_from("slime") == 1.0


def test_single_title_bonus_applied():
    service = TitleBonusService()
    title = _title(
        "slime_slayer",
        [
            {"type": "damage_bonus_vs_family", "target": "slime", "value": 10},
            {"type": "damage_reduction_from_family", "target": "slime", "value": 10},
        ],
    )
    out = service.aggregate([title])
    assert out.damage_multiplier_vs("slime") == 1.10
    assert out.damage_received_multiplier_from("slime") == 0.90


def test_multiple_titles_same_family_stack_additively():
    service = TitleBonusService()
    titles = [
        _title("a", [{"type": "damage_bonus_vs_family", "target": "slime", "value": 10}]),
        _title("b", [{"type": "damage_bonus_vs_family", "target": "slime", "value": 5}]),
    ]
    out = service.aggregate(titles)
    assert out.damage_multiplier_vs("slime") == 1.15


def test_bonus_capped_at_max():
    service = TitleBonusService()
    title = _title(
        "godslayer",
        [{"type": "damage_bonus_vs_family", "target": "slime", "value": 200}],
    )
    out = service.aggregate([title])
    # Bornage à MAX_BONUS_PCT
    assert out.damage_multiplier_vs("slime") == 1.0 + MAX_BONUS_PCT / 100


def test_unknown_effect_type_silently_ignored():
    service = TitleBonusService()
    title = _title(
        "future",
        [{"type": "future_effect_v2", "target": "slime", "value": 50}],
    )
    out = service.aggregate([title])
    assert out.damage_multiplier_vs("slime") == 1.0


def test_bonus_only_applies_to_targeted_family():
    service = TitleBonusService()
    title = _title(
        "slime_only",
        [{"type": "damage_bonus_vs_family", "target": "slime", "value": 20}],
    )
    out = service.aggregate([title])
    assert out.damage_multiplier_vs("slime") == 1.20
    assert out.damage_multiplier_vs("gobelin") == 1.0  # pas affecté
