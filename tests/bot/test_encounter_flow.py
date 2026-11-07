"""Déroulé d'un combat de zone (audit d'ouverture, 07/11/2026) : une zone ne se
fige jamais, une fuite ne laisse pas de message, le bouton Lancer, une seule
zone à la fois et un récapitulatif qui tient dans les limites de Discord."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import discord
import pytest

from app.bot.cogs import encounter_cog
from app.bot.cogs.encounter_cog import EncounterCog
from app.bot.embeds.battle_summary_embeds import (
    build_details_page_embed,
    build_rewards_page_embed,
)
from app.bot.rendering import render_queue
from app.bot.runtime.active_encounter import ActiveEncounter
from app.bot.runtime.encounter_mob_state import EncounterMobState
from app.bot.views.encounter_view import EncounterView
from app.domain.services.pacing_service import Pacing, ZonePacing
from app.domain.value_objects.battle_summary import BattleSummary
from app.domain.value_objects.player_contribution import PlayerContribution
from app.domain.value_objects.player_reward import PlayerReward

CHANNEL = 42


def _encounter(participants=()) -> ActiveEncounter:
    state = EncounterMobState(code="slime", name="Slime", image_name="slime.png", current_hp=10, max_hp=10,
                              attack=1, defense=0, speed=1, crit_chance=0, crit_damage=100, dodge=0,
                              hp_regeneration=0)
    encounter = ActiveEncounter.create(mob_state=state, victory_image_name="", defeat_image_name="",
                                       flee_image_name="", duration_minutes=2)
    encounter.participants = {p: SimpleNamespace(user_id=p, display_name=f"J{p}") for p in participants}
    return encounter


class FakeMessage:
    jump_url = "https://discord.com/channels/1/2/3"

    def __init__(self, fail_edit=False):
        self.id = 7
        self.fail_edit = fail_edit
        self.deleted = False
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)
        if self.fail_edit:
            raise discord.HTTPException(SimpleNamespace(status=400, reason="refusé"), "Invalid Form Body")

    async def delete(self):
        self.deleted = True


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append(content)
        return FakeMessage()


@pytest.fixture
def cog(monkeypatch):
    c = object.__new__(EncounterCog)
    c.active_encounters, c._zone_next_spawn, c._zone_early_resolve = {}, {}, {}
    monkeypatch.setattr(encounter_cog, "get_pacing", lambda: Pacing(zones=ZonePacing(
        respawn_min_minutes=1, respawn_max_minutes=1, flee_respawn_minutes=9)))
    c._current_lunar = lambda: None
    c.encounter_service = SimpleNamespace()

    async def no_video(*args):
        return None

    c._play_fight_video = no_video
    c.bot = SimpleNamespace(get_channel=lambda _: None)
    return c


def _play(cog, encounter, message, channel=None, window_s=0):
    cog.active_encounters[CHANNEL] = encounter

    async def scenario():
        view = SimpleNamespace(children=[])
        try:
            await cog._play_encounter(channel or FakeChannel(), CHANNEL, encounter, view, message, "", window_s)
        finally:
            if cog.active_encounters.get(CHANNEL) is encounter:
                cog._reschedule(CHANNEL)

    return scenario()


def _no_record(monkeypatch):
    monkeypatch.setattr(encounter_cog, "record_now", lambda *a, **k: None)


def test_une_fuite_supprime_le_message_et_applique_le_delai_de_fuite(cog, monkeypatch):
    _no_record(monkeypatch)
    message = FakeMessage()
    before = datetime.now(UTC)
    asyncio.run(_play(cog, _encounter(), message))
    assert message.deleted and not message.edits
    assert CHANNEL not in cog.active_encounters
    assert cog._zone_next_spawn[CHANNEL] - before > timedelta(minutes=8)


def test_un_combat_annule_par_l_admin_retire_son_message(cog):
    message, encounter = FakeMessage(), _encounter([1])

    async def scenario():
        async def replace():
            await asyncio.sleep(0)
            cog.active_encounters.pop(CHANNEL)
            cog._zone_early_resolve[CHANNEL].set()

        task = asyncio.create_task(replace())
        cog.active_encounters[CHANNEL] = encounter
        await cog._play_encounter(FakeChannel(), CHANNEL, encounter, SimpleNamespace(children=[]),
                                  message, "", 30)
        await task

    asyncio.run(scenario())
    assert message.deleted


def _reward(index: int, *, level_up: bool = False) -> PlayerReward:
    contribution = PlayerContribution(player_id=index, user_id=index, name=f"Joueur{index}", damage_dealt=1000 + index,
                                      damage_tanked=500, hp_healed=50, survived=True, final_hp=80, max_hp=100)
    return PlayerReward(player_id=index, user_id=index, name=f"Joueur{index}", avatar_url="", gold=100 + index,
                        xp=50, items=[("gelee", 2)], item_names={"gelee": "Gelée de slime"}, contribution=contribution,
                        contribution_share=1 / 30, level_before=4 if level_up else 0,
                        level_after=5 if level_up else 0, stat_points=1 if level_up else 0,
                        skill_points=1 if level_up else 0, gear=[("Heaume du Gobelin", "rare")],
                        titles=["Pourfendeur de slimes"] if level_up else [])


def _within_discord_limits(embed: discord.Embed) -> None:
    assert len(embed) <= 6000 and len(embed.fields) <= 25
    assert all(len(f.value) <= 1024 and f.value.strip() for f in embed.fields)


@pytest.mark.parametrize("players", [1, 20, 26, 40, 100])
def test_le_recapitulatif_tient_dans_les_limites_de_discord(players):
    summary = BattleSummary(outcome="victory", mob_name="Gobelin", mob_image_name="", mob_family="", turns=9,
                            rewards=[_reward(i, level_up=True) for i in range(players)])
    for builder in (build_rewards_page_embed, build_details_page_embed):
        embed = builder(summary)
        _within_discord_limits(embed)
        if players > 20:
            assert embed.fields[-1].name == "Et aussi"


def test_si_discord_refuse_le_recapitulatif_la_zone_repart_et_les_joueurs_le_savent(cog):
    encounter = _encounter([1])
    summary = BattleSummary(outcome="victory", mob_name="Slime", mob_image_name="", mob_family="", turns=3,
                            rewards=[_reward(1)])
    cog.encounter_service = SimpleNamespace(
        resolve_active_encounter=lambda e: SimpleNamespace(turn_logs=[]),
        persist_final_players_hp=lambda result, enc: None,
        apply_rewards=lambda enc, result: summary)
    channel = FakeChannel()
    asyncio.run(_play(cog, encounter, FakeMessage(fail_edit=True), channel))
    assert CHANNEL not in cog.active_encounters                       # la zone est libérée
    assert CHANNEL in cog._zone_next_spawn
    assert any("récompenses sont distribuées" in (text or "") for text in channel.sent)


def test_meme_une_panne_pendant_le_combat_libere_la_zone(cog):
    def boom(_):
        raise RuntimeError("panne")

    cog.encounter_service = SimpleNamespace(resolve_active_encounter=boom)
    with pytest.raises(RuntimeError):
        asyncio.run(_play(cog, _encounter([1]), FakeMessage()))
    assert CHANNEL not in cog.active_encounters


def test_le_bouton_lancer_demarre_le_combat_d_un_inscrit(cog):
    encounter = _encounter([1])
    encounter.launch_after = datetime.now(UTC) - timedelta(seconds=1)
    cog.active_encounters[CHANNEL] = encounter
    event = cog._zone_early_resolve[CHANNEL] = asyncio.Event()
    assert not cog.request_launch(CHANNEL, 2)[0]                      # pas inscrit
    assert not event.is_set()
    assert cog.request_launch(CHANNEL, 1)[0]
    assert event.is_set()


def test_le_bouton_lancer_laisse_aux_autres_le_temps_de_venir(cog):
    encounter = _encounter([1])
    encounter.launch_after = datetime.now(UTC) + timedelta(seconds=20)
    cog.active_encounters[CHANNEL] = encounter
    event = cog._zone_early_resolve[CHANNEL] = asyncio.Event()
    ok, message = cog.request_launch(CHANNEL, 1)
    assert not ok and "<t:" in message and not event.is_set()


def test_une_seule_zone_a_la_fois(cog):
    cog.active_encounters[1] = _encounter([9])
    cog.active_encounters[2] = _encounter()
    cog.encounter_service = SimpleNamespace(register_participant=lambda **kw: (True, "ok"))
    ok, message = asyncio.run(cog.register_participant(2, 9, "J", ""))
    assert not ok and "<#1>" in message
    cog.active_encounters[1].resolved = True           # sa vidéo tourne : il peut repartir
    assert asyncio.run(cog.register_participant(2, 9, "J", ""))[0]


def test_lancer_et_quitter_n_apparaissent_qu_avec_des_combattants(cog):
    async def scenario():
        view = EncounterView(cog, CHANNEL, timeout=None)
        assert view.launch_encounter not in view.children and view.leave_encounter not in view.children
        cog.active_encounters[CHANNEL] = _encounter([1])
        view.sync()
        assert [c.label for c in view.children] == ["Combattre", "Lancer", "Quitter", "Demander de l'aide"]
        cog.active_encounters[CHANNEL].participants.clear()
        view.sync()
        assert [c.label for c in view.children] == ["Combattre", "Demander de l'aide"]

    asyncio.run(scenario())


def test_une_seule_video_a_la_fois():
    async def scenario():
        order = []

        async def render(name):
            async with render_queue.video_slot() as granted:
                assert granted
                order.append(f"{name} début")
                await asyncio.sleep(0.01)
                order.append(f"{name} fin")

        await asyncio.gather(render("a"), render("b"))
        return order

    assert asyncio.run(scenario()) == ["a début", "a fin", "b début", "b fin"]


def test_une_file_trop_longue_saute_la_video():
    async def scenario():
        async with render_queue.video_slot():
            async with render_queue.video_slot(timeout=0.01) as granted:
                return granted

    assert asyncio.run(scenario()) is False


def test_un_palier_de_niveau_est_annonce_sans_mentionner(cog):
    sent = []

    class General:
        async def send(self, text, **kwargs):
            sent.append((text, kwargs["allowed_mentions"]))

    cog.bot = SimpleNamespace(get_channel=lambda _: General())
    below = SimpleNamespace(level_before=8, level_after=9, name="A")
    crossed = SimpleNamespace(level_before=19, level_after=21, name="B_b")
    asyncio.run(cog._announce_milestones(SimpleNamespace(rewards=[below, crossed])))
    assert len(sent) == 1 and "niveau 20" in sent[0][0] and "B\\_b" in sent[0][0]
    assert sent[0][1].users is False


def test_le_recapitulatif_annonce_le_niveau_et_le_titre():
    summary = BattleSummary(outcome="victory", mob_name="Gobelin", mob_image_name="", mob_family="", turns=9,
                            rewards=[_reward(1, level_up=True)])
    text = build_rewards_page_embed(summary).fields[0].value
    assert "🆙 **Niveau 5 !**" in text and "/stats" in text and "/arbre" in text
    assert "Titre débloqué : **Pourfendeur de slimes**" in text


def test_le_titre_du_recapitulatif_s_accorde_avec_une_meute():
    summary = BattleSummary(outcome="defeat", mob_name="Loup et Ours", mob_image_name="", mob_family="", turns=9,
                            mob_count=2)
    assert build_rewards_page_embed(summary).title == "💀 Défaite contre Loup et Ours"
