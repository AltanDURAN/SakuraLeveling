"""Déroulé d'un combat de zone (audit d'ouverture, 07/11/2026) : une zone ne se
fige jamais, la fiche d'une fuite reste jusqu'au monstre suivant, le bouton
Lancer, une seule zone à la fois et un récapitulatif qui tient dans les limites
de Discord."""

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
    c.active_encounters, c._zone_next_spawn, c._zone_early_resolve, c._zone_visitors = {}, {}, {}, {}
    c._zone_fled = {}
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
    monkeypatch.setattr(encounter_cog, "count_now", lambda *a, **k: None)


def test_une_fuite_laisse_sa_fiche_jusqu_au_monstre_suivant(cog, monkeypatch):
    """07/11/2026, demande de l'auteur : on voit toujours ce qu'est devenu le
    dernier monstre ; la fiche part quand le suivant apparaît."""
    from app.bot.embeds.encounter_embeds import FLEE_TEXT

    _no_record(monkeypatch)
    message = FakeMessage()
    before = datetime.now(UTC)
    asyncio.run(_play(cog, _encounter(), message))
    assert not message.deleted
    edit = message.edits[-1]
    assert edit["view"] is None and edit["attachments"] == []          # plus de bouton ni d'image
    assert edit["embed"].title == "🌫️ Slime a pris la fuite" and edit["embed"].description == FLEE_TEXT
    assert cog._zone_fled[CHANNEL] == [message]
    assert CHANNEL not in cog.active_encounters
    assert cog._zone_next_spawn[CHANNEL] - before > timedelta(minutes=8)

    asyncio.run(cog._retire_flee_notices(CHANNEL))                     # le monstre suivant apparaît
    assert message.deleted and CHANNEL not in cog._zone_fled


def test_une_fiche_de_fuite_refusee_ne_laisse_pas_de_boutons_morts(cog, monkeypatch):
    _no_record(monkeypatch)
    message = FakeMessage(fail_edit=True)
    asyncio.run(_play(cog, _encounter(), message))
    assert message.deleted and CHANNEL not in cog._zone_fled


def test_une_meute_ont_pris_la_fuite():
    from app.bot.embeds.encounter_embeds import build_flee_embed

    pack = _encounter()
    pack.pack = [_encounter().mob_state]
    assert build_flee_embed(pack).title == "🌫️ Slime et Slime ont pris la fuite"


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
    def register(**kwargs):
        kwargs["encounter"].participants[kwargs["user_id"]] = SimpleNamespace(level=4)
        return True, "ok"

    cog.encounter_service = SimpleNamespace(register_participant=register)
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


def _zone_cog(monkeypatch, mobs):
    from app.domain.services.power_score_service import PowerScoreService

    c = object.__new__(EncounterCog)
    c._zone_visitors = {}
    c.power_score_service = PowerScoreService()

    class Repo:
        def __init__(self, session):
            pass

        def list_all(self):
            return mobs

    class Session:
        def __enter__(self):
            return None

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(encounter_cog, "MobRepository", Repo)
    monkeypatch.setattr(encounter_cog, "get_db_session", Session)
    monkeypatch.setattr(encounter_cog, "get_spawn_channel_for_family", lambda family: CHANNEL)
    monkeypatch.setattr(encounter_cog, "unreleased_families", set)
    return c


def _mob(code, attack, weight):
    return SimpleNamespace(code=code, family="f", spawn_weight=weight, max_hp=100, attack=attack, defense=5,
                           speed=5, crit_chance=0, crit_damage=100, dodge=0, hp_regeneration=0)


def _draw(cog, n=2000):
    import random
    from collections import Counter

    random.seed(3)
    return Counter(cog._pick_mob_for_zone(CHANNEL, None).code for _ in range(n))


def test_une_zone_de_debutants_voit_surtout_le_monstre_le_plus_faible(monkeypatch):
    mobs = [_mob("slime", 8, 40), _mob("gobelin", 10, 40), _mob("chaman", 26, 60), _mob("runique", 42, 80)]
    cog = _zone_cog(monkeypatch, mobs)
    assert _draw(cog)["slime"] < 500                      # personne de connu : tirage normal
    cog._zone_visitors[CHANNEL] = {1: (3, datetime.now(UTC))}
    assert cog._beginners_only(CHANNEL)
    assert _draw(cog)["slime"] > 1200


