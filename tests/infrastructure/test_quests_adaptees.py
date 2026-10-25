"""Quêtes adaptées de bout en bout (base en mémoire) : tirage pour le joueur,
progression par objectif, réclamation, hebdo à plusieurs, défis."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.use_cases.daily_quests import (
    ClaimAllDailyUseCase,
    DailyQuestProgressService,
    GetDailyQuestsUseCase,
    get_current_day_start,
)
from app.application.use_cases.weekly_quests import (
    GetWeeklyQuestsUseCase,
    WeeklyQuestProgressService,
    get_current_week_start,
)
from app.domain.services.quest_reward_service import scale_reward
from app.infrastructure.daily_quests.quest_loader import get_definition
from app.infrastructure.db.base import Base
from app.infrastructure.db.models.mob_model import MobDefinitionModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel
from app.infrastructure.db.repositories.daily_quest_repository import DailyQuestRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.weekly_quest_repository import WeeklyQuestRepository


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    now = datetime.now(UTC)
    for code, family, level, weight in (("slime", "slime", 1, 40), ("gobelin", "gobelin", 6, 60),
                                         ("squelette", "mort-vivant", 14, 25), ("diablotin", "demoniaque", 44, 40)):
        s.add(MobDefinitionModel(code=code, name=code, description="", image_name="", family=family,
                                 element="", max_hp=100, current_hp=100, attack=10, defense=5, speed=5,
                                 crit_chance=0, crit_damage=100, dodge=0, hp_regeneration=0,
                                 xp_reward=round(6.25 * level), gold_reward=3 * level, spawn_weight=weight,
                                 created_at=now, updated_at=now))
    s.commit()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _player(session, discord_id=1, level=20):
    repo = PlayerRepository(session)
    profile = repo.get_or_create_by_discord_id(discord_id=discord_id, username="u", display_name="Joueur")
    session.query(PlayerProgressionModel).filter_by(player_id=profile.player.id).update({"level": level})
    session.commit()
    return repo.get_profile_by_player_id(profile.player.id)


def _state(session, rank="E"):
    return GetDailyQuestsUseCase(PlayerRepository(session), DailyQuestRepository(session)).execute(
        discord_id=1, username="u", display_name="Joueur", rank=rank)


def test_trois_quetes_concretes_a_la_mesure_du_joueur(session):
    _player(session, level=20)
    state = _state(session)
    assert len(state.quests) == 3
    for q in state.quests:
        assert "{" not in q.description and q.objective_quantity >= 1
        assert q.reward_gold == scale_reward(get_definition(q.code).reward_gold, 20)
    family = [a for a in DailyQuestRepository(session).list_for_player(1, get_current_day_start())
              if a.objective_type == "kill_family"]
    for a in family:   # rang E : la famille la plus avancée accessible
        assert a.objective_target == "mort-vivant"


def test_la_progression_suit_l_objectif_concret(session):
    profile = _player(session, level=20)
    repo = DailyQuestRepository(session)
    start = get_current_day_start()
    repo.assign(profile.player.id, start, [])          # rien d'auto-tiré
    from app.domain.services.quest_generation_service import ConcreteQuest
    repo.assign(profile.player.id, start, [
        ConcreteQuest("chasse_du_jour", "Chasse", "Vaincre 2 monstres.", "easy", "kill_any", "", 2),
        ConcreteQuest("traque_de_zone", "Traque", "Vaincre 2 démons.", "medium", "kill_family", "demoniaque", 2),
    ])
    hooks = DailyQuestProgressService(repo)
    hooks.on_kill(profile.player.id, "gobelin")
    hooks.on_kill(profile.player.id, "demoniaque")
    by_code = {a.quest_code: a for a in repo.list_for_player(profile.player.id, start)}
    assert by_code["chasse_du_jour"].completed
    assert by_code["traque_de_zone"].progress == 1 and not by_code["traque_de_zone"].completed

    result = ClaimAllDailyUseCase(PlayerRepository(session), repo, ItemRepository(session),
                                  InventoryRepository(session)).execute(
        discord_id=1, username="u", display_name="Joueur")
    assert result.success and [r.quest_code for r in result.rewards] == ["chasse_du_jour"]
    assert result.rewards[0].gold == scale_reward(get_definition("chasse_du_jour").reward_gold, 20)


def test_un_combat_tire_les_quetes_avec_la_zone_du_monstre(session):
    profile = _player(session, level=60)
    DailyQuestProgressService(DailyQuestRepository(session)).on_kill(profile.player.id, "demoniaque")
    rows = DailyQuestRepository(session).list_for_player(profile.player.id, get_current_day_start())
    assert len(rows) == 3
    assert all(a.objective_target in ("", "demoniaque", "soutien") for a in rows)


def test_hebdo_a_plusieurs_et_defis(session):
    profile = _player(session, level=30)
    repo = WeeklyQuestRepository(session)
    start = get_current_week_start()
    from app.domain.services.quest_generation_service import ConcreteQuest
    repo.assign(profile.player.id, start, [
        ConcreteQuest("en_bande", "En bande", "", "medium", "group_kill", "", 2),
        ConcreteQuest("assidu_des_defis", "Défis", "", "easy", "role_trial", "", 2),
    ])
    hooks = WeeklyQuestProgressService(repo)
    hooks.on_kill(profile.player.id, "gobelin", group_size=1)    # seul : ne compte pas
    hooks.on_kill(profile.player.id, "gobelin", group_size=3)
    hooks.on_role_trial(profile.player.id, "dps")
    hooks.on_role_trial(profile.player.id, "soutien")
    by_code = {a.quest_code: a for a in repo.list_for_player(profile.player.id, start)}
    assert by_code["en_bande"].progress == 1
    assert by_code["assidu_des_defis"].completed
    state = GetWeeklyQuestsUseCase(PlayerRepository(session), repo).execute(
        discord_id=1, username="u", display_name="Joueur")
    assert len(state.quests) == 2       # déjà tirées : on ne retire pas
