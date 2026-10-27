"""Scène de combat rendue en image (décor + monstre + HUD joueurs).

**Cadre fixe 4:5 vertical (1080×1350)** : c'est le format vertical qui
s'affiche le plus large sur PC (Discord plafonne la hauteur des images inline,
donc tous les formats verticaux finissent à la même hauteur — seule la largeur
varie) tout en restant franchement vertical sur mobile.

**Décor découplé du monstre** :
  - `spot` = environnement (background, crop, ground_y) — vient du couple
    (zone, élément) ; partagé par tous les monstres de cet élément dans la zone.
  - `placement` = placement du monstre (scale, offset_x, shadow) — propre au
    monstre ; ses pieds se posent sur `ground_y` du spot.
Sans spot/placement → rendu automatique (décor zoomé + monstre posé au sol).

Le HUD est auto-portant et dessiné PAR-DESSUS le monstre : bandeau haut (badge
d'élément + nom + power + barre de vie), bandeau bas (joueurs : avatar +
mini-barre de vie + nom). Barres mob et joueurs : même règle couleur.
"""

import logging
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.bot.rendering import combat_fx
from app.bot.rendering.element_visuals import make_element_badge, tint_by_element
from app.bot.rendering.image_utils import (
    add_outline,
    crop_to_circle,
    download_image,
    get_hp_color,
    load_background,
)
from app.shared.paths import LANDSCAPES_ASSETS_DIR, MOBS_ASSETS_DIR

_logger = logging.getLogger(__name__)

# --- Cadre fixe 4:5 ---
FRAME_W, FRAME_H = 1080, 1350
FRAME_RATIO = FRAME_H / FRAME_W

# Bandeaux HUD (positions fixes).
TOP_PANEL = (22, 18, FRAME_W - 22, 152)
BOTTOM_PANEL = (22, 1194, FRAME_W - 22, 1332)
# Zone utile pour le monstre (entre les deux bandeaux) — utilisée par le
# placement AUTOMATIQUE et comme repère dans l'éditeur.
STAGE_TOP, STAGE_BOTTOM = 152, 1194

_PANEL_FILL = (12, 10, 16, 165)
_PANEL_BORDER = (255, 255, 255, 32)
_AUTO_DECOR_ZOOM = 1.35   # zoom du décor quand aucune scène n'est composée
_AUTO_MOB_FILL = 0.92     # part de la zone occupée par le monstre en auto

_FONTS = {"title": 46, "stat": 30, "hp": 26, "badge": 96, "av_d": 88}


# --------------------------------------------------------------------------
# Helpers image
# --------------------------------------------------------------------------
def _cover_fit(image: Image.Image, w: int, h: int) -> Image.Image:
    """Redimensionne pour COUVRIR (w, h) en gardant le ratio, puis recadre au
    centre (pas de distorsion)."""
    image = image.convert("RGBA")
    if image.size == (w, h):
        return image
    scale = max(w / image.width, h / image.height)
    nw, nh = max(w, int(image.width * scale)), max(h, int(image.height * scale))
    resized = image.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - w) // 2, (nh - h) // 2
    return resized.crop((left, top, left + w, top + h))


def crop_background(image: Image.Image, crop: dict) -> Image.Image:
    """Applique un cadrage en FRACTIONS sur l'image d'environnement et le
    ramène aux dimensions du cadre. `crop` = {x, y, w} (la hauteur découle du
    ratio du cadre). Partagé avec l'éditeur admin pour un WYSIWYG exact."""
    image = image.convert("RGBA")
    W, H = image.size
    cw = max(0.02, min(1.0, float(crop.get("w", 1.0) or 1.0)))
    px_w = cw * W
    px_h = px_w * FRAME_RATIO
    if px_h > H:  # le cadrage demandé dépasse en hauteur → on borne
        px_h = H
        px_w = px_h / FRAME_RATIO
    x = max(0.0, min(1.0, float(crop.get("x", 0.0) or 0.0))) * W
    y = max(0.0, min(1.0, float(crop.get("y", 0.0) or 0.0))) * H
    x = max(0.0, min(x, W - px_w))
    y = max(0.0, min(y, H - px_h))
    box = (int(round(x)), int(round(y)), int(round(x + px_w)), int(round(y + px_h)))
    return image.crop(box).resize((FRAME_W, FRAME_H), Image.LANCZOS)


