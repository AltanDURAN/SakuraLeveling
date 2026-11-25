"""Le cog des zones suit le rythme réglé dans l'admin : délai et délai de
fuite, pause d'une zone, heures calmes (un monstre attendu passe quand même)."""

import asyncio
from types import SimpleNamespace
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
    c._zone_visitors = {}
    c._awake_cache = {}
    c.bot = SimpleNamespace(get_channel=lambda channel_id: None)   # serveur inconnu : éveillée
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
    # Un événement lunaire lève les heures calmes : le vrai ciel ne doit pas
    # décider du test (il échouait les nuits de nouvelle ou de pleine lune).
    monkeypatch.setattr(cog, "_current_lunar", lambda: None)
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
    ts = int(enc.ends_at.timestamp())
    text = EncounterCog._spawn_description(enc)
    # Le compte à rebours ET l'heure (07/11/2026, demande de l'auteur).
    assert f"⏳ S'enfuit à <t:{ts}:t>" in text and "🩸 Lune de sang — puissance des monstres ×" in text
    enc.participants = {1: object(), 2: object()}
    text = EncounterCog._spawn_description(enc)
    assert f"Le combat se lance <t:{ts}:R> (à <t:{ts}:t>) — 2 combattants" in text



# --- Veille des zones que personne n'a débloquées (25/11/2026) ---------------

ROLES = {"F": 1, "E": 2, "D": 3, "C": 4, "B": 5, "A": 6, "S": 7, "SS": 8, "SSS": 9}


def _guild(*members, chunked=True):
    return SimpleNamespace(guild=SimpleNamespace(chunked=chunked, members=list(members)))


def _member(*role_ids, bot=False):
    return SimpleNamespace(bot=bot, roles=[SimpleNamespace(id=r) for r in role_ids])


def test_une_zone_dort_tant_que_personne_n_a_son_rang():
    channel = _guild(_member(1), _member(2), _member(9, bot=True))      # F, E, et un bot SSS
    assert encounter_cog.zone_has_players(channel, "F", ROLES)
    assert encounter_cog.zone_has_players(channel, "E", ROLES)
    assert not encounter_cog.zone_has_players(channel, "D", ROLES)       # un bot ne compte pas
    # Un rang au-dessus suffit : la zone D se réveille pour un joueur de rang C.
    assert encounter_cog.zone_has_players(_guild(_member(4)), "D", ROLES)


def test_dans_le_doute_la_zone_reste_eveillee():
    assert encounter_cog.zone_has_players(None, "D", ROLES)                       # salon inconnu
    assert encounter_cog.zone_has_players(_guild(chunked=False), "D", ROLES)      # membres pas chargés
    assert encounter_cog.zone_has_players(_guild(), "", ROLES)                    # zone sans rang
    assert encounter_cog.zone_has_players(_guild(), "D", {})                      # rôles non réglés


def test_une_zone_en_veille_ne_fait_rien_apparaitre_sauf_un_monstre_force(cog, monkeypatch):
    use(monkeypatch, Pacing())
    monkeypatch.setattr(encounter_cog, "_zone_rank", lambda channel_id: "D")
    monkeypatch.setattr(encounter_cog.settings.__class__, "rank_roles", property(lambda self: ROLES))
    members = [_member(1)]
    cog.bot = SimpleNamespace(get_channel=lambda channel_id: _guild(*members))
    asyncio.run(cog._zone_tick(CHANNEL))
    assert cog.spawned == []
    cog._zone_forced_mob[CHANNEL] = "cor"                  # cor de chasse, test admin
    asyncio.run(cog._zone_tick(CHANNEL))
    assert cog.spawned == ["cor"]
    members.append(_member(3))                             # une promotion au rang D
    cog._awake_cache.clear()                               # (sinon : relu dans la minute)
    asyncio.run(cog._zone_tick(CHANNEL))
    assert cog.spawned == ["cor", "slime"]
