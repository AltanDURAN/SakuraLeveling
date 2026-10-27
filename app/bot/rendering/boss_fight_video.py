"""Vidéo d'un assaut de world boss (27/10/2026, demande de l'auteur : « rien
qui fait waou pour un boss »).

Même moteur que les combats de zone (`fight_animation`), avec la mise en
scène d'un boss :

  • l'ARÈNE : `assets/landscapes/arene_<code>.png` si le boss a la sienne,
    sinon la salle commune `arene_boss.png` ; tant qu'elle n'existe pas, le
    décor de zone de son élément, assombri ;
  • le boss au centre, en grand, ses gardes devant lui de part et d'autre ;
    une barre géante en haut, marquée de ses phases (75 / 50 / 25 %) ;
  • un carton d'ouverture, puis un carton à chaque bascule de phase ;
  • les TEMPS FORTS seulement : un assaut dure jusqu'à 180 actions, on en
    garde `HIGHLIGHTS` (phases, charges et ultimes, K.O., critiques, gros
    coups…) — les barres de PV restent justes, elles suivent l'état réel.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance

from app.bot.rendering import combat_fx
from app.bot.rendering.fight_animation import WIDTH, Animation, _values, animate_fight
from app.bot.rendering.fight_scene import FRAME_H, FRAME_W, Scene, build_scene
from app.shared.formatters import format_int
from app.shared.paths import GENERATED_ENCOUNTERS_DIR, LANDSCAPES_ASSETS_DIR

#: Actions montrées au plus (≈ 0,6 s chacune).
HIGHLIGHTS = 36
#: Toujours montrées : le début de l'assaut et sa fin.
OPENING, ENDING = 4, 3
#: Événements qu'on ne coupe jamais.
_KEY_KINDS = {"phase", "charge", "ko", "revive", "execute", "hold", "enrage"}
#: Formation : les gardes devant, de part et d'autre ; le boss en retrait, en grand.
GUARD_SLOTS = ({"x": -0.33, "y": 0.0, "scale": 0.62}, {"x": 0.33, "y": 0.0, "scale": 0.62},
               {"x": -0.18, "y": 0.02, "scale": 0.55}, {"x": 0.18, "y": 0.02, "scale": 0.55})
BOSS_SLOT = {"x": 0.0, "y": -0.035, "scale": 1.3}
#: Décor de repli par élément (en attendant l'arène).
_ELEMENT_DECORS = {
    "eau": "clairiere_sinistre_eau.png", "plante": "clairiere_sinistre_plante.png",
    "feu": "berceau_cataclysmique_feu.png", "terre": "berceau_cataclysmique_terre.png",
    "tenebre": "cimetiere_abandonne_tenebre.png", "lumiere": "cimetiere_abandonne_lumiere.png",
    "glace": "cimetiere_abandonne_glace.png", "vent": "cimetiere_abandonne_vent.png",
}
INTRO_MS = 1500
PHASE_MS = 1500
OUTRO_MS = 2600


def arena_path(code: str, element: str = "") -> str:
    """Le décor de l'assaut : l'arène du boss, la salle commune, ou en
    attendant le décor de zone de son élément assombri (préparé une fois)."""
    for name in (f"arene_{code}.png", "arene_boss.png"):
        if (LANDSCAPES_ASSETS_DIR / name).exists():
            return str(LANDSCAPES_ASSETS_DIR / name)
    source = LANDSCAPES_ASSETS_DIR / _ELEMENT_DECORS.get(element, "berceau_cataclysmique.png")
    if not source.exists():
        source = LANDSCAPES_ASSETS_DIR / "berceau_cataclysmique.png"
    out = GENERATED_ENCOUNTERS_DIR / f"arene_repli_{source.stem}.png"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        ImageEnhance.Brightness(Image.open(source).convert("RGB")).enhance(0.6).save(out)
    return str(out)


def _score(log, max_hp: dict[str, int]) -> float:
    """Intérêt d'une action pour le résumé (un coup vaut selon la part des
    PV qu'il retire à sa cible)."""
    score = 0.0
    for e in log.events or []:
        if e["kind"] in _KEY_KINDS or e.get("style") == "ultimate":
            return 1e9
        share = (e.get("amount", 0) or 0) / max(1, max_hp.get(e.get("target", ""), 1))
        score += {"crit": 6, "heal": 2, "shield": 2, "dodge": 1.5, "stun": 3, "block": 1}.get(e["kind"], 1)
        score += min(10.0, share * 20)
    return score


def select_highlights(logs: list, limit: int = HIGHLIGHTS) -> list:
    """Les temps forts de l'assaut, dans l'ordre : le début, la fin, tout ce
    qui ne se coupe pas, puis les actions les plus fortes."""
    shown = [i for i, log in enumerate(logs) if log.events]
    if len(shown) <= limit:
        return [logs[i] for i in shown]
    enemies, players = _values(logs[0])
    max_hp = {k: v[1] for k, v in {**enemies, **players}.items()}
    scores = {i: _score(logs[i], max_hp) for i in shown}
    keep = set(shown[:OPENING]) | set(shown[-ENDING:])
    keep |= {i for i in shown if scores[i] >= 1e9}
    rest = sorted((i for i in shown if i not in keep), key=lambda i: (-scores[i], i))
    keep |= set(rest[: max(0, limit - len(keep))])
    return [logs[i] for i in sorted(keep)]


