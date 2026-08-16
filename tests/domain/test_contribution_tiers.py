from app.domain.services.contribution_tier_service import (
    TIERS,
    next_tier,
    share_to_next,
    tier_for_share,
)


def test_tiers_are_ordered_from_highest_to_lowest():
    shares = [t.min_share for t in TIERS]
    assert shares == sorted(shares, reverse=True)


def test_tier_thresholds():
    assert tier_for_share(0.30).code == "legende"
    assert tier_for_share(0.25).code == "legende"   # borne incluse
    assert tier_for_share(0.24).code == "or"
    assert tier_for_share(0.15).code == "or"
    assert tier_for_share(0.14).code == "argent"
    assert tier_for_share(0.05).code == "argent"
    assert tier_for_share(0.04).code == "bronze"
    assert tier_for_share(0.0).code == "bronze"


def test_higher_tier_pays_more():
    mults = [tier_for_share(s).gold_multiplier for s in (0.0, 0.05, 0.15, 0.25)]
    assert mults == sorted(mults)  # strictement croissant par palier


def test_next_tier_and_gap():
    assert next_tier(0.0).code == "argent"
    assert abs(share_to_next(0.0) - 0.05) < 1e-9
    assert next_tier(0.10).code == "or"
    assert abs(share_to_next(0.10) - 0.05) < 1e-9


def test_no_next_tier_at_top():
    assert next_tier(0.40) is None
    assert share_to_next(0.40) == 0.0


def test_format_is_displayable():
    assert tier_for_share(0.30).format() == "💎 Légende du raid"
