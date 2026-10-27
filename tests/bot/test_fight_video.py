"""Vidéo des combats de zone (27/10/2026) : le GIF se génère depuis un vrai
combat, sous la limite d'envoi de Discord, sans boucler ; le récapitulatif a
sa page « Journal »."""

import random
from types import SimpleNamespace

from PIL import Image

from app.application.services.encounter_participant import EncounterParticipant
from app.bot.cogs.encounter_cog import _VIDEO_MAX_BYTES, EncounterCog
from app.bot.embeds.battle_summary_embeds import PAGES, build_journal_page_embed
from app.bot.runtime.active_encounter import ActiveEncounter
from app.bot.runtime.encounter_mob_state import EncounterMobState
from app.domain.services.party_combat_service import EnemySetup, PartyCombatService
from app.domain.services.power_score_service import PowerScoreService
from app.domain.value_objects.battle_summary import BattleSummary
from tests.domain.test_gear_passives_combat import member, mob


def _state(code: str, hp: int) -> EncounterMobState:
    return EncounterMobState(code=code, name=code.capitalize(), image_name="gobelin.png", current_hp=hp,
                             max_hp=hp, attack=60, defense=5, speed=10, crit_chance=20, crit_damage=150,
                             dodge=5, hp_regeneration=0, element="plante")


def test_la_video_d_un_combat_de_meute(tmp_path):
    states = [_state("gobelin", 600), _state("gobelin_combattant", 600)]
    encounter = ActiveEncounter.create(mob_state=states[0], victory_image_name="", defeat_image_name="",
                                       flee_image_name="")
    encounter.pack = states[1:]
    encounter.message_id = 1
    party = [member(1, crit_chance=30), member(2)]
    for m in party:
        encounter.participants[m["user_id"]] = EncounterParticipant(
            user_id=m["user_id"], player_id=m["player_id"], display_name=m["name"], avatar_url="",
            current_hp=m["current_hp"], max_hp=m["max_hp"], stats=m["stats"])
    random.seed(2)
    enemies = [EnemySetup(mob=mob(code=s.code, max_hp=s.max_hp, current_hp=s.max_hp, attack=60)) for s in states]
    result = PartyCombatService().fight_party_vs_mobs(party, enemies)

    cog = object.__new__(EncounterCog)
    cog.generated_dir = tmp_path
    cog.power_score_service = PowerScoreService()
    anim = cog._render_fight_video(0, encounter, result, "")
    assert anim is not None and anim.path.exists()
    assert 0 < anim.size_bytes <= _VIDEO_MAX_BYTES and anim.duration_s > 2
    gif = Image.open(anim.path)
    assert gif.info.get("loop") is None                                      # une seule lecture
    total_ms = 0
    for i in range(gif.n_frames):   # les images identiques sont fusionnées : la durée, elle, est gardée
        gif.seek(i)
        total_ms += gif.info["duration"]
    assert abs(total_ms / 1000 - anim.duration_s) < 0.05


def test_le_recapitulatif_a_trois_pages_dont_le_journal():
    assert [label for label, _ in PAGES][-1] == "📜 Journal"
    summary = BattleSummary(outcome="victory", mob_name="Gobelin", mob_image_name="", mob_family="",
                            turns=2, journal=["`T1` ⚔️ A inflige 10 dégâts", "`T2` 💥 A inflige 20 dégâts (CRIT)"])
    assert "(CRIT)" in build_journal_page_embed(summary).description