def mob_content(raw_mob: Image.Image) -> Image.Image:
    """Recadre le monstre sur ses pixels réels (bbox du non-transparent)."""
    raw_mob = raw_mob.convert("RGBA")
    bbox = raw_mob.getchannel("A").getbbox() or (0, 0, raw_mob.width, raw_mob.height)
    return raw_mob.crop(bbox)


def place_mob(content: Image.Image, placement: dict, ground_y: float) -> tuple[Image.Image, tuple[int, int]]:
    """Place le monstre : `scale` = hauteur du monstre / hauteur du cadre,
    `offset_x` = décalage horizontal (fraction, 0 = centré), `offset_y` =
    décalage vertical (fraction, <0 = plus haut, utile pour un monstre qui
    flotte). Les pieds se posent sur `ground_y` + `offset_y` (fractions)."""
    scale_frac = max(0.05, min(1.5, float(placement.get("scale", 0.62) or 0.62)))
    target_h = max(1, int(round(scale_frac * FRAME_H)))
    ratio = target_h / content.height
    nw = max(1, int(round(content.width * ratio)))
    img = content.resize((nw, target_h), Image.LANCZOS)
    cx = (0.5 + float(placement.get("offset_x", 0.0) or 0.0)) * FRAME_W
    base_y = float(ground_y if ground_y is not None else 0.86)
    fy = max(0.0, min(1.2, base_y + float(placement.get("offset_y", 0.0) or 0.0))) * FRAME_H
    return img, (int(round(cx - nw / 2)), int(round(fy - target_h)))


