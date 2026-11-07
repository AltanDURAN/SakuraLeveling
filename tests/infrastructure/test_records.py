"""Records du serveur (07/11/2026) : exploits notés après un combat de zone,
nuit de minuit (détenteurs, changements, titres tournants), bonus d'or."""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select

from app.application.services.encounter_service import EncounterService
from app.application.use_cases import records
from app.infrastructure.db.models.mob_model import MobDefinitionModel
from app.infrastructure.db.models.player_mob_kill_model import PlayerMobKillModel
from app.infrastructure.db.models.player_title_model import PlayerTitleModel
from app.infrastructure.db.models.records_model import PlayerRecordModel
from app.infrastructure.db.models.role_trial_model import RoleTrialScoreModel
from app.infrastructure.db.models.tower_progress_model import PlayerTowerProgressModel
from app.infrastructure.db.repositories.records_repository import RecordsRepository
from tests.infrastructure.test_encounter_service import (  # noqa: F401  (fixtures)
    _build_encounter,
    _create_player,
    _participant,
    _seed_mob,
    _won_by,
    patch_get_db_session,
    session,
)

NIGHT = datetime(2026, 11, 7, 23, 30, tzinfo=UTC)           # 8 novembre à Paris


def _mob(session, code, family):
    now = datetime.now(UTC)
    session.add(MobDefinitionModel(code=code, name=code, description="", image_name="", family=family,
                                   max_hp=10, current_hp=10, attack=1, defense=0, speed=1, crit_chance=0,
                                   crit_damage=100, dodge=0, hp_regeneration=0, xp_reward=1, gold_reward=1,
                                   spawn_weight=1, loot_table_json=None, created_at=now, updated_at=now))


def _titles(session) -> dict[str, int]:
    rows = session.execute(select(PlayerTitleModel).where(PlayerTitleModel.title_code.like("records_%")))
    return {r.title_code: r.player_id for r in rows.scalars()}


def test_un_combat_note_les_exploits_sauf_sous_la_lune(session):
    pid = _create_player(session, discord_id=11, name="Alice")
    encounter = SimpleNamespace(participants={1: SimpleNamespace(player_id=pid)}, lunar=None, mob_names="Gobelin")
    result = SimpleNamespace(
        turn_logs=[SimpleNamespace(events=[{"kind": "crit", "target": "e0", "amount": 700, "source": f"p{pid}"}])],
        contributions=[SimpleNamespace(player_id=pid, damage_dealt=1200, damage_tanked=0, hp_healed=0)])
    records.track_fight(session, encounter, result)
    session.commit()
    rows = {r.code: (r.value, r.detail) for r in session.execute(select(PlayerRecordModel)).scalars()}
    assert rows == {"coup": (700, "Gobelin"), "degats_combat": (1200, "Gobelin")}

    result.contributions[0].damage_dealt = 99_999
    records.track_fight(session, SimpleNamespace(**{**vars(encounter), "lunar": object()}), result)
    session.commit()
    assert session.execute(select(PlayerRecordModel.value).where(PlayerRecordModel.code == "degats_combat")).scalar() == 1200


def test_un_vrai_combat_de_zone_note_ses_exploits(session, patch_get_db_session):
    pid = _create_player(session, discord_id=11, name="Alice")
    _seed_mob(session)
    EncounterService().apply_rewards(_build_encounter([_participant(pid, 11)]), _won_by(pid, 11))
    assert RecordsRepository(session).player_exploits(pid)["degats_combat"].value == 100


def test_la_nuit_des_records(session, monkeypatch):
    admin = _create_player(session, discord_id=1, name="Admin")
    alice = _create_player(session, discord_id=11, name="Alice")
    bob = _create_player(session, discord_id=22, name="Bob")
    monkeypatch.setattr(records, "settings", SimpleNamespace(admin_ids=[1]))
    monkeypatch.setattr(records, "open_families", lambda: [("slime", "slimes")])
    _mob(session, "slime", "slime")
    repo = RecordsRepository(session)
    earlier = datetime(2026, 11, 7, 10, 0)
    repo.raise_best(admin, "coup", 99_999, earlier)                     # un admin n'entre pas dans les records
    repo.raise_best(alice, "coup", 500, earlier, "Gobelin")
    repo.raise_best(bob, "soin", 300, earlier)
    session.add(PlayerTowerProgressModel(player_id=bob, best_floor=12, best_at=earlier))
    session.add(RoleTrialScoreModel(player_id=alice, day=date(2026, 11, 7), role="dps", variant_code="x",
                                    score=8000, attempts=1, updated_at=earlier))
    session.add(PlayerMobKillModel(player_id=alice, mob_code="slime", kill_count=40, created_at=earlier,
                                   updated_at=earlier + timedelta(hours=1)))
    session.commit()

    report = records.run_night(session, now=NIGHT)
    assert report.first and report.day == date(2026, 11, 8)
    assert {code: e.player_id for code, e in report.held.items()} == {
        "coup": alice, "soin": bob, "tour": bob, "defi_dps": alice, "chasse_slime": alice}
    assert _titles(session) == {"records_1": alice, "records_2": bob}
    assert records.run_night(session, now=NIGHT + timedelta(minutes=20)) is None    # une fois par nuit

    # Le lendemain : Bob prend le plus gros coup et passe devant (égalité 3-2 → 3-2 inversé).
    repo.raise_best(bob, "coup", 650, datetime(2026, 11, 8, 15, 0), "Slime")
    session.commit()
    report = records.run_night(session, now=NIGHT + timedelta(days=1))
    assert [(c.record.code, c.taken, c.old.player_id) for c in report.changes] == [("coup", True, alice)]
    assert _titles(session) == {"records_1": bob, "records_2": alice}
    assert report.new_titles == {"records_1": bob, "records_2": alice}


def test_le_titre_donne_de_l_or_en_combat_de_zone(session, patch_get_db_session):
    pid = _create_player(session, discord_id=11, name="Alice")
    _seed_mob(session, gold=100)
    fight = lambda: EncounterService().apply_rewards(_build_encounter([_participant(pid, 11)]), _won_by(pid, 11))  # noqa: E731
    fight()                                       # sa 1re victoire lui donne aussi le Farmer Fou (+1 %)
    plain = fight()
    session.add(PlayerTitleModel(player_id=pid, title_code="records_1", unlocked_at=datetime.now(UTC),
                                 is_active=False))
    session.commit()
    titled = fight()
    assert titled.rewards[0].gold - plain.rewards[0].gold == 5           # +5 % d'un or de base de 100
    assert titled.rewards[0].xp == plain.rewards[0].xp                   # de l'or seulement
