"""Le cog des zones suit le rythme réglé dans l'admin : délai et délai de
fuite, pause d'une zone, heures calmes (un monstre attendu passe quand même)."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.bot.cogs import encounter_cog
from app.bot.cogs.encounter_cog import EncounterCog
from app.domain.services.pacing_service import Pacing, ZoneOverride, ZonePacing

CHANNEL = 42


@pytest.fixture
def cog(monkeypatch):
    c = object.__new__(EncounterCog)
    c.active_encounters, c._zone_next_spawn = {}, {}
    c._zone_forced_mob, c._zone_forced_element, c._zone_forced_pack = {}, {}, {}
    spawned = []

    async def run(channel_id, mob, **kw):
        spawned.append(mob)

    c._run_encounter = run
    c._pick_mob_for_zone = lambda channel_id, forced: forced or "slime"
    c.spawned = spawned
    monkeypatch.setattr(encounter_cog, "list_zone_channels", lambda: [CHANNEL])
    return c


def use(monkeypatch, pacing: Pacing) -> None:
    monkeypatch.setattr(encounter_cog, "get_pacing", lambda: pacing)


def test_le_prochain_monstre_suit_le_delai_et_le_delai_de_fuite(cog, monkeypatch):
    use(monkeypatch, Pacing(zones=ZonePacing(respawn_min_minutes=4, respawn_max_minutes=4,
                                             flee_respawn_minutes=20)))
    before = datetime.now(UTC)
    cog._reschedule(CHANNEL)
    assert abs(cog._zone_next_spawn[CHANNEL] - before - timedelta(minutes=4)) < timedelta(seconds=5)
    cog._reschedule(CHANNEL, fled=True)
    assert abs(cog._zone_next_spawn[CHANNEL] - before - timedelta(minutes=20)) < timedelta(seconds=5)


def test_une_zone_en_pause_ne_fait_rien_apparaitre_sauf_un_monstre_force(cog, monkeypatch):
    use(monkeypatch, Pacing(overrides={CHANNEL: ZoneOverride(paused=True)}))
    asyncio.run(cog._zone_tick(CHANNEL))
    assert cog.spawned == []
    ok, message = cog.queue_summoned_elite("gobelin_superieur", CHANNEL)
    assert not ok and "pause" in message                     # le cor n'est pas gaspillé
    cog._zone_forced_mob[CHANNEL] = "gobelin_superieur"       # /admin spawn_encounter
    asyncio.run(cog._zone_tick(CHANNEL))
    assert cog.spawned == ["gobelin_superieur"]


def test_heures_calmes(cog, monkeypatch):
    hour = datetime.now(encounter_cog.pacing_service.PARIS).hour
    use(monkeypatch, Pacing(zones=ZonePacing(quiet_start_hour=hour, quiet_end_hour=(hour + 2) % 24,
                                             pack_chance_pct=0)))
    asyncio.run(cog._zone_tick(CHANNEL))
    assert cog.spawned == []
    use(monkeypatch, Pacing(zones=ZonePacing(pack_chance_pct=0)))
    asyncio.run(cog._zone_tick(CHANNEL))
    assert cog.spawned == ["slime"]


def test_le_compte_a_rebours_reste_affiche_et_dit_quand_le_combat_part():
    from types import SimpleNamespace

    from app.domain.services.lunar_service import DEFAULT_RULES, LunarEvent

    now = datetime.now(UTC)
    enc = SimpleNamespace(pack=[], mob_names="Loup", ends_at=now + timedelta(minutes=5), participants={},
                          lunar=LunarEvent("lune_de_sang", now, now + timedelta(hours=9),
                                           rule=DEFAULT_RULES["lune_de_sang"]))
    text = EncounterCog._spawn_description(enc)
    assert "s'enfuit <t:" in text and "🩸 Lune de sang — monstres ×3 plus forts" in text
    enc.participants = {1: object(), 2: object()}
    assert "Le combat se lance <t:" in EncounterCog._spawn_description(enc) and "2 combattants" in \
        EncounterCog._spawn_description(enc)
