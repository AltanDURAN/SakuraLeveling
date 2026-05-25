from datetime import UTC, datetime

from app.domain.entities.mob_definition import MobDefinition
from app.domain.services.power_score_service import PowerScoreService
from app.domain.value_objects.stats import Stats


def build_stats(
    max_hp: int = 100,
    attack: int = 10,
    defense: int = 5,
    speed: int = 5,
    crit_chance: int = 5,
    crit_damage: int = 150,
    dodge: int = 0,
    hp_regeneration: int = 5,
) -> Stats:
    return Stats(
        max_hp=max_hp,
        attack=attack,
        defense=defense,
        speed=speed,
        crit_chance=crit_chance,
        crit_damage=crit_damage,
        dodge=dodge,
        hp_regeneration=hp_regeneration,
    )


def build_mob(
    max_hp: int = 100,
    attack: int = 10,
    defense: int = 5,
    speed: int = 5,
    crit_chance: int = 5,
    crit_damage: int = 150,
    dodge: int = 0,
    hp_regeneration: int = 0,
) -> MobDefinition:
    now = datetime.now(UTC)
    return MobDefinition(
        id=1,
        code="test_mob",
        name="Test Mob",
        description="",
        image_name="test.png",
        family="test",
        max_hp=max_hp,
        current_hp=max_hp,
        attack=attack,
        defense=defense,
        speed=speed,
        crit_chance=crit_chance,
        crit_damage=crit_damage,
        dodge=dodge,
        hp_regeneration=hp_regeneration,
        xp_reward=10,
        gold_reward=5,
        spawn_weight=1,
        loot_table=None,
        created_at=now,
        updated_at=now,
    )


def test_format_score_under_thousand():
    service = PowerScoreService()

    assert service.format_score(0) == "0"
    assert service.format_score(123) == "123"
    assert service.format_score(900) == "900"
    assert service.format_score(999) == "999"


def test_format_score_thousands():
    service = PowerScoreService()

    assert service.format_score(1_000) == "1K"
    assert service.format_score(1_200) == "1K"
    assert service.format_score(12_999) == "12K"
    assert service.format_score(999_999) == "999K"


def test_format_score_millions():
    service = PowerScoreService()

    assert service.format_score(1_000_000) == "1M"
    assert service.format_score(1_200_000) == "1M"
    assert service.format_score(42_000_000) == "42M"


def test_calculate_from_stats_returns_positive_integer():
    service = PowerScoreService()

    score = service.calculate_from_stats(build_stats())

    assert isinstance(score, int)
    assert score >= 1


def test_score_increases_with_attack():
    service = PowerScoreService()

    weak = build_stats(attack=10)
    strong = build_stats(attack=50)

    assert service.calculate_from_stats(strong) > service.calculate_from_stats(weak)


def test_score_increases_with_max_hp():
    service = PowerScoreService()

    fragile = build_stats(max_hp=100)
    tanky = build_stats(max_hp=500)

    assert service.calculate_from_stats(tanky) > service.calculate_from_stats(fragile)


def test_score_increases_with_defense():
    service = PowerScoreService()

    naked = build_stats(defense=0)
    armored = build_stats(defense=50)

    assert service.calculate_from_stats(armored) > service.calculate_from_stats(naked)


def test_score_increases_with_speed():
    service = PowerScoreService()

    slow = build_stats(speed=5)
    fast = build_stats(speed=50)

    assert service.calculate_from_stats(fast) > service.calculate_from_stats(slow)


def test_score_consistency_between_stats_and_mob():
    service = PowerScoreService()

    stats = build_stats(
        max_hp=200, attack=30, defense=10, speed=10,
        crit_chance=10, crit_damage=160, dodge=5, hp_regeneration=8,
    )
    mob = build_mob(
        max_hp=200, attack=30, defense=10, speed=10,
        crit_chance=10, crit_damage=160, dodge=5, hp_regeneration=8,
    )

    assert service.calculate_from_stats(stats) == service.calculate_from_mob(mob)


def test_party_score_is_sum_of_individual_scores():
    service = PowerScoreService()

    stats_a = build_stats(attack=10)
    stats_b = build_stats(attack=20)
    stats_c = build_stats(attack=30)

    individual = (
        service.calculate_from_stats(stats_a)
        + service.calculate_from_stats(stats_b)
        + service.calculate_from_stats(stats_c)
    )
    party = service.calculate_party_score([stats_a, stats_b, stats_c])

    assert party == individual


def test_party_score_empty_list_is_zero():
    service = PowerScoreService()

    assert service.calculate_party_score([]) == 0


def test_calculate_and_format_helpers_return_strings():
    service = PowerScoreService()

    stats = build_stats()
    mob = build_mob()

    assert isinstance(service.calculate_and_format_from_stats(stats), str)
    assert isinstance(service.calculate_and_format_from_mob(mob), str)
    assert isinstance(service.calculate_and_format_party_score([stats]), str)


def test_dodge_does_not_break_score_at_zero():
    service = PowerScoreService()

    score = service.calculate_from_stats(build_stats(dodge=0))

    assert score >= 1


# ---------- Rangs (F- → SSS+) ----------


def test_compute_rank_starts_at_f_minus_for_low_scores():
    service = PowerScoreService()

    assert service.compute_rank(0) == "F-"
    assert service.compute_rank(1) == "F-"
    assert service.compute_rank(309) == "F-"


def test_compute_rank_thresholds_are_strict():
    """Score == borne ne donne PAS le rang inférieur — il bascule au suivant."""
    service = PowerScoreService()

    # 310 = borne F- → on bascule sur F
    assert service.compute_rank(309) == "F-"
    assert service.compute_rank(310) == "F"
    # 800 = borne F+ → on bascule sur E-
    assert service.compute_rank(799) == "F+"
    assert service.compute_rank(800) == "E-"


def test_compute_rank_letter_progression():
    service = PowerScoreService()

    # Score == borne ⇒ bascule sur le rang du dessus (lookup strict)
    assert service.compute_rank(524) == "F"
    assert service.compute_rank(525) == "F+"
    assert service.compute_rank(1_124) == "E-"
    assert service.compute_rank(1_125) == "E"
    assert service.compute_rank(13_599) == "S"
    assert service.compute_rank(13_600) == "S+"
    assert service.compute_rank(649_999) == "SSS"
    assert service.compute_rank(650_000) == "SSS+"


def test_compute_rank_level_100_reference_is_s():
    """Régression : le joueur de référence (build équilibré) au niveau ~100
    doit être rang S — c'est la définition de l'endgame 'actuel'."""
    service = PowerScoreService()

    ref_l100 = build_stats(
        max_hp=100 + 16 * 100,
        attack=int(10 + 1.45 * 100),
        defense=int(8 + 0.52 * 100),
        speed=10, crit_chance=5, crit_damage=150, dodge=0,
    )
    assert service.compute_rank_from_stats(ref_l100) == "S"


def test_compute_rank_caps_at_sss_plus():
    service = PowerScoreService()

    # Au-delà du dernier seuil (50_000_000_000), tout est SSS+
    assert service.compute_rank(50_000_000_000) == "SSS+"
    assert service.compute_rank(10**15) == "SSS+"
