from app.domain.services.progression_service import ProgressionService


def test_progression_service_no_level_up():
    service = ProgressionService()

    new_level, new_xp, new_skill_points = service.apply_level_up(
        current_level=1,
        current_xp=0,
        gained_xp=50,
        current_skill_points=0,
    )

    assert new_level == 1
    assert new_xp == 50
    assert new_skill_points == 0


def test_progression_service_single_level_up():
    service = ProgressionService()

    new_level, new_xp, new_skill_points = service.apply_level_up(
        current_level=1,
        current_xp=90,
        gained_xp=20,
        current_skill_points=0,
    )

    # niveau 1 -> 2 coûte 100 XP
    assert new_level == 2
    assert new_xp == 10
    assert new_skill_points == 1


def test_progression_service_multiple_level_ups():
    service = ProgressionService()

    new_level, new_xp, new_skill_points = service.apply_level_up(
        current_level=1,
        current_xp=0,
        gained_xp=350,
        current_skill_points=0,
    )

    # niveau 1 -> 2 : 100
    # niveau 2 -> 3 : 200
    # reste 50
    assert new_level == 3
    assert new_xp == 50
    assert new_skill_points == 2


def test_progression_service_xp_required_for_next_level():
    service = ProgressionService()

    assert service.xp_required_for_next_level(1) == 100
    assert service.xp_required_for_next_level(2) == 200
    assert service.xp_required_for_next_level(3) == 300