def _card(frame: Image.Image, title: str, subtitle: str, color) -> Image.Image:
    """Carton plein cadre : l'image assombrie, un bandeau, le titre."""
    img = ImageEnhance.Brightness(frame.convert("RGB")).enhance(0.45).convert("RGBA")
    band = Image.new("RGBA", img.size, (0, 0, 0, 0))
    y1, y2 = int(FRAME_H * 0.36), int(FRAME_H * 0.60)
    ImageDraw.Draw(band).rectangle([0, y1, FRAME_W, y2], fill=(12, 6, 10, 200))
    ImageDraw.Draw(band).line([(0, y1), (FRAME_W, y1)], fill=(*color, 255), width=5)
    ImageDraw.Draw(band).line([(0, y2), (FRAME_W, y2)], fill=(*color, 255), width=5)
    img.alpha_composite(band)
    head = combat_fx._text_layer(title, 132, color, stroke=(30, 6, 10))
    combat_fx._paste_center(img, head, FRAME_W / 2, y1 + (y2 - y1) * 0.40)
    if subtitle:
        size = 58
        sub = combat_fx._text_layer(subtitle, size, (255, 240, 225))
        while sub.width > FRAME_W - 40 and size > 30:
            size -= 4
            sub = combat_fx._text_layer(subtitle, size, (255, 240, 225))
        combat_fx._paste_center(img, sub, FRAME_W / 2, y1 + (y2 - y1) * 0.78)
    return img


def phase_number(name: str, phases: list[dict]) -> int:
    """« Phase 2 » pour le premier seuil (la phase 1 est le boss au départ)."""
    ordered = sorted(phases, key=lambda ph: -float(ph.get("below_pct", 0)))
    for k, ph in enumerate(ordered):
        if ph.get("name") == name:
            return k + 2
    return 2


def render_boss_video(*, boss: dict, guards: list[dict], boss_index: int, players: list[dict],
                      logs: list, boss_hp_before: int, phases: list[dict], out_path: str | Path,
                      background_path: str, width: int = WIDTH) -> Animation:
    """La vidéo de l'assaut. `boss` / `guards` : {name, image_name, element,
    max_hp, code} ; `players` : {player_id, name, avatar_url, max_hp} ;
    `logs` : les tours du combat."""
    mobs = [*guards[:boss_index], boss, *guards[boss_index:]]
    slots = list(GUARD_SLOTS[: len(guards)])
    left = [s for s in slots if s["x"] < 0][:boss_index]
    right = [s for s in slots if s["x"] > 0][: len(guards) - boss_index]
    formation = [*left, BOSS_SLOT, *right]
    ticks = tuple(sorted(float(ph.get("below_pct", 0)) / 100 for ph in phases if ph.get("below_pct")))
    scene: Scene = build_scene(mob=None, players=players, background_path=background_path,
                               mobs=mobs, formation=formation, boss_index=boss_index,
                               phase_ticks=ticks)
    start_enemies = {f"e{i}": (int(m["max_hp"]), int(m["max_hp"]), 0) for i, m in enumerate(mobs)}
    start_enemies[f"e{boss_index}"] = (int(boss_hp_before), int(boss["max_hp"]), 0)
    start_players = {f"p{p['player_id']}": (int(p["max_hp"]), int(p["max_hp"])) for p in players}
    chosen = select_highlights(logs)
    first = chosen[0] if chosen else None

    def interlude(log):
        frames = []
        if log is first:
            intro = scene.static().copy()
            scene.draw_bars(intro, start_enemies, start_players)
            frames.append((_card(intro, "ASSAUT !", str(boss.get("name", "")), (255, 196, 90)), INTRO_MS))
        for e in log.events or []:
            if e["kind"] == "phase":
                enemies, players_hp = _values(log)
                img = scene.static(frozenset(k for k, v in enemies.items() if v[0] <= 0)).copy()
                scene.draw_bars(img, enemies, players_hp)
                name = e.get("style", "")
                frames.append((_card(img, f"PHASE {phase_number(name, phases)}", name, (255, 90, 70)),
                               PHASE_MS))
        return frames

    def outro(last: Image.Image):
        boss_hp = int((logs[-1].enemies_state or [{}] * (boss_index + 1))[boss_index].get("current_hp", 0)
                      or 0) if logs else int(boss_hp_before)
        if boss_hp <= 0:
            return [(_card(last, "VAINCU !", str(boss.get("name", "")), (255, 214, 90)), OUTRO_MS)]
        dealt = max(0, int(boss_hp_before) - boss_hp)
        return [(_card(last, "FIN DE L'ASSAUT", f"-{format_int(dealt)} PV au boss", (255, 196, 90)), OUTRO_MS)]

    return animate_fight(scene, start_enemies, start_players, chosen, out_path, width=width,
                         interlude=interlude, outro=outro)
