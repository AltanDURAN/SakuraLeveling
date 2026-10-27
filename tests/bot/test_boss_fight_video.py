"""Vidéo d'un assaut de world boss (27/10/2026) : arène, temps forts,
cartons d'ouverture / de phase / de fin, sous la limite d'envoi de Discord."""

import random
from types import SimpleNamespace

from PIL import Image, ImageSequence

from app.bot.cogs.world_boss_cog import WorldBossCog
from app.bot.rendering import boss_fight_video as bfv
from app.bot.rendering.fight_animation import MAX_UPLOAD_BYTES
from app.domain.services.boss_assault import assault_enemies
from app.domain.services.party_combat_service import PartyCombatService
from tests.domain.test_gear_passives_combat import member, mob

PHASES = [{"below_pct": 75, "name": "Colère", "text": "il frappe plus fort.", "attack_pct": 30},
          {"below_pct": 50, "name": "Fureur", "attack_pct": 30}]


def _log(*events):
    return SimpleNamespace(events=list(events), enemies_state=[{"current_hp": 100, "max_hp": 100}],
                           mob_state={}, players_state=[{"player_id": 1, "current_hp": 100, "max_hp": 100}],
                           turn_number=0)


def _index(logs, log) -> int:
    return next(i for i, other in enumerate(logs) if other is log)


def test_les_temps_forts_gardent_les_moments_cles_dans_l_ordre():
    logs = [_log({"kind": "hit", "target": "e0", "amount": 1}) for _ in range(100)]
    logs[50] = _log({"kind": "phase", "target": "e0"})
    logs[60] = _log({"kind": "hit", "target": "p1", "amount": 50, "style": "ultimate"})
    logs[70] = _log({"kind": "hit", "target": "e0", "amount": 90})     # gros coup
    chosen = bfv.select_highlights(logs, limit=12)
    assert len(chosen) == 12
    picked = [_index(logs, c) for c in chosen]
    assert {0, 1, 2, 3, 50, 60, 70, 97, 98, 99} <= set(picked)
    assert picked == sorted(picked)


def test_l_arene_du_boss_puis_la_salle_commune_puis_un_repli(tmp_path, monkeypatch):
    monkeypatch.setattr(bfv, "LANDSCAPES_ASSETS_DIR", tmp_path)
    monkeypatch.setattr(bfv, "GENERATED_ENCOUNTERS_DIR", tmp_path / "gen")
    Image.new("RGB", (40, 50), (200, 100, 50)).save(tmp_path / "berceau_cataclysmique.png")
    fallback = bfv.arena_path("titan", "feu")
    assert "arene_repli" in fallback and Image.open(fallback).getpixel((0, 0))[0] < 200   # assombri
    Image.new("RGB", (40, 50)).save(tmp_path / "arene_boss.png")
    assert bfv.arena_path("titan", "feu").endswith("arene_boss.png")
    Image.new("RGB", (40, 50)).save(tmp_path / "arene_titan.png")
    assert bfv.arena_path("titan", "feu").endswith("arene_titan.png")


def test_la_video_d_un_assaut(tmp_path):
    guard = {"code": "slime", "name": "Gelée", "image_name": "slime.png", "max_hp": 300, "attack": 30}
    boss = mob(code="slime_titan", name="Titan", image_name="slime.png", max_hp=6_000, current_hp=5_000,
               attack=120, defense=5, element="eau")
    enemies, index = assault_enemies(boss, phases=PHASES, guards=[guard, guard],
                                     ultimate={"name": "le Raz-de-marée", "every": 4, "multiplier": 1.8})
    random.seed(3)
    party = [member(1, attack=300), member(2, attack=300)]
    result = PartyCombatService().fight_party_vs_mobs(party, enemies)
    mobs = [{"name": e.mob.name, "image_name": e.mob.image_name, "element": e.mob.element,
             "max_hp": e.mob.max_hp, "code": e.mob.code} for e in enemies]
    players = [{"player_id": p["player_id"], "name": p["name"], "avatar_url": "", "max_hp": p["max_hp"],
                "current_hp": p["max_hp"]} for p in party]
    anim = bfv.render_boss_video(boss=mobs[index], guards=mobs[:index] + mobs[index + 1:], boss_index=index,
                                 players=players, logs=result.turn_logs, boss_hp_before=5_000, phases=PHASES,
                                 out_path=tmp_path / "assaut.gif", background_path="")
    assert anim.path.exists() and 0 < anim.size_bytes <= MAX_UPLOAD_BYTES
    gif = Image.open(anim.path)
    assert gif.info.get("loop") is None                                   # une seule lecture
    durations = [f.info.get("duration", 0) for f in ImageSequence.Iterator(gif)]
    assert durations[-1] == bfv.OUTRO_MS                                  # carton de fin
    assert durations.count(bfv.INTRO_MS) >= 1                             # ouverture (et phases)


def test_l_annonce_de_phase_dit_ce_qui_change():
    text = WorldBossCog._phase_milestone(1000, 400, 1000, PHASES, "Titan")
    assert "Titan entre en phase 2 — « Colère »" in text and "il frappe plus fort." in text
    assert "phase 3 — « Fureur »" in text
    assert WorldBossCog._phase_milestone(1000, 900, 1000, PHASES, "Titan") is None
