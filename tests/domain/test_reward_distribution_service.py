from app.domain.services.reward_distribution_service import RewardDistributionService
from app.domain.value_objects.player_contribution import PlayerContribution


def _make_contribution(
    player_id: int,
    damage_dealt: int = 0,
    damage_tanked: int = 0,
    hp_healed: int = 0,
    survived: bool = True,
) -> PlayerContribution:
    return PlayerContribution(
        player_id=player_id,
        user_id=player_id * 100,
        name=f"P{player_id}",
        damage_dealt=damage_dealt,
        damage_tanked=damage_tanked,
        hp_healed=hp_healed,
        survived=survived,
        max_hp=100,
        final_hp=100 if survived else 0,
    )


# ---------- Score de contribution multi-métriques ----------


def test_contribution_pure_dps_scores_full_when_alone_in_damage():
    service = RewardDistributionService()

    # Un seul joueur fait des dégâts, l'autre ne fait rien (mais a survécu).
    shares = service.compute_contribution_shares(
        [
            _make_contribution(1, damage_dealt=100),
            _make_contribution(2),
        ]
    )

    # P1 a 100% de la métrique active, P2 0% → P1 prend toute la part.
    assert shares[1] == 1.0
    assert shares[2] == 0.0


def test_contribution_dps_and_tank_get_equal_share():
    service = RewardDistributionService()

    # DPS fait 100% des dégâts, Tank tank 100% des coups → chacun a 1 point.
    shares = service.compute_contribution_shares(
        [
            _make_contribution(1, damage_dealt=200, damage_tanked=20),
            _make_contribution(2, damage_dealt=20, damage_tanked=200),
        ]
    )

    # Symétrie parfaite → 50/50.
    assert abs(shares[1] - 0.5) < 0.001
    assert abs(shares[2] - 0.5) < 0.001


def test_contribution_pure_healer_gets_share_when_team_has_heals():
    service = RewardDistributionService()

    shares = service.compute_contribution_shares(
        [
            _make_contribution(1, damage_dealt=300),
            _make_contribution(2, damage_tanked=300),
            _make_contribution(3, hp_healed=100),
        ]
    )

    # 3 spécialistes complémentaires, chacun 100% de sa métrique → tiers parfait.
    assert abs(shares[1] - 1 / 3) < 0.001
    assert abs(shares[2] - 1 / 3) < 0.001
    assert abs(shares[3] - 1 / 3) < 0.001


def test_contribution_versatile_player_beats_specialist():
    service = RewardDistributionService()

    # P1 fait du dégât ET tank ; P2 ne fait que du dégât.
    shares = service.compute_contribution_shares(
        [
            _make_contribution(1, damage_dealt=100, damage_tanked=200),
            _make_contribution(2, damage_dealt=100, damage_tanked=0),
        ]
    )

    # P1 a 50% du dmg + 100% du tank = 1.5 / 2.0 = 75%
    # P2 a 50% du dmg + 0% du tank = 0.5 / 2.0 = 25%
    assert abs(shares[1] - 0.75) < 0.001
    assert abs(shares[2] - 0.25) < 0.001


def test_contribution_unused_metric_is_ignored():
    service = RewardDistributionService()

    # Personne n'a soigné → la métrique heal est ignorée, pas de division par zéro.
    shares = service.compute_contribution_shares(
        [
            _make_contribution(1, damage_dealt=100, damage_tanked=50),
            _make_contribution(2, damage_dealt=100, damage_tanked=50),
        ]
    )

    # Symétrie parfaite, partage égal.
    assert abs(shares[1] - 0.5) < 0.001
    assert abs(shares[2] - 0.5) < 0.001


def test_contribution_zero_metrics_falls_back_to_equal():
    service = RewardDistributionService()

    # Aucune métrique active (cas extrême : combat instant gagné par déconnexion ?).
    shares = service.compute_contribution_shares(
        [
            _make_contribution(1),
            _make_contribution(2),
            _make_contribution(3),
        ]
    )

    assert all(abs(s - 1 / 3) < 0.001 for s in shares.values())


