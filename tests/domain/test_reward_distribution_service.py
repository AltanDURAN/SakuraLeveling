from app.domain.services.reward_distribution_service import RewardDistributionService
from app.domain.value_objects.player_contribution import PlayerContribution


def _make_contribution(
    player_id: int,
    damage_dealt: int = 0,
    survived: bool = True,
) -> PlayerContribution:
    return PlayerContribution(
        player_id=player_id,
        user_id=player_id * 100,
        name=f"P{player_id}",
        damage_dealt=damage_dealt,
        survived=survived,
        max_hp=100,
        final_hp=100 if survived else 0,
    )


def test_gold_distributed_proportionally_to_damage():
    service = RewardDistributionService()

    contributions = [
        _make_contribution(1, damage_dealt=60),
        _make_contribution(2, damage_dealt=30),
        _make_contribution(3, damage_dealt=10),
    ]

    rewards = service.distribute_gold(mob_gold_reward=100, contributions=contributions)

    pool = 100 * 3
    assert rewards[1] == pool * 60 // 100
    assert rewards[2] == pool * 30 // 100
    assert rewards[3] == pool * 10 // 100


def test_gold_pool_scales_with_survivor_count():
    service = RewardDistributionService()

    solo = service.distribute_gold(
        mob_gold_reward=50,
        contributions=[_make_contribution(1, damage_dealt=10)],
    )
    duo = service.distribute_gold(
        mob_gold_reward=50,
        contributions=[
            _make_contribution(1, damage_dealt=10),
            _make_contribution(2, damage_dealt=10),
        ],
    )

    assert solo[1] == 50
    assert duo[1] == 50
    assert duo[2] == 50


def test_gold_skips_dead_players():
    service = RewardDistributionService()

    contributions = [
        _make_contribution(1, damage_dealt=50, survived=True),
        _make_contribution(2, damage_dealt=50, survived=False),
    ]

    rewards = service.distribute_gold(mob_gold_reward=100, contributions=contributions)

    assert rewards[2] == 0
    assert rewards[1] == 100


def test_gold_falls_back_to_equal_share_when_no_damage():
    service = RewardDistributionService()

    contributions = [
        _make_contribution(1, damage_dealt=0),
        _make_contribution(2, damage_dealt=0),
    ]

    rewards = service.distribute_gold(mob_gold_reward=100, contributions=contributions)

    assert rewards[1] == 100
    assert rewards[2] == 100


def test_gold_no_survivors_returns_zero():
    service = RewardDistributionService()

    contributions = [
        _make_contribution(1, damage_dealt=10, survived=False),
        _make_contribution(2, damage_dealt=10, survived=False),
    ]

    rewards = service.distribute_gold(mob_gold_reward=100, contributions=contributions)

    assert rewards == {1: 0, 2: 0}


def test_gold_zero_reward_returns_zero():
    service = RewardDistributionService()

    contributions = [_make_contribution(1, damage_dealt=10)]

    rewards = service.distribute_gold(mob_gold_reward=0, contributions=contributions)

    assert rewards == {1: 0}


def test_xp_weak_player_gains_more_than_strong():
    service = RewardDistributionService()

    contributions = [_make_contribution(1), _make_contribution(2)]

    rewards = service.distribute_xp(
        mob_xp_reward=100,
        mob_power=1000,
        player_powers={1: 500, 2: 2000},
        contributions=contributions,
    )

    # P1 (faible) ratio 1000/500 = 2.0 → 200 XP
    # P2 (fort) ratio 1000/2000 = 0.5 → 50 XP
    assert rewards[1] == 200
    assert rewards[2] == 50
    assert rewards[1] > rewards[2]


def test_xp_clamps_to_max_when_player_extremely_weak():
    service = RewardDistributionService()

    contributions = [_make_contribution(1)]

    rewards = service.distribute_xp(
        mob_xp_reward=100,
        mob_power=10_000,
        player_powers={1: 1},
        contributions=contributions,
    )

    # ratio = 10000/1 = 10000, clampé à 2.5 → 250 XP
    assert rewards[1] == 250


def test_xp_clamps_to_min_when_player_extremely_strong():
    service = RewardDistributionService()

    contributions = [_make_contribution(1)]

    rewards = service.distribute_xp(
        mob_xp_reward=100,
        mob_power=10,
        player_powers={1: 10_000},
        contributions=contributions,
    )

    # ratio = 10/10000 ≈ 0.001, clampé à 0.5 → 50 XP
    assert rewards[1] == 50


def test_xp_skips_dead_players():
    service = RewardDistributionService()

    contributions = [
        _make_contribution(1, survived=True),
        _make_contribution(2, survived=False),
    ]

    rewards = service.distribute_xp(
        mob_xp_reward=100,
        mob_power=1000,
        player_powers={1: 1000, 2: 1000},
        contributions=contributions,
    )

    assert rewards[1] == 100
    assert rewards[2] == 0


def test_xp_zero_reward_returns_zero():
    service = RewardDistributionService()

    contributions = [_make_contribution(1)]

    rewards = service.distribute_xp(
        mob_xp_reward=0,
        mob_power=1000,
        player_powers={1: 500},
        contributions=contributions,
    )

    assert rewards == {1: 0}
