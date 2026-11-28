"""Mesure la file des vidéos de combat (audit du 28/11/2026) : N vidéos de
zone rendues EN MÊME TEMPS, comme le bot (un thread chacune), avec un vrai
décor et un long combat de meute. Donne la durée de chaque rendu et la
mémoire au plus haut, pour régler `render_queue`.

Usage (sur le VPS, bot en marche : on mesure dans les vraies conditions) :
    .venv/bin/python -m scripts.measure_video_load 1
    .venv/bin/python -m scripts.measure_video_load 2
Chaque appel est un processus neuf (la mémoire au plus haut est celle du
processus). Rien n'est écrit en base ; les GIF vont dans un dossier jetable.
"""

from __future__ import annotations

import random
import resource
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def _available_mb() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) // 1024
    return -1


def _fight(seed: int):
    from app.application.services.encounter_participant import EncounterParticipant
    from app.bot.runtime.active_encounter import ActiveEncounter
    from app.bot.runtime.encounter_mob_state import EncounterMobState
    from app.domain.services.party_combat_service import EnemySetup, PartyCombatService
    from tests.domain.test_gear_passives_combat import member, mob

    def state(code, hp):
        return EncounterMobState(code=code, name=code, image_name=f"{code}.png", current_hp=hp, max_hp=hp,
                                 attack=60, defense=5, speed=10, crit_chance=20, crit_damage=150, dodge=5,
                                 hp_regeneration=0, element="plante")

    states = [state("gobelin", 1500), state("gobelin_combattant", 1500), state("slime", 1500)]
    encounter = ActiveEncounter.create(mob_state=states[0], victory_image_name="", defeat_image_name="",
                                       flee_image_name="")
    encounter.pack = states[1:]
    encounter.message_id = seed + 1
    party = [member(i, crit_chance=30) for i in (1, 2, 3)]
    for m in party:
        encounter.participants[m["user_id"]] = EncounterParticipant(
            user_id=m["user_id"], player_id=m["player_id"], display_name=m["name"], avatar_url="",
            current_hp=m["current_hp"], max_hp=m["max_hp"], stats=m["stats"])
    random.seed(seed)
    enemies = [EnemySetup(mob=mob(code=s.code, max_hp=s.max_hp, current_hp=s.max_hp, attack=60)) for s in states]
    return encounter, PartyCombatService().fight_party_vs_mobs(party, enemies)


def main(count: int) -> None:
    from app.bot.cogs.encounter_cog import EncounterCog
    from app.domain.services.power_score_service import PowerScoreService

    background = next(iter(sorted(Path("assets/landscapes").glob("clairiere*.png"))), None)
    cog = object.__new__(EncounterCog)
    cog.generated_dir = Path(tempfile.mkdtemp(prefix="video_load_"))
    cog.power_score_service = PowerScoreService()
    fights = [_fight(seed) for seed in range(count)]
    base_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
    lowest = [_available_mb()]
    done = threading.Event()

    def sample():
        while not done.wait(0.2):
            lowest[0] = min(lowest[0], _available_mb())

    threading.Thread(target=sample, daemon=True).start()

    def render(i):
        start = time.perf_counter()
        encounter, result = fights[i]
        anim = cog._render_fight_video(0, encounter, result, str(background) if background else "")
        took = time.perf_counter() - start
        size = anim.size_bytes // 1024 if anim else 0
        duration = anim.duration_s if anim else 0
        if anim:
            anim.path.unlink(missing_ok=True)
        return took, size, duration, len(result.turn_logs)

    t0 = time.perf_counter()
    with ThreadPoolExecutor(count) as pool:
        results = list(pool.map(render, range(count)))
    wall = time.perf_counter() - t0
    done.set()
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
    for took, size, duration, actions in results:
        print(f"  rendu {took:5.1f} s · GIF {size} Ko · vidéo {duration:.0f} s · {actions} actions")
    print(f"{count} vidéo(s) en même temps : {wall:.1f} s au total ; processus {base_rss} → {peak} Mo "
          f"(+{peak - base_rss}) ; mémoire disponible au plus bas {lowest[0]} Mo")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
