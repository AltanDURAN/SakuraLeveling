"""Vidéo d'un combat de la tour solo (08/11/2026, demande de l'auteur : voir le
combat et son récapitulatif « de la même façon que les combats de zone »).

Même moteur que les combats de zone (`fight_scene.build_scene` puis
`fight_animation.animate_fight`). La scène est celle de l'image de l'étage
dans `/tour` (`floor_scene`) : décor de la famille du premier ennemi, son
spot pour son élément, formation de sa zone.
"""

from __future__ import annotations

from pathlib import Path

from app.bot.rendering.fight_animation import MAX_UPLOAD_BYTES, WIDTH, Animation, animate_fight
from app.bot.rendering.fight_scene import build_scene
from app.domain.services.power_score_service import PowerScoreService
from app.domain.value_objects.party_battle_result import PartyBattleResult
from app.domain.value_objects.stats import Stats
from app.infrastructure.encounters import farm_zone_loader, mob_formation_loader, mob_placement_loader
from app.shared.paths import LANDSCAPES_ASSETS_DIR

#: Largeurs essayées : la vidéo doit passer sous la limite d'envoi de Discord.
WIDTHS = (WIDTH, 440)

_POWER = PowerScoreService()


def _payload(enemy: dict) -> dict:
    """Un ennemi de l'étage tel que la scène le dessine (nom, élément, puissance, PV)."""
    stats = Stats(max_hp=enemy["max_hp"], attack=enemy["attack"], defense=enemy["defense"],
                  crit_chance=enemy.get("crit_chance", 0), crit_damage=enemy.get("crit_damage", 100),
                  dodge=enemy.get("dodge", 0), hp_regeneration=0, speed=enemy.get("speed", 1))
    return {
        "code": enemy["code"], "name": enemy["name"], "image_name": enemy.get("image_name", ""),
        "element": enemy.get("element", ""), "current_hp": enemy["max_hp"], "max_hp": enemy["max_hp"],
        "attack": enemy["attack"], "defense": enemy["defense"], "speed": enemy.get("speed", 1),
        "crit_chance": enemy.get("crit_chance", 0), "crit_damage": enemy.get("crit_damage", 100),
        "dodge": enemy.get("dodge", 0),
        "power_score": _POWER.format_score(_POWER.calculate_from_stats(stats)),
    }


def floor_scene(floor_data: dict) -> dict:
    """Arguments de scène d'un étage (`build_scene`, `compose_players_banner`)."""
    enemies = floor_data["enemies"]
    first = enemies[0]
    family, element = first.get("family"), first.get("element", "")
    channel = farm_zone_loader.get_spawn_channel_for_family(family)
    background = farm_zone_loader.get_background_for_family(family)
    payloads = [_payload(e) for e in enemies]
    placements = [mob_placement_loader.get_placement(e["code"], e.get("element", "")) for e in enemies]
    scene = {
        "background_path": str(LANDSCAPES_ASSETS_DIR / background) if background else None,
        "spot": farm_zone_loader.get_spot(channel, element) if element else None,
    }
    if len(payloads) == 1:
        scene.update(mob=payloads[0], placement=placements[0])
    else:
        scene.update(mob=None, mobs=payloads, placements=placements,
                     formation=mob_formation_loader.get_formation(str(channel), len(payloads)))
    return scene


def render_tower_video(floor_data: dict, result: PartyBattleResult, avatar_url: str,
                       out_path: str | Path) -> Animation | None:
    """Le GIF du combat, ou None (combat vide, ou trop lourd même réduit)."""
    if not result.turn_logs:
        return None
    first = result.turn_logs[0]
    players = [dict(p, avatar_url=avatar_url) for p in first.players_state]
    # La tour se joue à PV pleins ; les ennemis partent eux aussi entiers.
    start_players = {f"p{p['player_id']}": (p["max_hp"], p["max_hp"]) for p in players}
    first_enemies = first.enemies_state or [first.mob_state]
    start_enemies = {
        f"e{i}": (e["max_hp"], e["max_hp"],
                  int((first_enemies[i] if i < len(first_enemies) else {}).get("shield", 0) or 0))
        for i, e in enumerate(floor_data["enemies"])
    }
    scene = build_scene(players=players, **floor_scene(floor_data))
    out_path = Path(out_path)
    for width in WIDTHS:
        anim = animate_fight(scene, start_enemies, start_players, result.turn_logs, out_path, width=width)
        if anim.size_bytes <= MAX_UPLOAD_BYTES:
            return anim
    out_path.unlink(missing_ok=True)
    return None