def _auto_place_mob(content: Image.Image) -> tuple[Image.Image, tuple[int, int]]:
    """Placement automatique (aucune scène composée) : le monstre remplit la
    zone entre les bandeaux, centré, posé au sol."""
    stage_h = (STAGE_BOTTOM - STAGE_TOP) * _AUTO_MOB_FILL
    ratio = min(stage_h / content.height, (FRAME_W * 0.86) / content.width)
    nw, nh = max(1, round(content.width * ratio)), max(1, round(content.height * ratio))
    img = content.resize((nw, nh), Image.LANCZOS)
    return img, ((FRAME_W - nw) // 2, STAGE_BOTTOM - nh)


def draw_contact_shadow(base: Image.Image, pos: tuple[int, int], size: tuple[int, int]) -> None:
    """Ombre de contact douce sous le monstre → il paraît posé DANS le décor."""
    nw, nh = size
    cx = pos[0] + nw / 2
    fy = pos[1] + nh
    rw = max(12.0, nw * 0.42)
    rh = max(7.0, nw * 0.10)
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse(
        [cx - rw, fy - rh, cx + rw, fy + rh], fill=(0, 0, 0, 115),
    )
    layer = layer.filter(ImageFilter.GaussianBlur(radius=max(4, rh * 0.8)))
    base.alpha_composite(layer)


def _panel(base: Image.Image, box, radius: int = 24) -> None:
    x1, y1, x2, y2 = box
    overlay = Image.new("RGBA", (x2 - x1, y2 - y1), (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rounded_rectangle(
        [0, 0, x2 - x1 - 1, y2 - y1 - 1], radius=radius,
        fill=_PANEL_FILL, outline=_PANEL_BORDER, width=2,
    )
    base.alpha_composite(overlay, (x1, y1))


def _draw_ratio_bar(base, draw, x1, y1, x2, y2, current, maximum) -> None:
    """Barre de vie : couleur selon le % de PV (vert plein → rouge), vide à 0%."""
    r = (y2 - y1) // 2
    draw.rounded_rectangle([x1, y1, x2, y2], radius=r,
                           fill=(22, 18, 26, 235), outline=(255, 255, 255, 55), width=2)
    ratio = max(0.0, min(1.0, current / maximum)) if maximum > 0 else 0.0
    fill_w = int((x2 - x1 - 6) * ratio)
    if fill_w > 6:
        color = get_hp_color(current, maximum)
        fill = Image.new("RGBA", (fill_w, y2 - y1 - 6), (color[0], color[1], color[2], 255))
        mask = Image.new("L", fill.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, fill_w - 1, fill.size[1] - 1], radius=(y2 - y1 - 6) // 2, fill=255)
        fill.putalpha(mask)
        base.alpha_composite(fill, (x1 + 3, y1 + 3))


def has_mob_image(image_name: str | None) -> bool:
    return bool(image_name) and (MOBS_ASSETS_DIR / image_name).exists()


def _load_mob_image(image_name: str | None) -> Image.Image:
    if image_name:
        try:
            return Image.open(MOBS_ASSETS_DIR / image_name).convert("RGBA")
        except Exception as e:
            _logger.warning("Chargement image mob %s échoué : %s", image_name, e)
    return Image.new("RGBA", (600, 600), (120, 120, 120, 255))


@dataclass
class _Sprite:
    """Un monstre posé dans la scène (teinté par son élément) ; `dim` : sa
    version vaincue (assombrie), calculée au besoin."""
    key: str
    img: Image.Image
    pos: tuple[int, int]
    dim: Image.Image | None = None

    def dimmed(self) -> Image.Image:
        if self.dim is None:
            alpha = self.img.getchannel("A").point(lambda a: a * 45 // 100)
            self.dim = Image.merge("RGBA", (*self.img.convert("RGB").point(lambda v: v // 3).split(), alpha))
        return self.dim


@dataclass
class _Bar:
    """Une barre de PV du HUD (position, police du texte, texte affiché ou
    non, barre de bouclier au-dessus pour le monstre seul)."""
    box: tuple[int, int, int, int]
    font: ImageFont.ImageFont | None = None
    shield_box: tuple[int, int, int, int] | None = None
    #: Repères sur la barre (fractions des PV) : les phases d'un boss.
    ticks: tuple[float, ...] = ()


@dataclass
class Scene:
    """Une scène de combat découpée en couches : `bg` (décor + ombres), les
    monstres (`sprites`, dans l'ordre de dessin), `overlay` (bandeaux, noms,
    badges, avatars) — figés — puis les barres de PV et les effets, redessinés
    à chaque image. Le rendu fixe est mis en cache par ensemble de vaincus :
    une animation ne recompose le décor qu'à la chute d'un monstre."""
    bg: Image.Image
    sprites: list[_Sprite]
    overlay: Image.Image
    enemy_bars: dict[str, _Bar]
    player_bars: dict[str, _Bar]
    anchors: dict[str, combat_fx.Anchor]
    dim_dead: bool = True
    _cache: dict = field(default_factory=dict)

    def static(self, dead: frozenset = frozenset()) -> Image.Image:
        key = dead if self.dim_dead else frozenset()
        if key not in self._cache:
            img = self.bg.copy()
            for sprite in self.sprites:
                img.alpha_composite(sprite.dimmed() if sprite.key in key else sprite.img, sprite.pos)
            img.alpha_composite(self.overlay)
            self._cache[key] = img
        return self._cache[key]

    def draw_bars(self, img: Image.Image, enemies: dict[str, tuple], players: dict[str, tuple]) -> None:
        """`enemies` : {clé: (PV, PV max, bouclier)} ; `players` : {clé: (PV, PV max)}."""
        draw = ImageDraw.Draw(img)
        for key, bar in self.enemy_bars.items():
            cur, mx, shield = enemies.get(key, (0, 1, 0))
            cur, mx, shield = max(0, int(round(cur))), int(round(mx)), int(round(shield))
            x1, y1, x2, y2 = bar.box
            _draw_ratio_bar(img, draw, x1, y1, x2, y2, cur, mx)
            for tick in bar.ticks:
                tx = int(x1 + (x2 - x1) * tick)
                draw.line([(tx, y1 - 5), (tx, y2 + 5)], fill=(24, 10, 18, 255), width=6)
                draw.line([(tx, y1 - 4), (tx, y2 + 4)], fill=(255, 236, 200, 255), width=2)
            if bar.font is not None:
                hp_txt = f"{cur} / {mx}" if cur > 0 else "Vaincu"
                draw.text(((x1 + x2) / 2 - draw.textlength(hp_txt, font=bar.font) / 2,
                           (y1 + y2) / 2 - bar.font.size / 2 - 1), hp_txt, font=bar.font,
                          fill=(255, 255, 255, 255))
            if bar.shield_box is not None and shield > 0 and mx > 0:
                sx1, sy1, sx2, sy2 = bar.shield_box
                draw.rounded_rectangle([sx1, sy1, sx2, sy2], radius=5, fill=(18, 22, 40, 190))
                fill_w = int((sx2 - sx1) * max(0.0, min(1.0, shield / mx)))
                if fill_w > 4:
                    draw.rounded_rectangle([sx1, sy1, sx1 + fill_w, sy2], radius=5, fill=(74, 150, 255, 240))
                draw.text((sx1 + 6, sy1 - 1), f"Bouclier {int(shield)}", font=bar.font,
                          fill=(190, 218, 255, 255))
        for key, bar in self.player_bars.items():
            cur, mx = players.get(key, (0, 1))
            _draw_ratio_bar(img, draw, *bar.box, max(0, int(round(cur))), int(round(mx)))

    def render(self, enemies: dict[str, tuple], players: dict[str, tuple],
               dead: frozenset = frozenset(), events: list[dict] | None = None,
               fx_seed: int = 0) -> Image.Image:
        """Une image complète (RGBA) : décor figé, barres, effets."""
        img = self.static(dead).copy()
        self.draw_bars(img, enemies, players)
        combat_fx.draw_combat_fx(img, events, self.anchors, seed=fx_seed)
        return img


def _player_key(player: dict, index: int) -> str:
    return f"p{player['player_id']}" if player.get("player_id") is not None else f"slot{index}"


def build_scene(
    *,
    mob: dict | None,
    players: list[dict] | None = None,
    background_path: str | None = None,
    spot: dict | None = None,
    placement: dict | None = None,
    mobs: list[dict] | None = None,
    placements: list[dict | None] | None = None,
    formation: list[dict] | None = None,
    boss_index: int | None = None,
    phase_ticks: tuple[float, ...] = (),
) -> Scene:
    """Prépare la scène (cf. `Scene`) : décor du spot, monstre(s), bandeaux.
    Les PV des monstres et des joueurs ne servent qu'au rendu des barres.
    `boss_index` : le boss d'un groupe (world boss et ses gardes) — le
    bandeau du haut est à lui seul, une barre géante marquée de ses phases
    (`phase_ticks`), et ses gardes ont une barre au-dessus de la tête."""
    players = players or []
    group = list(mobs or [])
    if len(group) > 1:
        mob = None

    # ---- Décor (vient du spot) ----
    bg_path = background_path
    if spot and spot.get("background"):
        bg_path = str(LANDSCAPES_ASSETS_DIR / spot["background"])
    raw_bg = load_background(bg_path, size=(FRAME_W, FRAME_H))
    if spot and spot.get("crop"):
        bg = crop_background(raw_bg, spot["crop"])
    else:
        zoomed = raw_bg
        if _AUTO_DECOR_ZOOM > 1.0:
            cw = int(raw_bg.width / _AUTO_DECOR_ZOOM)
            ch = int(raw_bg.height / _AUTO_DECOR_ZOOM)
            zoomed = raw_bg.crop(((raw_bg.width - cw) // 2, (raw_bg.height - ch) // 2,
                                  (raw_bg.width - cw) // 2 + cw, (raw_bg.height - ch) // 2 + ch))
        bg = _cover_fit(zoomed, FRAME_W, FRAME_H)
    bg = bg.convert("RGBA")

    try:
        title_font = ImageFont.truetype("DejaVuSans-Bold.ttf", _FONTS["title"])
        stat_font = ImageFont.truetype("DejaVuSans-Bold.ttf", _FONTS["stat"])
        hp_font = ImageFont.truetype("DejaVuSans-Bold.ttf", _FONTS["hp"])
    except Exception:
        title_font = stat_font = hp_font = ImageFont.load_default()

    anchors: dict[str, combat_fx.Anchor] = {}
    sprites: list[_Sprite] = []
    enemy_bars: dict[str, _Bar] = {}
    player_bars: dict[str, _Bar] = {}

    # ---- Monstre (le HUD passera par-dessus) ----
    if mob is not None:
        content = mob_content(_load_mob_image(mob.get("image_name")))
        if placement:
            ground_y = (spot or {}).get("ground_y", 0.86)
            mob_img, mob_pos = place_mob(content, placement, ground_y)
            shadow = placement.get("shadow", True)
        else:
            mob_img, mob_pos = _auto_place_mob(content)
            shadow = True
        if shadow:
            draw_contact_shadow(bg, mob_pos, mob_img.size)
        element = mob.get("element") or ""
        if element:
            mob_img = tint_by_element(mob_img, element)
        sprites.append(_Sprite("e0", mob_img, mob_pos))
        anchors["e0"] = combat_fx.Anchor(
            mob_pos[0], max(STAGE_TOP, mob_pos[1]), mob_img.width,
            min(mob_img.height, STAGE_BOTTOM - max(STAGE_TOP, mob_pos[1])),
            int(mob.get("max_hp", 1) or 1), element, mob.get("code", ""))

    boxes: dict[int, tuple[int, int, int, int]] = {}
    if len(group) > 1:
        group_sprites, boxes = _place_group(bg, group, placements or [None] * len(group),
                                            formation or [{"x": 0, "y": 0, "scale": 1}] * len(group), spot)
        sprites.extend(group_sprites)
        for i, data in enumerate(group):
            x, y, w, h = boxes[i]
            anchors[f"e{i}"] = combat_fx.Anchor(x, y, w, h, int(data.get("max_hp", 1) or 1),
                                                data.get("element") or "", data.get("code", ""))

    # ---- Bandeaux et textes figés (calque au-dessus des monstres) ----
    overlay = Image.new("RGBA", (FRAME_W, FRAME_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    _panel(overlay, TOP_PANEL)
    if len(group) > 1 and boss_index is not None:
        enemy_bars.update(_boss_hud(overlay, draw, group, boss_index, boxes, title_font, stat_font,
                                    hp_font, phase_ticks))
    elif len(group) > 1:
        enemy_bars.update(_group_hud(overlay, draw, group))
    if mob is not None:
        pl, pt, pr, pb = TOP_PANEL
        badge_d = _FONTS["badge"]
        name_x = pl + 30
        element = mob.get("element") or ""
        if element:
            badge = make_element_badge(element, diameter=badge_d)
            if badge is not None:
                overlay.alpha_composite(badge, (pl + 18, pt + (pb - pt - badge_d) // 2))
                name_x = pl + 18 + badge_d + 18
        draw.text((name_x, pt + 12), mob.get("name", "Monstre"), font=title_font,
                  fill=(255, 255, 255, 255))
        power = mob.get("power_score", "")
        if power:
            ptxt = f"[ {power} ]"
            draw.text((pr - 16 - draw.textlength(ptxt, font=stat_font), pt + 20),
                      ptxt, font=stat_font, fill=(235, 226, 236, 255))
        bar_y2, bar_y1 = pb - 14, pb - 50
        # Barre de BOUCLIER (bleu) par-dessus les PV — s'épuise avant les PV.
        enemy_bars["e0"] = _Bar((name_x, bar_y1, pr - 16, bar_y2), hp_font,
                                shield_box=(name_x, bar_y1 - 13, pr - 16, bar_y1 - 3),
                                ticks=tuple(phase_ticks))

    # ---- Bandeau JOUEURS (bas) ----
    _panel(overlay, BOTTOM_PANEL)
    if players:
        bl, bt, br, bb = BOTTOM_PANEL
        count = len(players)
        slot_x1, slot_x2 = bl + 24, br - 24
        step = (slot_x2 - slot_x1) / max(1, count)
        av_d = max(44, min(_FONTS["av_d"], int(step) - 8))
        bar_half = int(av_d * 0.58)
        av_y = bt + 8
        for i, player in enumerate(players):
            cx = int(slot_x1 + step * (i + 0.5))
            try:
                raw_avatar = download_image(player["avatar_url"])
            except Exception:
                raw_avatar = Image.new("RGBA", (av_d, av_d), (120, 120, 120, 255))
            mx = int(player.get("max_hp", 1) or 1)
            avatar = add_outline(crop_to_circle(raw_avatar, av_d), outline_size=3)
            overlay.alpha_composite(avatar, (cx - avatar.width // 2, av_y))
            key = _player_key(player, i)
            if player.get("player_id") is not None:
                anchors[key] = combat_fx.Anchor(
                    cx - avatar.width // 2, av_y, avatar.width, avatar.height, mx, player=True)
            bar_y = av_y + avatar.height + 2
            player_bars[key] = _Bar((cx - bar_half, bar_y, cx + bar_half, bar_y + 16))
            name = player.get("name", "")
            # Un raid à 10+ joueurs : le nom tient dans sa colonne ou disparaît.
            while len(name) > 3 and draw.textlength(name, font=hp_font) > step - 6:
                name = name[:-2] + "…"
            if name and draw.textlength(name, font=hp_font) <= step - 6:
                draw.text((cx - draw.textlength(name, font=hp_font) / 2, bar_y + 18),
                          name, font=hp_font, fill=(240, 240, 245, 255))

    return Scene(bg, sprites, overlay, enemy_bars, player_bars, anchors, dim_dead=len(group) > 1)


def scene_values(mob: dict | None, mobs: list[dict] | None,
                 players: list[dict] | None) -> tuple[dict, dict, frozenset]:
    """(PV des monstres, PV des joueurs, vaincus) tirés des données de la scène."""
    group = list(mobs or [])
    enemy_list = group if len(group) > 1 else ([mob] if mob is not None else [])
    enemies = {f"e{i}": (int(m.get("current_hp", 0) or 0), int(m.get("max_hp", 0) or 0),
                         int(m.get("shield", 0) or 0)) for i, m in enumerate(enemy_list)}
    dead = frozenset(k for k, (cur, _, _) in enemies.items() if cur <= 0)
    pl = {_player_key(p, i): (int(p.get("current_hp", 0) or 0), int(p.get("max_hp", 1) or 1))
          for i, p in enumerate(players or [])}
    return enemies, pl, dead


def render_scene(
    *,
    mob: dict | None,
    players: list[dict] | None = None,
    background_path: str | None = None,
    spot: dict | None = None,
    placement: dict | None = None,
    mobs: list[dict] | None = None,
    placements: list[dict | None] | None = None,
    formation: list[dict] | None = None,
    events: list[dict] | None = None,
    fx_seed: int = 0,
) -> Image.Image:
    """Compose la scène complète et renvoie l'image (RGB). Utilisé par le bot
    ET par l'aperçu de l'éditeur admin → WYSIWYG garanti.

    `spot` = environnement (background, crop, ground_y). `placement` = placement
    du monstre (scale, offset_x, shadow). Sans eux → rendu automatique.
    Plusieurs monstres (meute, tour) : `mobs` (ordre de la formation),
    `placements` (le placement propre de chacun pour son élément, ou None) et
    `formation` (un emplacement {x, y, scale} par monstre). `events` :
    ce qui s'est passé pendant l'action (chiffres de dégâts, soins, effets —
    cf. `combat_fx`), dessiné par-dessus tout. Une animation passe plutôt par
    `build_scene` (décor préparé une fois) — cf. `fight_animation`."""
    scene = build_scene(mob=mob, players=players, background_path=background_path, spot=spot,
                        placement=placement, mobs=mobs, placements=placements, formation=formation)
    enemies, pl, dead = scene_values(mob, mobs, players)
    result = scene.render(enemies, pl, dead, events, fx_seed)
    # Léger renforcement de netteté (compense la vignette WebP de l'aperçu).
    return result.convert("RGB").filter(
        ImageFilter.UnsharpMask(radius=2, percent=95, threshold=2)
    )


#: Taille automatique d'un monstre de groupe sans placement propre (fraction
#: de la hauteur du cadre, avant le multiplicateur de son emplacement).
_GROUP_AUTO_SCALE = 0.50


def _place_group(bg: Image.Image, mobs: list[dict], placements: list[dict | None],
                 formation: list[dict], spot: dict | None
                 ) -> tuple[list[_Sprite], dict[int, tuple[int, int, int, int]]]:
    """Plusieurs monstres posés au sol selon la formation : les plus LOIN
    (y le plus petit) d'abord, pour que ceux de devant passent par-dessus
    (ordre des `sprites`). Les ombres sont dessinées dans le décor. Renvoie
    aussi la boîte (x, y, l, h) de chacun (celle de son emplacement s'il n'a
    pas encore d'image) — pour y poser les chiffres de combat."""
    ground_y = (spot or {}).get("ground_y", STAGE_BOTTOM / FRAME_H)
    order = sorted(range(len(mobs)), key=lambda i: formation[i]["y"] if i < len(formation) else 0)
    boxes: dict[int, tuple[int, int, int, int]] = {}
    sprites: list[_Sprite] = []
    for i in order:
        data = mobs[i]
        slot = formation[i] if i < len(formation) else {"x": 0, "y": 0, "scale": 1}
        if not has_mob_image(data.get("image_name")):
            # Pas encore d'image : le bandeau du haut le nomme quand même.
            h = int(FRAME_H * _GROUP_AUTO_SCALE * float(slot.get("scale", 1)))
            w = int(h * 0.7)
            cx = (0.5 + float(slot.get("x", 0))) * FRAME_W
            feet = (ground_y + float(slot.get("y", 0))) * FRAME_H
            boxes[i] = (int(cx - w / 2), int(max(STAGE_TOP, feet - h)), w, int(min(h, feet - STAGE_TOP)))
            continue
        own = placements[i] if i < len(placements) and placements[i] else {}
        content = mob_content(_load_mob_image(data.get("image_name")))
        placement = {
            "scale": float(own.get("scale", _GROUP_AUTO_SCALE)) * float(slot.get("scale", 1)),
            "offset_x": float(slot.get("x", 0)),
            "offset_y": float(own.get("offset_y", 0)) + float(slot.get("y", 0)),
        }
        img, pos = place_mob(content, placement, ground_y)
        if own.get("shadow", True):
            draw_contact_shadow(bg, pos, img.size)
        element = data.get("element") or ""
        if element:
            img = tint_by_element(img, element)
        sprites.append(_Sprite(f"e{i}", img, pos))
        top = max(STAGE_TOP, pos[1])
        boxes[i] = (pos[0], top, img.width, max(1, min(img.height, STAGE_BOTTOM - top)))
    return sprites, boxes


def _group_hud(base: Image.Image, draw: ImageDraw.ImageDraw, mobs: list[dict]) -> dict[str, _Bar]:
    """Bandeau du haut d'un groupe : par monstre, pastille d'élément et nom
    (figés) ; renvoie la place de chaque barre de PV — une colonne chacun
    jusqu'à 3, une grille 2 × 2 à 4."""
    two_rows = len(mobs) > 3
    try:
        name_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 20 if two_rows else 24)
        hp_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 15 if two_rows else 17)
    except Exception:
        name_font = hp_font = ImageFont.load_default()
    pl, pt, pr, pb = TOP_PANEL
    cols = 2 if two_rows else len(mobs)
    rows = 2 if two_rows else 1
    col_w = (pr - pl - 24) / cols
    row_h = (pb - pt - 16) / rows
    badge_d = 34 if two_rows else 48
    bar_h = 18 if two_rows else 26
    bars: dict[str, _Bar] = {}
    for i, data in enumerate(mobs[:4]):
        col, row = i % cols, i // cols
        x1 = int(pl + 12 + col * col_w) + 6
        x2 = int(pl + 12 + (col + 1) * col_w) - 8
        top = int(pt + 8 + row * row_h)
        y_mid = int(top + row_h / 2)
        x = x1
        element = data.get("element") or ""
        badge = make_element_badge(element, diameter=badge_d) if element else None
        if badge is not None:
            base.alpha_composite(badge, (x, y_mid - badge_d // 2))
            x += badge_d + 8
        name = str(data.get("name", "Monstre"))
        while len(name) > 3 and draw.textlength(name, font=name_font) > x2 - x:
            name = name[:-2] + "…"
        name_h = name_font.size + 4
        block = name_h + bar_h
        y0 = y_mid - block // 2
        draw.text((x, y0 - 2), name, font=name_font, fill=(255, 255, 255, 255))
        bars[f"e{i}"] = _Bar((x, y0 + name_h, x2, y0 + name_h + bar_h), hp_font)
    return bars


def _boss_hud(base: Image.Image, draw: ImageDraw.ImageDraw, mobs: list[dict], boss_index: int,
              boxes: dict[int, tuple[int, int, int, int]], title_font, stat_font, hp_font,
              ticks: tuple[float, ...]) -> dict[str, _Bar]:
    """Bandeau du haut d'un world boss : pastille, nom, barre géante marquée
    de ses phases ; une petite barre flottante au-dessus de chaque garde."""
    pl, pt, pr, pb = TOP_PANEL
    boss = mobs[boss_index]
    badge_d = _FONTS["badge"]
    name_x = pl + 30
    element = boss.get("element") or ""
    badge = make_element_badge(element, diameter=badge_d) if element else None
    if badge is not None:
        base.alpha_composite(badge, (pl + 18, pt + (pb - pt - badge_d) // 2))
        name_x = pl + 18 + badge_d + 18
    draw.text((name_x, pt + 12), str(boss.get("name", "Boss")), font=title_font, fill=(255, 226, 150, 255))
    guards = len(mobs) - 1
    if guards:
        tag = f"{guards} garde{'s' if guards > 1 else ''}"
        draw.text((pr - 16 - draw.textlength(tag, font=stat_font), pt + 20), tag, font=stat_font,
                  fill=(235, 226, 236, 255))
    bars = {f"e{boss_index}": _Bar((name_x, pb - 50, pr - 16, pb - 14), hp_font, ticks=tuple(ticks))}
    for i, data in enumerate(mobs):
        if i == boss_index or i not in boxes:
            continue
        x, y, w, h = boxes[i]
        half = max(60, min(130, w // 3))
        cx = x + w // 2
        top = max(STAGE_TOP + 10, y - 30)
        bars[f"e{i}"] = _Bar((cx - half, top, cx + half, top + 18))
    return bars


def compose_players_banner(
    players: list[dict],
    output_path: str = "result.png",
    background_path: str | None = None,
    mob: dict | None = None,
    players_power_score: str = "",
    spot: dict | None = None,
    placement: dict | None = None,
    mobs: list[dict] | None = None,
    placements: list[dict | None] | None = None,
    formation: list[dict] | None = None,
    events: list[dict] | None = None,
    fx_seed: int = 0,
):
    """Point d'entrée du bot. `spot` (environnement du couple zone×élément) et
    `placement` (placement du monstre) sont résolus par l'appelant (encounter).
    Sans eux → rendu automatique (fallback). Meute : `mobs`, `placements`,
    `formation` (cf. `render_scene`)."""
    image = render_scene(
        mob=mob, players=players, background_path=background_path,
        spot=spot, placement=placement, mobs=mobs, placements=placements,
        formation=formation, events=events, fx_seed=fx_seed,
    )
    image.save(output_path)
    _logger.debug("Scène de combat générée : %s", output_path)