def test_contribution_dead_players_get_zero_share():
    service = RewardDistributionService()

    shares = service.compute_contribution_shares(
        [
            _make_contribution(1, damage_dealt=100, survived=True),
            _make_contribution(2, damage_dealt=100, survived=False),
        ]
    )

    # Mort → écarté du calcul, vivant prend 100%.
    assert shares[1] == 1.0
    assert shares[2] == 0.0


# ---------- Distribution de l'or ----------


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


def test_gold_distributed_by_contribution_score_dps_vs_tank_equal():
    service = RewardDistributionService()

    # DPS fait tout le dmg, Tank tank tout : 50/50 grâce au score multi-métrique.
    rewards = service.distribute_gold(
        mob_gold_reward=100,
        contributions=[
            _make_contribution(1, damage_dealt=200, damage_tanked=20),
            _make_contribution(2, damage_dealt=20, damage_tanked=200),
        ],
    )

    pool = 100 * 2  # 200
    assert abs(rewards[1] - pool * 0.5) <= 1
    assert abs(rewards[2] - pool * 0.5) <= 1


def test_gold_versatile_player_gets_more():
    service = RewardDistributionService()

    rewards = service.distribute_gold(
        mob_gold_reward=100,
        contributions=[
            _make_contribution(1, damage_dealt=100, damage_tanked=200),
            _make_contribution(2, damage_dealt=100, damage_tanked=0),
        ],
    )

    # P1 = 75%, P2 = 25% du pool 200 → 150 vs 50
    assert rewards[1] > rewards[2]
    assert abs(rewards[1] - 150) <= 1
    assert abs(rewards[2] - 50) <= 1


def test_gold_skips_dead_players():
    service = RewardDistributionService()

    rewards = service.distribute_gold(
        mob_gold_reward=100,
        contributions=[
            _make_contribution(1, damage_dealt=50, survived=True),
            _make_contribution(2, damage_dealt=50, survived=False),
        ],
    )

    assert rewards[2] == 0
    # Pool = 100 × 1 survivant = 100, tout va au survivant
    assert rewards[1] == 100


def test_gold_no_survivors_returns_zero():
    service = RewardDistributionService()

    rewards = service.distribute_gold(
        mob_gold_reward=100,
        contributions=[
            _make_contribution(1, damage_dealt=10, survived=False),
            _make_contribution(2, damage_dealt=10, survived=False),
        ],
    )

    assert rewards == {1: 0, 2: 0}


def test_gold_zero_reward_returns_zero():
    service = RewardDistributionService()

    rewards = service.distribute_gold(
        mob_gold_reward=0,
        contributions=[_make_contribution(1, damage_dealt=10)],
    )

    assert rewards == {1: 0}


# ---------- Distribution de l'XP ----------


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

    rewards = service.distribute_xp(
        mob_xp_reward=100,
        mob_power=10_000,
        player_powers={1: 1},
        contributions=[_make_contribution(1)],
    )

    # ratio = 10000/1 = 10000, clampé à 2.5 → 250 XP
    assert rewards[1] == 250


def test_xp_clamps_to_min_when_player_extremely_strong():
    service = RewardDistributionService()

    rewards = service.distribute_xp(
        mob_xp_reward=100,
        mob_power=10,
        player_powers={1: 10_000},
        contributions=[_make_contribution(1)],
    )

    # ratio = 10/10000 ≈ 0.001, clampé à 0.5 → 50 XP
    assert rewards[1] == 50


def test_xp_skips_dead_players():
    service = RewardDistributionService()

    rewards = service.distribute_xp(
        mob_xp_reward=100,
        mob_power=1000,
        player_powers={1: 1000, 2: 1000},
        contributions=[
            _make_contribution(1, survived=True),
            _make_contribution(2, survived=False),
        ],
    )

    assert rewards[1] == 100
    assert rewards[2] == 0


def test_xp_zero_reward_returns_zero():
    service = RewardDistributionService()

    rewards = service.distribute_xp(
        mob_xp_reward=0,
        mob_power=1000,
        player_powers={1: 500},
        contributions=[_make_contribution(1)],
    )

    assert rewards == {1: 0}
