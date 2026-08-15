import random

from app.domain.services.little_girl_service import (
    CHOICE_HELP,
    CHOICE_IGNORE,
    TITLE_CODE,
    LittleGirlConfig,
    LittleGirlService,
)

CFG = LittleGirlConfig(
    trap_probability=50,
    gold_loss_per_level=10,
    buff_multiplier=1.1,
    buff_duration_hours=3,
    debuff_multiplier=0.5,
    debuff_duration_hours=3,
    title_chance=10,
)


def _svc():
    return LittleGirlService()


def test_help_real_girl_gives_buff():
    c = _svc().resolve(CHOICE_HELP, is_trap=False, player_level=50, config=CFG, has_title=False)
    assert c.buff_multiplier == 1.1 and c.buff_hours == 3
    assert c.gold_loss == 0 and not c.halve_hp and not c.grant_title


def test_help_trap_loses_gold_and_half_hp():
    c = _svc().resolve(CHOICE_HELP, is_trap=True, player_level=40, config=CFG, has_title=False)
    assert c.gold_loss == 400  # 10 × 40
    assert c.halve_hp is True
    assert c.buff_multiplier == 0.0


def test_ignore_real_girl_gives_debuff():
    c = _svc().resolve(CHOICE_IGNORE, is_trap=False, player_level=10, config=CFG, has_title=False)
    assert c.debuff_multiplier == 0.5 and c.debuff_hours == 3
    assert c.gold_loss == 0


def test_ignore_trap_grants_title_on_win():
    # rng forcé à retourner un tirage gagnant (< title_chance)
    rng = random.Random()
    rng.uniform = lambda a, b: 5.0  # < 10 → gagne
    c = _svc().resolve(CHOICE_IGNORE, is_trap=True, player_level=1, config=CFG, has_title=False, rng=rng)
    assert c.grant_title == TITLE_CODE
    assert c.buff_multiplier == 0.0


def test_ignore_trap_already_has_title_gives_buff():
    rng = random.Random()
    rng.uniform = lambda a, b: 5.0  # gagne
    c = _svc().resolve(CHOICE_IGNORE, is_trap=True, player_level=1, config=CFG, has_title=True, rng=rng)
    assert c.grant_title == ""
    assert c.buff_multiplier == 1.1


def test_ignore_trap_loses_gives_nothing():
    rng = random.Random()
    rng.uniform = lambda a, b: 50.0  # > 10 → perd
    c = _svc().resolve(CHOICE_IGNORE, is_trap=True, player_level=1, config=CFG, has_title=False, rng=rng)
    assert c.grant_title == "" and c.buff_multiplier == 0.0 and c.gold_loss == 0


def test_gold_loss_floors_level_at_1():
    c = _svc().resolve(CHOICE_HELP, is_trap=True, player_level=0, config=CFG, has_title=False)
    assert c.gold_loss == 10  # niveau planché à 1


def test_roll_is_trap_bounds():
    always = LittleGirlConfig(trap_probability=100)
    never = LittleGirlConfig(trap_probability=0)
    assert _svc().roll_is_trap(always, random.Random(0)) is True
    assert _svc().roll_is_trap(never, random.Random(0)) is False


def test_unknown_choice_no_effect():
    c = _svc().resolve("", is_trap=True, player_level=5, config=CFG, has_title=False)
    assert c.summary == "" and c.buff_multiplier == 0.0 and c.gold_loss == 0
