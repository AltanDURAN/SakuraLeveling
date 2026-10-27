"""Chiffres et effets de combat dessinés PAR-DESSUS la scène (27/10/2026).

Demande de l'auteur : rendre les combats vivants et lisibles. Chaque image du
combat correspond à UNE action ; le moteur y joint ses événements
(`PartyBattleTurnLog.events`, cf. `PartyCombatService._emit`) et on les
dessine ici, sur la cible :

  • un CHIFFRE dont la taille suit la part des PV retirée à la cible, entre
    `MIN_SIZE` et `MAX_SIZE` (un coup à 1 % des PV reste lisible, un coup à
    40 % et plus est énorme) ;
  • un EFFET selon l'attaque : entaille, griffure, morsure, coup sourd,
    estoc, magie, foudre, flammes, explosion, onde de choc… teinté par
    l'élément infusé (joueurs) ou l'élément du monstre ;
  • les CRITIQUES : chiffre plus gros, dégradé or → rouge, « CRITIQUE ! »,
    éclat étoilé derrière ; soins en vert, boucliers en bleu, poison,
    saignement et brûlure à leurs couleurs, esquives, immunités, K.O.

Tout est dessiné au code (aucune image à fournir) ; la police des chiffres
est Bangers (OFL, `assets/fonts`), DejaVu en repli. Le tirage des petites
variations (angle, décalage) est fixé par le numéro du tour : la même image
pour le même combat.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.bot.rendering.element_visuals import ELEMENT_COLORS
from app.shared.paths import ASSETS_DIR

FONT_PATH = ASSETS_DIR / "fonts" / "Bangers-Regular.ttf"
MIN_SIZE = 64
MAX_SIZE = 128
#: Part des PV de la cible à partir de laquelle le chiffre est au maximum.
FULL_SIZE_SHARE = 0.30
CRIT_SCALE = 1.25
PLAYER_SCALE = 0.8           # les avatars sont petits : chiffres un peu plus sobres
#: Zone d'effet minimale autour d'un avatar (il ne fait que ~90 px).
PLAYER_FX_SPAN = 230
#: Le chiffre ne recouvre jamais le bandeau du haut ni celui du bas.
TOP_LIMIT, BOTTOM_LIMIT = 168, 1188

WHITE = (255, 255, 255)
DARK = (24, 10, 18)
RED = (255, 82, 72)
GREEN = (110, 240, 125)
BLUE = (100, 175, 255)
VIOLET = (205, 140, 255)
GREY = (200, 200, 210)
GOLD = (255, 214, 90)
DOT_COLORS = {"poison": (170, 230, 70), "bleed": (230, 40, 60), "burn": (255, 140, 40)}

#: Style d'attaque de chaque monstre (le reste : entaille).
MOB_STYLES: dict[str, str] = {
    **dict.fromkeys(("loup_sacre", "ours_colosse", "goule", "loup_garou", "chauve_souris_geante",
                     "aigle_tempete", "wyverne", "diablotin", "archidemon", "gargouille",
                     "demon_cornu"), "claw"),
    **dict.fromkeys(("serpent_des_racines", "cerbere", "vampire_noble", "dragonnet", "drake_de_braise",
                     "dragon_de_givre", "dragon_ancien", "devoreur", "zombie", "kraken_astral"), "bite"),
    **dict.fromkeys(("slime", "gobelin_geant", "golem_de_mousse", "ogre_demoniaque", "gardien_draconique",
                     "chevalier_de_l_eclipse", "gobelin_superieur", "momie", "cerf_esprit"), "blunt"),
    **dict.fromkeys(("liche_maudite", "banshee", "fantome", "sorciere_de_sang", "gobelin_chaman",
                     "succube", "ange_dechu", "heraut_du_vide", "oeil_errant", "seraphin_brise",
                     "avatar_du_neant", "rejeton_du_neant", "gobelin_runique"), "magic"),
    **dict.fromkeys(("kobold", "gobelin_assassin"), "pierce"),
    "gobelin_ballon": "explosion",
}
#: Style d'un événement du moteur → effet dessiné.
_PLAYER_STYLES = {
    "slash": "slash", "counter": "slash", "double": "double", "dive": "pierce", "storm": "lightning",
    "splash": "explosion", "fire": "flame", "void": "magic", "holy": "magic", "charm": "magic",
    "reflect": "spark", "guard": "blunt", "summon": "claw", "assassinate": "pierce",
    "explosion": "explosion", "aoe": "shockwave", "ultimate": "ultimate",
}
ULTIMATE_COLOR = (255, 70, 40)


@dataclass
class Anchor:
    """Où dessiner sur une cible : sa boîte à l'image, ses PV max, son
    élément (teinte) et, pour un monstre, son code (style de ses coups)."""
    x: int
    y: int
    w: int
    h: int
    max_hp: int
    element: str = ""
    code: str = ""
    player: bool = False

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


# ----------------------------------------------------------------- police
_FONTS: dict[int, ImageFont.FreeTypeFont] = {}


def _font(size: int) -> ImageFont.FreeTypeFont:
    if size not in _FONTS:
        try:
            _FONTS[size] = ImageFont.truetype(str(FONT_PATH), size)
        except OSError:
            try:
                _FONTS[size] = ImageFont.truetype("DejaVuSans-Bold.ttf", int(size * 0.8))
            except OSError:
                _FONTS[size] = ImageFont.load_default()
    return _FONTS[size]


def number_size(amount: int, max_hp: int, crit: bool = False, player: bool = False) -> int:
    """Taille du chiffre : selon la part des PV retirée, entre MIN et MAX."""
    share = amount / max(1, max_hp)
    t = min(1.0, max(0.0, share / FULL_SIZE_SHARE)) ** 0.5
    size = MIN_SIZE + (MAX_SIZE - MIN_SIZE) * t
    if crit:
        size *= CRIT_SCALE
    if player:
        size *= PLAYER_SCALE
    return int(round(min(size, MAX_SIZE * CRIT_SCALE)))


def _mix(a, b, t: float) -> tuple[int, int, int]:
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


# ------------------------------------------------------------- textes
def _text_layer(text: str, size: int, fill, *, gradient: tuple | None = None,
                stroke=DARK, label: str = "", label_color=None) -> Image.Image:
    """Le chiffre (ou le mot) avec contour épais, ombre portée, dégradé
    éventuel, et une petite étiquette au-dessus (« CRITIQUE ! »)."""
    font = _font(size)
    stroke_w = max(3, size // 11)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    l, t, r, b = probe.textbbox((0, 0), text, font=font, stroke_width=stroke_w)
    label_font = _font(max(20, size // 3))
    lw = lh = 0
    if label:
        ll, lt, lr, lb = probe.textbbox((0, 0), label, font=label_font, stroke_width=3)
        lw, lh = lr - ll, lb - lt + 4
    pad = stroke_w + 10
    W = max(r - l, lw) + pad * 2
    H = (b - t) + lh + pad * 2
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ox = (W - (r - l)) // 2 - l
    oy = pad + lh - t
    # Ombre portée.
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text((ox + 4, oy + 5), text, font=font, fill=(0, 0, 0, 170),
                                stroke_width=stroke_w, stroke_fill=(0, 0, 0, 170))
    layer.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(3)))
    d = ImageDraw.Draw(layer)
    d.text((ox, oy), text, font=font, fill=fill, stroke_width=stroke_w, stroke_fill=stroke)
    if gradient:
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).text((ox, oy), text, font=font, fill=255)
        top, bottom = gradient
        grad = Image.new("RGBA", (W, H))
        gd = ImageDraw.Draw(grad)
        for y in range(H):
            gd.line([(0, y), (W, y)], fill=(*_mix(top, bottom, y / max(1, H - 1)), 255))
        layer.paste(grad, (0, 0), mask)
    if label:
        lx = (W - lw) // 2
        d.text((lx, pad // 2), label, font=label_font, fill=label_color or WHITE,
               stroke_width=3, stroke_fill=DARK)
    return layer


@dataclass
class FxItem:
    """Un calque d'effet ou de chiffre, centré en (cx, cy) — pour l'animation."""
    layer: Image.Image
    cx: float
    cy: float
    role: str          # "effect" ou "label"


class FxCollector:
    """Remplace l'image de destination : collecte les calques au lieu de les
    coller (l'animation les transforme ensuite image par image)."""

    def __init__(self, width: int, height: int) -> None:
        self.width, self.height = width, height
        self.items: list[FxItem] = []
        self.role = "effect"


def collect_fx(events: list[dict] | None, anchors: dict[str, "Anchor"], size: tuple[int, int],
               seed: int = 0) -> list[FxItem]:
    """Les calques des événements d'une action, sans les coller."""
    collector = FxCollector(*size)
    draw_combat_fx(collector, events, anchors, seed=seed)
    return collector.items


def _paste_center(base, layer: Image.Image, cx: float, cy: float, angle: float = 0) -> None:
    if angle:
        layer = layer.rotate(angle, resample=Image.BICUBIC, expand=True)
    if isinstance(base, FxCollector):
        base.items.append(FxItem(layer, cx, cy, base.role))
        return
    x = int(round(cx - layer.width / 2))
    y = int(round(cy - layer.height / 2))
    # Un calque qui déborde du cadre est rogné (Pillow refuse une position négative).
    left, top = max(0, -x), max(0, -y)
    right = min(layer.width, base.width - x)
    bottom = min(layer.height, base.height - y)
    if right <= left or bottom <= top:
        return
    base.alpha_composite(layer.crop((left, top, right, bottom)), (x + left, y + top))


# ------------------------------------------------------------- effets
def _span(a: Anchor, k: float = 1.0, lo: float = 170, hi: float = 520) -> float:
    """Taille d'un effet sur une cible : selon sa surface (un monstre étroit
    garde un effet lisible), bornée."""
    return max(lo, min(hi, (a.w * a.h) ** 0.5)) * k


def _glow_layer(size: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    return layer, ImageDraw.Draw(layer)


def _finish(base: Image.Image, glow: Image.Image, core: Image.Image, cx: float, cy: float,
            blur: float) -> None:
    """Halo flouté sous un trait net : l'effet « lumineux »."""
    out = glow.filter(ImageFilter.GaussianBlur(blur))
    out.alpha_composite(core)
    _paste_center(base, out, cx, cy)


def _streak(draw: ImageDraw.ImageDraw, c: float, angle: float, length: float, width: float,
            color, offset: float = 0) -> None:
    """Un trait effilé aux deux bouts (entaille), centré sur (c, c)."""
    dx, dy = math.cos(angle), math.sin(angle)
    nx, ny = -dy, dx
    pts_top, pts_bottom = [], []
    for i in range(21):
        s = i / 20
        along = (s - 0.5) * length
        half = width * math.sin(math.pi * s) ** 0.8 / 2
        px = c + dx * along + nx * offset
        py = c + dy * along + ny * offset
        pts_top.append((px + nx * half, py + ny * half))
        pts_bottom.append((px - nx * half, py - ny * half))
    draw.polygon(pts_top + pts_bottom[::-1], fill=color)


def _star_points(c: float, spikes: int, r_out: float, r_in: float, rot: float = 0) -> list:
    pts = []
    for i in range(spikes * 2):
        r = r_out if i % 2 == 0 else r_in
        a = rot + math.pi * i / spikes
        pts.append((c + r * math.cos(a), c + r * math.sin(a)))
    return pts


def _fx_slash(base, a: Anchor, color, rng, crosses: int = 1, claws: int = 1, scale: float = 1.0) -> None:
    span = _span(a, 1.0) * scale
    size = int(span * 1.7) + 40
    c = size / 2
    glow, gd = _glow_layer(size)
    core, cd = _glow_layer(size)
    base_angle = math.radians(rng.uniform(-60, -35))
    for k in range(crosses):
        angle = base_angle + (math.radians(rng.uniform(70, 100)) if k else 0)
        for j in range(claws):
            off = (j - (claws - 1) / 2) * span * 0.16
            width = span * (0.05 if claws == 1 else 0.035)
            _streak(gd, c, angle, span * 1.15, width * 3.2, (*color, 220), off)
            _streak(cd, c, angle, span * 1.1, width, (255, 255, 255, 250), off)
    _finish(base, glow, core, a.cx, a.cy, max(4, span / 30))


def _fx_burst(base, a: Anchor, rng, scale: float = 1.0) -> None:
    """Éclat doré derrière un critique : des rayons, sans masquer la cible."""
    span = _span(a, 1.1) * scale
    size = int(span * 1.4) + 40
    c = size / 2
    glow, gd = _glow_layer(size)
    core, cd = _glow_layer(size)
    rot = rng.uniform(0, math.pi)
    gd.polygon(_star_points(c, 16, span * 0.6, span * 0.2, rot), fill=(255, 190, 60, 150))
    cd.polygon(_star_points(c, 16, span * 0.42, span * 0.08, rot), fill=(255, 235, 150, 150))
    _finish(base, glow, core, a.cx, a.cy, max(6, span / 22))


def _fx_pierce(base, a: Anchor, color, rng, scale: float = 1.0) -> None:
    span = _span(a, 1.0) * scale
    size = int(span * 1.4) + 40
    c = size / 2
    glow, gd = _glow_layer(size)
    core, cd = _glow_layer(size)
    angle = math.radians(rng.uniform(-15, 15) + 180)
    _streak(gd, c, angle, span, span * 0.12, (*color, 210))
    _streak(cd, c, angle, span * 0.95, span * 0.04, (255, 255, 255, 250))
    tip = (c - math.cos(angle) * span * 0.48, c - math.sin(angle) * span * 0.48)
    star = [(tip[0] - c + x, tip[1] - c + y) for x, y in _star_points(c, 6, span * 0.16, span * 0.05)]
    gd.polygon(star, fill=(*color, 230))
    cd.polygon([(tip[0] - c + x, tip[1] - c + y) for x, y in _star_points(c, 6, span * 0.08, span * 0.025)],
               fill=(255, 255, 255, 255))
    _finish(base, glow, core, a.cx, a.cy, max(4, span / 28))


def _fx_bite(base, a: Anchor, color, rng, scale: float = 1.0) -> None:
    span = _span(a, 0.85) * scale
    size = int(span * 1.5) + 40
    c = size / 2
    glow, gd = _glow_layer(size)
    core, cd = _glow_layer(size)
    teeth = 6
    for row, sign in ((-1, 1), (1, -1)):
        y0 = c + row * span * 0.22
        for i in range(teeth):
            x0 = c - span / 2 + span * i / teeth
            x1 = x0 + span / teeth
            curve = math.sin(math.pi * (i + 0.5) / teeth) * span * 0.08 * -row
            tooth = [(x0, y0 + curve), (x1, y0 + curve), ((x0 + x1) / 2, y0 + curve + sign * span * 0.2)]
            gd.polygon(tooth, fill=(*color, 220))
            shrink = [(x0 + span * 0.015, y0 + curve), (x1 - span * 0.015, y0 + curve),
                      ((x0 + x1) / 2, y0 + curve + sign * span * 0.15)]
            cd.polygon(shrink, fill=(255, 255, 255, 240))
    _finish(base, glow, core, a.cx, a.cy, max(4, span / 26))


def _fx_blunt(base, a: Anchor, color, rng, scale: float = 1.0, spikes: int = 11) -> None:
    span = _span(a, 0.8) * scale
    size = int(span * 1.4) + 40
    c = size / 2
    glow, gd = _glow_layer(size)
    core, cd = _glow_layer(size)
    rot = rng.uniform(0, math.pi)
    gd.polygon(_star_points(c, spikes, span * 0.55, span * 0.28, rot), fill=(*color, 220))
    cd.polygon(_star_points(c, spikes, span * 0.36, span * 0.17, rot), fill=(255, 250, 225, 240))
    for _ in range(7):
        ang, dist = rng.uniform(0, 2 * math.pi), rng.uniform(0.45, 0.7) * span
        r = span * rng.uniform(0.02, 0.045)
        x, y = c + math.cos(ang) * dist, c + math.sin(ang) * dist
        cd.ellipse([x - r, y - r, x + r, y + r], fill=(*_mix(color, WHITE, 0.4), 230))
    _finish(base, glow, core, a.cx, a.cy, max(5, span / 22))


def _fx_explosion(base, a: Anchor, color, rng, scale: float = 1.0) -> None:
    span = _span(a, 0.95) * scale
    size = int(span * 1.6) + 40
    c = size / 2
    glow, gd = _glow_layer(size)
    core, cd = _glow_layer(size)
    fire = _mix(color, (255, 120, 30), 0.6)
    rot = rng.uniform(0, math.pi)
    # Fumée, puis boule de feu en couronnes irrégulières, cœur blanc.
    for _ in range(7):
        ang, dist = rng.uniform(0, 2 * math.pi), rng.uniform(0.35, 0.55) * span
        r = span * rng.uniform(0.10, 0.16)
        x, y = c + math.cos(ang) * dist, c + math.sin(ang) * dist
        gd.ellipse([x - r, y - r, x + r, y + r], fill=(70, 60, 60, 120))
    gd.polygon(_star_points(c, 18, span * 0.62, span * 0.36, rot), fill=(*fire, 200))
    cd.polygon(_star_points(c, 12, span * 0.42, span * 0.24, rot + 0.2), fill=(255, 150, 40, 170))
    cd.polygon(_star_points(c, 9, span * 0.28, span * 0.16, rot + 0.5), fill=(255, 215, 100, 200))
    cd.ellipse([c - span * 0.11, c - span * 0.11, c + span * 0.11, c + span * 0.11], fill=(255, 250, 225, 230))
    out = glow.filter(ImageFilter.GaussianBlur(max(8, span / 12)))
    out.alpha_composite(core.filter(ImageFilter.GaussianBlur(max(2, span / 60))))
    _paste_center(base, out, a.cx, a.cy)


def _fx_shockwave(base, a: Anchor, color, rng, scale: float = 1.0) -> None:
    span = max(a.w, a.h) * 1.15 * scale
    size = int(span * 1.2) + 40
    c = size / 2
    glow, gd = _glow_layer(size)
    core, cd = _glow_layer(size)
    for k, (rx, ry) in enumerate(((0.5, 0.22), (0.38, 0.16))):
        box = [c - span * rx, c - span * ry, c + span * rx, c + span * ry]
        gd.ellipse(box, outline=(*color, 200), width=int(span * 0.05))
        cd.ellipse(box, outline=(255, 255, 255, 220 - k * 70), width=max(2, int(span * 0.015)))
    _finish(base, glow, core, a.cx, a.cy, max(4, span / 30))


def _fx_charge(base, a: Anchor, rng) -> None:
    """Le boss rassemble ses forces : un anneau d'énergie rouge qui se
    resserre sur lui (avant son attaque ultime)."""
    span = max(a.w, a.h) * 0.95
    size = int(span * 1.2) + 40
    c = size / 2
    glow, gd = _glow_layer(size)
    core, cd = _glow_layer(size)
    gd.ellipse([c - span * 0.5, c - span * 0.5, c + span * 0.5, c + span * 0.5],
               outline=(*ULTIMATE_COLOR, 210), width=int(span * 0.06))
    cd.ellipse([c - span * 0.46, c - span * 0.46, c + span * 0.46, c + span * 0.46],
               outline=(255, 220, 160, 230), width=max(3, int(span * 0.012)))
    for i in range(10):
        ang = 2 * math.pi * i / 10 + rng.uniform(-0.15, 0.15)
        r1, r2 = span * 0.52, span * 0.30
        cd.line([(c + math.cos(ang) * r1, c + math.sin(ang) * r1),
                 (c + math.cos(ang) * r2, c + math.sin(ang) * r2)],
                fill=(255, 200, 140, 230), width=max(3, int(span * 0.014)))
    _finish(base, glow, core, a.cx, a.cy, max(6, span / 22))


def _fx_ultimate(base, a: Anchor, rng, scale: float = 1.0) -> None:
    """L'attaque ultime d'un boss : explosion rouge et onde de choc."""
    _fx_explosion(base, a, ULTIMATE_COLOR, rng, scale=scale * 1.25)
    _fx_shockwave(base, a, ULTIMATE_COLOR, rng, scale=scale)


def _fx_phase(base, a: Anchor, rng) -> None:
    """Bascule de phase : une aura rouge qui enveloppe le boss."""
    span = max(a.w, a.h) * 1.05
    size = int(span * 1.3) + 40
    c = size / 2
    glow, gd = _glow_layer(size)
    core, cd = _glow_layer(size)
    gd.ellipse([c - span * 0.5, c - span * 0.55, c + span * 0.5, c + span * 0.55], fill=(200, 30, 40, 70))
    gd.ellipse([c - span * 0.5, c - span * 0.55, c + span * 0.5, c + span * 0.55],
               outline=(255, 60, 50, 200), width=int(span * 0.05))
    _finish(base, glow, core, a.cx, a.cy, max(10, span / 12))


def _sparkle(draw, x, y, r, color) -> None:
    draw.polygon([(x, y - r), (x + r * 0.25, y - r * 0.25), (x + r, y), (x + r * 0.25, y + r * 0.25),
                  (x, y + r), (x - r * 0.25, y + r * 0.25), (x - r, y), (x - r * 0.25, y - r * 0.25)],
                 fill=color)


def _fx_magic(base, a: Anchor, color, rng, scale: float = 1.0) -> None:
    span = _span(a, 0.8) * scale
    size = int(span * 1.5) + 40
    c = size / 2
    glow, gd = _glow_layer(size)
    core, cd = _glow_layer(size)
    gd.ellipse([c - span * 0.42, c - span * 0.42, c + span * 0.42, c + span * 0.42], fill=(*color, 170))
    cd.ellipse([c - span * 0.36, c - span * 0.36, c + span * 0.36, c + span * 0.36],
               outline=(*_mix(color, WHITE, 0.6), 235), width=max(3, int(span * 0.03)))
    cd.ellipse([c - span * 0.14, c - span * 0.14, c + span * 0.14, c + span * 0.14], fill=(255, 255, 255, 230))
    for i in range(6):
        ang = rng.uniform(0, 2 * math.pi)
        dist = rng.uniform(0.3, 0.6) * span
        _sparkle(cd, c + math.cos(ang) * dist, c + math.sin(ang) * dist, span * rng.uniform(0.05, 0.09),
                 (255, 255, 255, 240))
    _finish(base, glow, core, a.cx, a.cy, max(6, span / 14))


def _fx_lightning(base, a: Anchor, color, rng, scale: float = 1.0) -> None:
    span = max(170, min(a.h * 0.85, 460)) * scale
    size = int(span * 1.3) + 40
    c = size / 2
    glow, gd = _glow_layer(size)
    core, cd = _glow_layer(size)
    pts, x = [], c + rng.uniform(-span * 0.1, span * 0.1)
    for i in range(8):
        pts.append((x, c - span / 2 + span * i / 7))
        x += rng.uniform(-span * 0.12, span * 0.12)
    gd.line(pts, fill=(120, 190, 255, 240), width=int(span * 0.08), joint="curve")
    cd.line(pts, fill=(255, 255, 255, 255), width=max(3, int(span * 0.018)), joint="curve")
    _finish(base, glow, core, a.cx, a.cy, max(5, span / 30))


def _fx_flames(base, a: Anchor, color, rng, scale: float = 1.0, small: bool = False) -> None:
    span = _span(a, 0.5 if small else 0.85) * scale
    size = int(span * 1.5) + 40
    c = size / 2
    glow, gd = _glow_layer(size)
    core, cd = _glow_layer(size)
    for _ in range(4 if small else 7):
        x = c + rng.uniform(-0.35, 0.35) * span
        h = span * rng.uniform(0.35, 0.6)
        w = h * 0.45
        y = c + span * 0.25
        flame = [(x - w / 2, y), (x, y - h), (x + w / 2, y)]
        gd.polygon(flame, fill=(255, 110, 30, 220))
        cd.polygon([(x - w / 4, y), (x, y - h * 0.65), (x + w / 4, y)], fill=(255, 225, 120, 240))
    _finish(base, glow, core, a.cx, a.cy, max(4, span / 20))


def _fx_heal(base, a: Anchor, rng) -> None:
    span = min(a.w, a.h, 420) * 1.1
    size = int(span * 1.5) + 40
    c = size / 2
    glow, gd = _glow_layer(size)
    core, cd = _glow_layer(size)
    gd.ellipse([c - span * 0.45, c - span * 0.45, c + span * 0.45, c + span * 0.45], fill=(*GREEN, 120))
    for _ in range(4):
        x, y = c + rng.uniform(-0.35, 0.35) * span, c + rng.uniform(-0.4, 0.2) * span
        r = span * rng.uniform(0.07, 0.12)
        t = r * 0.36
        for col, k in (((*GREEN, 230), 1.0), ((235, 255, 235, 255), 0.55)):
            cd.rectangle([x - r * k, y - t * k, x + r * k, y + t * k], fill=col)
            cd.rectangle([x - t * k, y - r * k, x + t * k, y + r * k], fill=col)
    _finish(base, glow, core, a.cx, a.cy, max(6, span / 14))


def _fx_shield(base, a: Anchor) -> None:
    span = max(a.w, a.h) * 0.8
    size = int(span * 1.2) + 40
    c = size / 2
    glow, gd = _glow_layer(size)
    core, cd = _glow_layer(size)
    hexagon = [(c + span * 0.5 * math.cos(math.pi / 3 * i + math.pi / 6),
                c + span * 0.5 * math.sin(math.pi / 3 * i + math.pi / 6)) for i in range(6)]
    gd.polygon(hexagon, outline=(*BLUE, 230), width=int(span * 0.07))
    cd.polygon(hexagon, outline=(220, 240, 255, 240), width=max(2, int(span * 0.02)))
    cd.polygon(hexagon, fill=(*BLUE, 28))
    _finish(base, glow, core, a.cx, a.cy, max(4, span / 24))


def _fx_dodge(base, a: Anchor, rng) -> None:
    span = min(a.w, 420) * 1.1
    size = int(span * 1.3) + 40
    c = size / 2
    glow, gd = _glow_layer(size)
    core, cd = _glow_layer(size)
    for i in range(4):
        y = c + (i - 1.5) * span * 0.14
        x0 = c - span * rng.uniform(0.35, 0.5)
        _streak(gd, c, 0, span * 0.7, span * 0.05, (180, 230, 255, 200), (y - c))
        cd.line([(x0, y), (x0 + span * 0.55, y)], fill=(255, 255, 255, 220), width=max(2, int(span * 0.012)))
    _finish(base, glow, core, a.cx + span * 0.08, a.cy, max(3, span / 40))


def _fx_drops(base, a: Anchor, color, rng) -> None:
    span = min(a.w, a.h, 360) * 0.7
    size = int(span * 1.5) + 40
    c = size / 2
    glow, gd = _glow_layer(size)
    core, cd = _glow_layer(size)
    for _ in range(6):
        x, y = c + rng.uniform(-0.4, 0.4) * span, c + rng.uniform(-0.3, 0.4) * span
        r = span * rng.uniform(0.05, 0.08)
        gd.ellipse([x - r * 1.4, y - r * 1.4, x + r * 1.4, y + r * 1.4], fill=(*color, 160))
        cd.ellipse([x - r, y - r, x + r, y + r], fill=(*_mix(color, WHITE, 0.25), 240))
        cd.polygon([(x - r * 0.7, y - r * 0.4), (x, y - r * 2.2), (x + r * 0.7, y - r * 0.4)],
                   fill=(*_mix(color, WHITE, 0.25), 240))
    _finish(base, glow, core, a.cx, a.cy, max(3, span / 20))


def _fx_stun(base, a: Anchor, freeze: bool, rng) -> None:
    span = min(a.w, 420) * 0.9
    size = int(span * 1.4) + 40
    c = size / 2
    glow, gd = _glow_layer(size)
    core, cd = _glow_layer(size)
    color = (150, 230, 255) if freeze else GOLD
    for i in range(6 if freeze else 5):
        ang = 2 * math.pi * i / (6 if freeze else 5) + rng.uniform(-0.2, 0.2)
        x, y = c + math.cos(ang) * span * 0.42, c + math.sin(ang) * span * 0.16
        if freeze:
            shard = [(x, y - span * 0.14), (x + span * 0.04, y), (x, y + span * 0.06), (x - span * 0.04, y)]
            gd.polygon(shard, fill=(*color, 220))
            cd.polygon(shard, outline=(255, 255, 255, 240))
        else:
            pts = [(x + px, y + py) for px, py in _star_points(0, 5, span * 0.07, span * 0.03, -math.pi / 2)]
            gd.polygon(pts, fill=(*color, 220))
            cd.polygon([(x + px, y + py) for px, py in _star_points(0, 5, span * 0.04, span * 0.017, -math.pi / 2)],
                       fill=(255, 255, 255, 250))
    top = a.y + (a.h * 0.12 if not a.player else 0)
    _finish(base, glow, core, a.cx, top, max(3, span / 30))


# ------------------------------------------------------------- résolution
def _effect(style: str, event: dict, target: Anchor, anchors: dict[str, Anchor]) -> str:
    """Effet dessiné pour un coup : style du moteur, ou celui du monstre."""
    if style in ("melee", ""):
        source = anchors.get(event.get("source", ""))
        return MOB_STYLES.get(source.code, "slash") if source is not None else "slash"
    return _PLAYER_STYLES.get(style, style)


def _color_of(event: dict, target: Anchor, anchors: dict[str, Anchor]) -> tuple[int, int, int]:
    """Teinte de l'effet : l'élément infusé du joueur, sinon celui du monstre
    qui frappe, sinon blanc chaud."""
    element = event.get("element", "")
    if not element:
        source = anchors.get(event.get("source", ""))
        if source is not None and not source.player:
            element = source.element
    return ELEMENT_COLORS.get(element, (255, 236, 200))


def _fx_zone(target: Anchor) -> Anchor:
    """Zone où dessiner l'effet : la cible, ou un carré élargi autour d'un
    avatar (sinon l'effet tiendrait dans 90 px)."""
    if not target.player:
        return target
    span = max(target.w, PLAYER_FX_SPAN)
    return Anchor(int(target.cx - span / 2), int(target.cy - span / 2), span, span,
                  target.max_hp, target.element, target.code, player=True)


def _draw_effect(base, kind: str, event: dict, target: Anchor, anchors, rng) -> None:
    target = _fx_zone(target)
    scale = 0.8 if target.player else 1.0
    if kind in ("hit", "crit"):
        effect = _effect(event.get("style", ""), event, target, anchors)
        color = _color_of(event, target, anchors)
        crit = kind == "crit"
        if crit:   # éclat étoilé derrière tout critique
            _fx_burst(base, target, rng, scale=scale)
        if effect == "double" or (effect == "slash" and crit):
            _fx_slash(base, target, color, rng, crosses=2, scale=scale)
        elif effect == "slash":
            _fx_slash(base, target, color, rng, scale=scale)
        elif effect == "claw":
            _fx_slash(base, target, color, rng, claws=3, scale=scale)
        elif effect == "pierce":
            _fx_pierce(base, target, color, rng, scale=scale)
        elif effect == "bite":
            _fx_bite(base, target, color, rng, scale=scale)
        elif effect == "blunt":
            _fx_blunt(base, target, color, rng, scale=scale)
        elif effect == "magic":
            _fx_magic(base, target, color if event.get("style") != "holy" else GOLD, rng, scale=scale)
        elif effect == "lightning":
            _fx_lightning(base, target, color, rng, scale=scale)
        elif effect == "flame":
            _fx_flames(base, target, color, rng, scale=scale)
        elif effect == "explosion":
            _fx_explosion(base, target, color, rng, scale=scale)
        elif effect == "shockwave":
            _fx_shockwave(base, target, color, rng)
        elif effect == "ultimate":
            _fx_ultimate(base, target, rng, scale=scale)
        elif effect == "spark":
            _fx_blunt(base, target, VIOLET, rng, scale=scale * 0.6, spikes=8)
    elif kind == "heal":
        _fx_heal(base, target, rng)
    elif kind in ("shield", "block"):
        _fx_shield(base, target)
    elif kind == "dodge":
        _fx_dodge(base, target, rng)
    elif kind == "dot":
        style = event.get("style", "")
        if style == "burn":
            _fx_flames(base, target, DOT_COLORS["burn"], rng, scale=scale, small=True)
        else:
            _fx_drops(base, target, DOT_COLORS.get(style, RED), rng)
    elif kind == "stun":
        _fx_stun(base, target, event.get("style") == "freeze", rng)
    elif kind == "execute":
        _fx_slash(base, target, RED, rng, crosses=2, scale=scale * 1.3)
    elif kind in ("recoil", "mirror"):
        _fx_blunt(base, target, VIOLET, rng, scale=scale * 0.5, spikes=8)
    elif kind == "revive":
        _fx_magic(base, target, GOLD, rng, scale=scale * 1.2)
    elif kind == "enrage":
        _fx_flames(base, target, RED, rng, scale=scale)
    elif kind == "charge":
        _fx_charge(base, target, rng)
    elif kind == "phase":
        _fx_phase(base, target, rng)


def _label(event: dict, target: Anchor) -> tuple[str, int, tuple, dict] | None:
    """(texte, taille, couleur, options) du chiffre ou du mot de l'événement."""
    kind, amount = event["kind"], event.get("amount", 0)
    size = number_size(amount, target.max_hp, kind == "crit", target.player)
    small = max(28, int(MIN_SIZE * (PLAYER_SCALE if target.player else 1)))
    if kind in ("hit", "crit"):
        if target.player:
            color = RED
        else:
            element = event.get("element", "")
            color = _mix(WHITE, ELEMENT_COLORS[element], 0.35) if element in ELEMENT_COLORS else WHITE
        if kind == "crit":
            return f"{amount}", size, GOLD, {"gradient": ((255, 245, 140), (255, 90, 40)),
                                             "stroke": (110, 10, 20), "label": "CRITIQUE !",
                                             "label_color": (255, 210, 90)}
        if event.get("style") == "ultimate":
            return f"{amount}", max(size, int(MIN_SIZE * 1.1 * (PLAYER_SCALE if target.player else 1))), \
                ULTIMATE_COLOR, {"stroke": (70, 0, 10), "label": "ULTIME", "label_color": (255, 190, 120)}
        return f"{amount}", size, color, {}
    if kind == "heal":
        return f"+{amount}", size, GREEN, {"stroke": (10, 60, 20)}
    if kind == "shield":
        return f"+{amount}", size, BLUE, {"stroke": (10, 30, 70), "label": "BOUCLIER", "label_color": BLUE}
    if kind == "block":
        return (f"-{amount}" if amount else "BLOQUÉ"), (size if amount else small), BLUE, {"stroke": (10, 30, 70)}
    if kind == "dot":
        return f"-{amount}", max(small, int(size * 0.8)), DOT_COLORS.get(event.get("style", ""), RED), {}
    if kind in ("recoil", "mirror"):
        return f"-{amount}", max(small, int(size * 0.8)), VIOLET, {
            "label": "CONTRECOUP" if kind == "recoil" else "MIROIR", "label_color": VIOLET}
    words = {
        "dodge": ("ESQUIVE", (190, 240, 255)), "immune": ("IMMUNISÉ", GREY), "stun": ("ÉTOURDI", GOLD),
        "ko": ("K.O.", RED), "revive": ("RELEVÉ !", GOLD), "hold": ("TIENT BON !", GOLD),
        "execute": ("EXÉCUTÉ !", RED), "enrage": ("FURIE", (255, 120, 60)),
    }
    if kind == "charge":
        return "CHARGE…", int(MIN_SIZE * 1.1), (255, 150, 90), {
            "stroke": (70, 0, 10), "label": (event.get("style") or "ATTAQUE ULTIME").upper()[:40],
            "label_color": (255, 220, 170)}
    if kind in words:
        text, color = words[kind]
        if kind == "stun" and event.get("style") == "freeze":
            text, color = "GELÉ", (150, 230, 255)
        return text, max(small, int(MIN_SIZE * 0.85 * (PLAYER_SCALE if target.player else 1))), color, {}
    return None


def draw_combat_fx(base, events: list[dict] | None, anchors: dict[str, Anchor],
                   seed: int = 0) -> None:
    """Dessine les effets puis les chiffres des événements de l'action, sur
    leurs cibles. Un événement dont la cible n'est pas à l'image est ignoré."""
    if not events:
        return
    rng = random.Random(seed)
    placed: dict[str, float] = {}
    labels = []
    # Le boss qui déchaîne son ultime s'embrase (une fois par action).
    for source in dict.fromkeys(e.get("source") for e in events if e.get("style") == "ultimate"):
        if source in anchors:
            _fx_phase(base, anchors[source], rng)
    for event in events:
        target = anchors.get(event.get("target", ""))
        if target is None:
            continue
        _draw_effect(base, event["kind"], event, target, anchors, rng)
        label = _label(event, target)
        if label is not None:
            labels.append((event, target, label))
    # Les chiffres par-dessus tous les effets, empilés par cible.
    if isinstance(base, FxCollector):
        base.role = "label"
    for event, target, (text, size, color, opts) in labels:
        key = event["target"]
        stacked = placed.get(key, 0.0)      # hauteur déjà occupée sur cette cible
        layer = _text_layer(text, size, color, **opts)
        placed[key] = stacked + layer.height * 0.82
        if target.player:
            cy = target.y - 14 - layer.height / 2 - stacked
        else:
            cy = target.y + target.h * 0.28 + stacked
        cy = min(BOTTOM_LIMIT - layer.height / 2, max(TOP_LIMIT + layer.height / 2, cy))
        cx = target.cx + rng.uniform(-0.12, 0.12) * min(target.w, 300)
        cx = min(base.width - layer.width / 2 - 8, max(layer.width / 2 + 8, cx))
        angle = rng.uniform(-9, 9) if event["kind"] in ("crit", "execute") else rng.uniform(-5, 5)
        _paste_center(base, layer, cx, cy, angle)