def test_un_ancien_dans_la_zone_rend_le_tirage_normal(monkeypatch):
    mobs = [_mob("slime", 8, 40), _mob("gobelin", 10, 40)]
    cog = _zone_cog(monkeypatch, mobs)
    now = datetime.now(UTC)
    cog._zone_visitors[CHANNEL] = {1: (3, now), 2: (30, now)}
    assert not cog._beginners_only(CHANNEL)


def test_le_passage_d_un_debutant_s_oublie(monkeypatch):
    cog = _zone_cog(monkeypatch, [_mob("slime", 8, 40)])
    cog._zone_visitors[CHANNEL] = {1: (3, datetime.now(UTC) - timedelta(minutes=30))}
    assert not cog._beginners_only(CHANNEL)


def _button_row(*labels):
    return SimpleNamespace(children=[SimpleNamespace(label=label) for label in labels])


def test_seul_un_monstre_ou_une_note_d_arret_sont_retires_au_demarrage():
    from app.bot.cogs.encounter_cog import RESTART_NOTE

    bot_user = SimpleNamespace(id=1)
    mine = dict(author=bot_user, content="", components=[])
    assert EncounterCog._is_leftover(SimpleNamespace(**{**mine, "components": [_button_row("Combattre")]}), 1)
    assert EncounterCog._is_leftover(SimpleNamespace(**{**mine, "content": RESTART_NOTE}), 1)
    assert not EncounterCog._is_leftover(SimpleNamespace(**mine), 1)                 # un récapitulatif
    assert not EncounterCog._is_leftover(
        SimpleNamespace(author=SimpleNamespace(id=2), content="", components=[_button_row("Combattre")]), 1)


def test_au_demarrage_la_fiche_de_fuite_reste_jusqu_au_monstre_suivant(cog, monkeypatch):
    from app.bot.embeds.encounter_embeds import FLEE_TEXT

    bot_user = SimpleNamespace(id=1)
    flee = SimpleNamespace(author=bot_user, content="", components=[], deleted=False,
                           embeds=[discord.Embed(title="🌫️ Gobelin a pris la fuite", description=FLEE_TEXT)])
    monster = SimpleNamespace(author=bot_user, content="", components=[_button_row("Combattre")],
                              embeds=[], deleted=False)
    recap = SimpleNamespace(author=bot_user, content="", components=[], deleted=False,
                            embeds=[discord.Embed(title="🏆 Victoire contre Slime")])
    for message in (flee, monster, recap):
        async def delete(m=message):
            m.deleted = True
        message.delete = delete
    assert EncounterCog._is_flee_notice(flee, 1)
    assert not EncounterCog._is_flee_notice(recap, 1) and not EncounterCog._is_flee_notice(monster, 1)
    assert not EncounterCog._is_flee_notice(SimpleNamespace(**{**vars(flee), "author": SimpleNamespace(id=2)}), 1)

    class Channel:
        async def history(self, limit):
            for message in (monster, flee, recap):
                yield message

    channel = Channel()
    cog.bot = SimpleNamespace(get_channel=lambda _: channel, user=bot_user)
    monkeypatch.setattr(encounter_cog, "list_zone_channels", lambda: [CHANNEL])
    asyncio.run(cog._clean_leftovers())
    assert monster.deleted and not flee.deleted and not recap.deleted
    assert cog._zone_fled[CHANNEL] == [flee]
    asyncio.run(cog._retire_flee_notices(CHANNEL))
    assert flee.deleted


def test_un_arret_annule_les_combats_a_venir_et_montre_les_combats_joues(cog):
    from app.bot.cogs.encounter_cog import RESTART_NOTE

    waiting, played = _encounter([1]), _encounter([2])
    waiting.message, played.message = FakeMessage(), FakeMessage()
    played.resolved = True
    played.summary = BattleSummary(outcome="victory", mob_name="Slime", mob_image_name="", mob_family="", turns=3,
                                   rewards=[_reward(1)])
    channel = FakeChannel()
    cog.bot = SimpleNamespace(get_channel=lambda _: channel)
    cog.active_encounters = {1: waiting, 2: played}
    asyncio.run(cog.prepare_shutdown())
    assert waiting.message.deleted and channel.sent == [RESTART_NOTE]
    assert not played.message.deleted and played.message.edits[0]["view"] is None


def test_les_boutons_du_recapitulatif_partent_a_la_fin():
    from app.bot.views.battle_summary_view import BattleSummaryView

    async def scenario():
        view = BattleSummaryView(BattleSummary(outcome="defeat", mob_name="Slime", mob_image_name="",
                                               mob_family="", turns=1))
        view.message = FakeMessage()
        await view.on_timeout()
        return view.message.edits

    assert asyncio.run(scenario()) == [{"view": None}]
