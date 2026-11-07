"""Animation d'un combat (27/10/2026, demande de l'auteur) : au lieu d'une
image toutes les 1,5 s, une VIDÉO fluide qui se lance toute seule.

Le moteur a déjà tout le combat (`PartyBattleResult.turn_logs`, chacun avec
ses événements) : on le rejoue en images. Pour chaque action :

  • les barres de PV descendent en douceur vers leur nouvelle valeur ;
  • l'effet du coup apparaît en grossissant puis s'estompe ;
  • le chiffre jaillit (un peu plus gros), se pose, puis monte en s'effaçant ;
  • le monstre touché flashe ; un critique le fait trembler ;
  • un monstre vaincu s'assombrit après le coup qui l'achève.

Format : GIF (le seul que Discord lance tout seul, sur ordinateur et mobile)
qui ne boucle PAS ; le bot remplace le message par le récapitulatif une fois
la vidéo finie. Le décor est préparé une fois (`fight_scene.build_scene`) et
les effets une fois par action (`combat_fx.collect_fx`) : chaque image ne
recolle que ce qui bouge.

Mémoire (audit du 06/11/2026 : une longue vidéo prenait 840 Mo sur un VPS de
1,8 Go) : une image n'existe en couleurs que le temps d'être quantifiée
(`_GifFrames`), la vidéo se construit en images à palette (3 fois plus légères)
et les vidéos passent une à une (`render_queue`).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops

from app.bot.rendering import combat_fx
from app.bot.rendering.fight_scene import FRAME_H, FRAME_W, Scene

#: Réglages retenus après essais (cf. `scripts/bench_fight_animation.py`).
FPS = 10
WIDTH = 540
FRAMES_PER_ACTION = 6          # 0,6 s par action
QUIET_FRAMES = 2               # action sans rien à montrer (ex. annonce)
CRIT_EXTRA_FRAMES = 2          # un critique reste un peu plus à l'écran
INTRO_FRAMES = 6
OUTRO_MS = 1800
#: Un long combat est accéléré (moins d'images par action, jamais moins de
#: `MIN_FRAMES_PER_ACTION`) pour tenir dans cette durée.
MAX_SECONDS = 40
MIN_FRAMES_PER_ACTION = 3
SHAKE_PX = 9
#: Taille maximale d'une vidéo (envoi Discord sans boost : 10 Mo).
MAX_UPLOAD_BYTES = 9_500_000

#: Couleurs réservées dans la palette du GIF (effets et chiffres).
_FX_COLORS = [
    (255, 255, 255), (24, 10, 18), (255, 82, 72), (110, 240, 125), (100, 175, 255), (205, 140, 255),
    (255, 214, 90), (255, 245, 140), (255, 90, 40), (255, 150, 40), (255, 205, 80), (255, 110, 30),
    (110, 10, 20), (10, 60, 20), (10, 30, 70), (170, 230, 70), (230, 40, 60), (190, 240, 255),
    (150, 230, 255), (120, 190, 255), (255, 235, 150), (255, 190, 60), (70, 60, 60), (200, 200, 210),
]


@dataclass
class Animation:
    path: Path
    duration_s: float
    frames: int
    size_bytes: int


def _values(log) -> tuple[dict, dict]:
    enemies = {f"e{i}": (int(e.get("current_hp", 0) or 0), int(e.get("max_hp", 1) or 1),
                         int(e.get("shield", 0) or 0))
               for i, e in enumerate(log.enemies_state or [log.mob_state])}
    players = {f"p{p['player_id']}": (int(p.get("current_hp", 0) or 0), int(p.get("max_hp", 1) or 1))
               for p in log.players_state if p.get("player_id") is not None}
    return enemies, players


def _lerp_values(a: dict, b: dict, t: float) -> dict:
    out = {}
    for key, target in b.items():
        start = a.get(key, target)
        out[key] = tuple(s + (e - s) * t for s, e in zip(start, target))
    return out


def _with_alpha(layer: Image.Image, alpha: float) -> Image.Image:
    if alpha >= 0.999:
        return layer
    out = layer.copy()
    out.putalpha(layer.getchannel("A").point(lambda v: int(v * alpha)))
    return out


def _paste(frame: Image.Image, item: combat_fx.FxItem, scale: float, alpha: float, dy: float = 0) -> None:
    if alpha <= 0.02:
        return
    layer = item.layer
    if abs(scale - 1) > 0.01:
        layer = layer.resize((max(1, int(layer.width * scale)), max(1, int(layer.height * scale))),
                             Image.BILINEAR)
    combat_fx._paste_center(frame, _with_alpha(layer, alpha), item.cx, item.cy + dy)


def _flash_sprites(scene: Scene, events: list[dict]) -> list:
    hit = {e["target"] for e in events if e["kind"] in ("hit", "crit", "execute") and e["target"].startswith("e")}
    out = []
    for sprite in scene.sprites:
        if sprite.key in hit:
            white = Image.new("RGBA", sprite.img.size, (255, 255, 255, 255))
            flash = Image.blend(sprite.img, white, 0.55)
            flash.putalpha(sprite.img.getchannel("A"))
            out.append((flash, sprite.pos))
    return out


#: Index de palette réservé à la transparence : un pixel identique à
#: l'image précédente n'est pas réécrit (le GIF ne stocke que ce qui bouge).
_TRANSPARENT = 255


def _shaken_static(scene: Scene, dead: frozenset, shaken: set, offset: tuple[int, int]) -> Image.Image:
    """Le décor figé, les monstres de `shaken` décalés de `offset`."""
    img = scene.bg.copy()
    for sprite in scene.sprites:
        x, y = sprite.pos
        if sprite.key in shaken:
            x, y = x + offset[0], y + offset[1]
        img.alpha_composite(sprite.dimmed() if (scene.dim_dead and sprite.key in dead) else sprite.img,
                            (max(0, x), max(0, y)))
    img.alpha_composite(scene.overlay)
    return img


def _palette(sample: Image.Image) -> tuple[Image.Image, list[int]]:
    """Palette commune à toute la vidéo : le décor + les couleurs des effets
    (255 couleurs, la 256e est la transparence) — une palette par image ferait
    scintiller le décor."""
    base = sample.convert("RGB").quantize(colors=255 - len(_FX_COLORS), method=Image.Quantize.MEDIANCUT)
    colors = base.getpalette()[: 3 * (255 - len(_FX_COLORS))]
    while len(colors) < 3 * (255 - len(_FX_COLORS)):
        colors.extend((0, 0, 0))
    for c in _FX_COLORS:
        colors.extend(c)
    pal = Image.new("P", (1, 1))
    pal.putpalette(colors)          # 255 couleurs : l'index 255 n'est jamais choisi
    return pal, colors


class _GifFrames:
    """Les images de la vidéo, quantifiées dès qu'elles sont prêtes.

    La palette vient de la première image (le décor au repos, les couleurs des
    effets sont réservées) ; chaque image ne garde que ce qui a changé depuis
    la précédente (le reste est transparent)."""

    def __init__(self, size: tuple[int, int]) -> None:
        self.size = size
        self.frames: list[Image.Image] = []
        self.durations: list[int] = []
        self._palette: Image.Image | None = None
        self._colors: list[int] = []
        self._previous: Image.Image | None = None

    def push(self, img: Image.Image, ms: int) -> None:
        frame = img.convert("RGB").resize(self.size, Image.BILINEAR)
        if self._palette is None:
            self._palette, colors = _palette(frame)
            self._colors = colors + [255, 0, 255]
        q = frame.quantize(palette=self._palette, dither=Image.Dither.NONE)
        q.putpalette(self._colors)
        previous, self._previous = self._previous, q
        if previous is not None:
            # Pixels inchangés → transparents (l'image précédente reste visible).
            same = ImageChops.difference(Image.frombytes("L", q.size, q.tobytes()),
                                         Image.frombytes("L", q.size, previous.tobytes()))
            mask = same.point(lambda v: 255 if v == 0 else 0)
            q = q.copy()
            q.paste(_TRANSPARENT, mask=mask)
        self.frames.append(q)
        self.durations.append(ms)

    def save(self, out_path: Path) -> None:
        def remaining():
            # Chaque image est lâchée dès que Pillow l'a reprise : sinon elles
            # existent deux fois jusqu'à la fin de l'écriture.
            while frames:
                yield frames.popleft()

        frames = deque(self.frames)
        self.frames = []
        first = frames.popleft()
        # Sans `loop` : le GIF ne se joue qu'une fois.
        first.save(out_path, save_all=True, append_images=remaining(), duration=self.durations,
                   disposal=1, transparency=_TRANSPARENT, optimize=False)


def animate_fight(scene: Scene, start_enemies: dict, start_players: dict, logs: list,
                  out_path: str | Path, *, fps: int = FPS, width: int = WIDTH,
                  frames_per_action: int = FRAMES_PER_ACTION,
                  interlude=None, outro=None) -> Animation:
    """Rejoue les `logs` du combat en vidéo. `start_*` : les PV avant la
    première action ({clé: (PV, max[, bouclier])}). `interlude(log)` peut
    renvoyer des images plein cadre à intercaler (bascule de phase d'un
    boss…), `outro(dernière image)` celles de la fin. Renvoie le chemin, la
    durée et la taille."""
    out_path = Path(out_path)
    step_ms = int(1000 / fps)
    shown = sum(1 for log in logs if log.events)
    budget = max(1, MAX_SECONDS * fps - INTRO_FRAMES)
    if shown * frames_per_action > budget:   # long combat : accéléré
        frames_per_action = max(MIN_FRAMES_PER_ACTION, budget // max(1, shown))
    video = _GifFrames((width, round(width * FRAME_H / FRAME_W)))

    def push(img: Image.Image, ms: int = step_ms) -> None:
        video.push(img, ms)

    enemies = {k: (v + (0,))[:3] for k, v in start_enemies.items()}
    players = dict(start_players)
    dead = frozenset(k for k, v in enemies.items() if v[0] <= 0)
    intro = scene.static(dead).copy()
    scene.draw_bars(intro, enemies, players)
    for _ in range(INTRO_FRAMES):
        push(intro)

    for index, log in enumerate(logs):
        target_enemies, target_players = _values(log)
        new_dead = frozenset(k for k, v in target_enemies.items() if v[0] <= 0)
        events = log.events or []
        if interlude is not None:
            for img, ms in interlude(log) or ():
                push(img, ms)
        items = combat_fx.collect_fx(events, scene.anchors, (FRAME_W, FRAME_H), seed=log.turn_number)
        crit = any(e["kind"] in ("crit", "execute") for e in events)
        # Le monstre frappé d'un critique tremble (lui seul : faire trembler
        # toute l'image réécrivait le décor entier dans le GIF, mesuré ×2).
        shaken = {e["target"] for e in events if e["kind"] in ("crit", "execute") and e["target"].startswith("e")}
        flashes = _flash_sprites(scene, events)
        if not items and not events:
            n = 1 if frames_per_action < FRAMES_PER_ACTION else QUIET_FRAMES
        else:
            n = frames_per_action + (CRIT_EXTRA_FRAMES if crit and frames_per_action >= FRAMES_PER_ACTION else 0)
        for k in range(n):
            t_bar = min(1.0, (k + 1) / 3)
            if shaken and k < 2:
                frame = _shaken_static(scene, dead, shaken,
                                       (SHAKE_PX, -SHAKE_PX // 2) if k == 0 else (-SHAKE_PX // 2, SHAKE_PX // 3))
            else:
                frame = scene.static(dead if k < 2 else new_dead).copy()
            if k == 0:
                for img, pos in flashes:
                    frame.alpha_composite(img, pos)
            scene.draw_bars(frame, _lerp_values(enemies, target_enemies, t_bar),
                            _lerp_values(players, target_players, t_bar))
            # L'effet est un ÉCLAT bref (2 images, une 3e en fondu) : son fondu
            # lent sur un décor détaillé doublait le poids du GIF (mesuré).
            fade = 1.0 if k < 2 else (0.45 if k == 2 else 0.0)
            for item in items:
                if item.role == "effect":
                    _paste(frame, item, 0.85 if k == 0 else 1.0, fade)
                else:
                    scale = 1.35 if k == 0 else (1.1 if k == 1 else 1.0)
                    alpha = 1.0 if k < n - 1 else 0.55
                    _paste(frame, item, scale, alpha, dy=-9 * max(0, k - 1))
            push(frame)
        enemies, players, dead = target_enemies, target_players, new_dead

    closing = list(outro(_final(scene, dead, enemies, players)) or ()) if outro is not None else []
    if closing:
        for img, ms in closing:
            push(img, ms)
    elif video.durations:
        video.durations[-1] = OUTRO_MS
    count = len(video.frames)
    video.save(out_path)
    return Animation(out_path, sum(video.durations) / 1000, count, out_path.stat().st_size)


def _final(scene: Scene, dead: frozenset, enemies: dict, players: dict) -> Image.Image:
    """La dernière image, sans effet ni chiffre."""
    img = scene.static(dead).copy()
    scene.draw_bars(img, enemies, players)
    return img
