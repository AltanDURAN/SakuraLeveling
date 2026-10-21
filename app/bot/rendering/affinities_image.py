"""Image de `/affinites` : les 8 éléments du joueur sur une seule planche.

Même grammaire visuelle que la bannière et les PNJ (dégradé nuit, pétales de
sakura, panneaux translucides, badges d'élément). Chaque élément a sa carte :
affinité, progression d'essences vers le palier suivant, talent.

Le talent est CACHÉ tant que la voyante ne l'a pas révélé : la carte
le montre comme un mystère (❓, pointillés), sans jamais trahir le plafond réel.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter

from app.bot.rendering.element_visuals import ELEMENT_COLORS, make_element_badge
from app.bot.rendering.emoji_text import draw_text_with_emojis, measure_text_with_emojis
from app.bot.rendering.pillow_utils import (
    draw_sakura_petals,
    draw_text_with_shadow,
    gradient_background,
    try_font,
)
from app.domain.services.element_service import BEATS
from app.shared.enums import ELEMENT_EMOJIS, ELEMENT_LABELS, Element
from app.shared.formatters import format_int

WIDTH = 1024
_PAD = 28
_GAP = 16
_COLS = 2
_CARD_H = 168
_HEADER_H = 156
_FOOTER_H = 84

_TEXT = (245, 242, 250, 255)
_MUTED = (176, 170, 194, 255)
_DIM = (128, 122, 144, 255)
_GOLD = (240, 196, 92, 255)
_SHADOW = (0, 0, 0, 170)
_DEAD = (112, 108, 124)


@dataclass(frozen=True)
class AffinityCard:
    code: str
    affinity: int
    essences: int
    next_cost: int | None      # None = plafond atteint
    known: bool                # talent révélé par la voyante
    talent: int = 0
    cap: int = 100
    boosts: int = 0

    @property
    def dead(self) -> bool:
        return self.known and self.talent <= 0


def build_affinity_cards(
    affinities: dict[str, int],
    essences: dict[str, int],
    talents: dict,
    revealed: set[str],
) -> list[AffinityCard]:
    """Cartes des 8 éléments. Un talent non révélé ne transmet NI sa valeur NI
    son plafond (le palier suivant, lui, suit le vrai plafond)."""
    from app.domain.services.element_affinity_progression_service import (
        ElementAffinityProgressionService,
    )
    from app.shared.enums import ALL_ELEMENTS

    progression = ElementAffinityProgressionService()
    cards = []
    for element in ALL_ELEMENTS:
        code = element.value
        talent = talents.get(code)
        real_cap = talent.cap if talent is not None else 100
        known = code in revealed and talent is not None
        aff = int(affinities.get(code, 0))
        cards.append(AffinityCard(
            code=code,
            affinity=aff,
            essences=int(essences.get(code, 0)),
            next_cost=progression.cost_for_next_level(aff, cap=real_cap),
            known=known,
            talent=talent.talent if known else 0,
            cap=real_cap if known else 100,
            boosts=talent.boosts if known else 0,
        ))
    return cards


def _lighten(color: tuple[int, int, int], f: float) -> tuple[int, int, int]:
    return tuple(int(c + (255 - c) * f) for c in color)


def _readable(color: tuple[int, int, int]) -> tuple[int, int, int]:
    """Couleur d'élément éclaircie si elle est trop sombre pour du texte."""
    lum = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
    return _lighten(color, 0.45) if lum < 120 else color


def _panel(img, xy, size, radius=16, fill=(28, 24, 40, 205), outline=None, width=1):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        [xy, (xy[0] + size[0], xy[1] + size[1])], radius=radius, fill=fill,
        outline=outline, width=width,
    )
    img.alpha_composite(layer)


def _bar(img, xy, size, ratio, color, track=(60, 54, 78, 220), glow=False):
    x, y = xy
    w, h = size
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([(x, y), (x + w, y + h)], radius=h // 2, fill=track)
    filled = int(w * max(0.0, min(1.0, ratio)))
    if filled > 2:
        if glow:
            g = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(g).rounded_rectangle(
                [(x, y - 2), (x + filled, y + h + 2)], radius=h, fill=(*color, 120),
            )
            img.alpha_composite(g.filter(ImageFilter.GaussianBlur(5)))
        d.rounded_rectangle([(x, y), (x + filled, y + h)], radius=h // 2, fill=(*color, 255))
    img.alpha_composite(layer)


def _dashed_round_rect(draw, box, color, dash=7, gap=6, radius=10):
    """Contour pointillé (mystère) — segments droits + coins pleins."""
    x0, y0, x1, y1 = box
    for x in range(x0 + radius, x1 - radius, dash + gap):
        draw.line([(x, y0), (min(x + dash, x1 - radius), y0)], fill=color, width=2)
        draw.line([(x, y1), (min(x + dash, x1 - radius), y1)], fill=color, width=2)
    for y in range(y0 + radius, y1 - radius, dash + gap):
        draw.line([(x0, y), (x0, min(y + dash, y1 - radius))], fill=color, width=2)
        draw.line([(x1, y), (x1, min(y + dash, y1 - radius))], fill=color, width=2)
    for (cx, cy, start) in ((x0, y0, 180), (x1 - 2 * radius, y0, 270),
                            (x1 - 2 * radius, y1 - 2 * radius, 0), (x0, y1 - 2 * radius, 90)):
        draw.arc([cx, cy, cx + 2 * radius, cy + 2 * radius], start, start + 90, fill=color, width=2)


def _beats_line(code: str) -> str:
    try:
        targets = BEATS.get(Element(code), frozenset())
    except ValueError:
        return ""
    order = [e for e in Element if e in targets]
    return " ".join(ELEMENT_EMOJIS.get(e.value, "") for e in order)


def _draw_card(img: Image.Image, xy: tuple[int, int], size: tuple[int, int],
               card: AffinityCard) -> None:
    x, y = xy
    w, h = size
    color = _DEAD if card.dead else ELEMENT_COLORS.get(card.code, (150, 150, 160))
    text_color = _readable(color)
    draw = ImageDraw.Draw(img)

    # Fond : panneau sombre teinté de la couleur de l'élément, liseré à gauche.
    _panel(img, (x, y), (w, h), radius=16, fill=(24, 20, 36, 215),
           outline=(*color, 90))
    tint = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(tint).rounded_rectangle([(x, y), (x + w, y + h)], radius=16,
                                           fill=(*color, 26))
    img.alpha_composite(tint)
    _panel(img, (x, y + 14), (5, h - 28), radius=3, fill=(*color, 255))

    # Badge
    badge_d = 84
    badge = make_element_badge(card.code, diameter=badge_d)
    bx, by = x + 22, y + 18
    if badge is not None:
        if card.dead:
            badge = badge.convert("LA").convert("RGBA")
            badge.putalpha(badge.getchannel("A").point(lambda a: a * 0.55))
        img.alpha_composite(badge, (bx, by))

    f_name = try_font(26, bold=True)
    f_big = try_font(34, bold=True)
    f_small = try_font(17)
    f_label = try_font(14, bold=True)

    # Nom + relation « bat »
    tx = bx + badge_d + 18
    draw_text_with_shadow(draw, (tx, y + 18), ELEMENT_LABELS.get(card.code, card.code),
                          f_name, fill=(*text_color, 255), shadow=_SHADOW)
    # Talent sous le nom : c'est l'information que le joueur vient chercher.
    _draw_talent(img, (tx, y + 56), card)

    # Valeur d'affinité, à droite
    right = x + w - 20
    if card.dead:
        value = "—"
        sub = ""
    else:
        value = str(card.affinity)
        sub = f"/ {card.cap}" if card.known else "/ ?"
    sub_w = draw.textlength(sub, font=f_small) if sub else 0
    val_w = draw.textlength(value, font=f_big)
    if sub:
        draw_text_with_shadow(draw, (right - sub_w, y + 32), sub, f_small, fill=_DIM, shadow=_SHADOW)
    draw_text_with_shadow(draw, (right - sub_w - 6 - val_w, y + 16), value, f_big,
                          fill=(*text_color, 255), shadow=_SHADOW)

    # « Fort contre » sous la valeur, aligné à droite (⚔️, légendé en en-tête).
    beats = "" if card.dead else _beats_line(card.code)
    if beats:
        line = f"⚔️ {beats}"
        beats_w = measure_text_with_emojis(line, f_small, 20)
        draw_text_with_emojis(img, (int(right - beats_w), y + 58), line, f_small,
                              fill=_MUTED, emoji_size=20)

    # Barres : affinité (vers le plafond) puis essences (vers le palier suivant)
    bar_x, bar_w = x + 22, w - 44
    cap = card.cap if card.known else 100
    if card.dead:
        _panel(img, (bar_x, y + 108), (bar_w, 42), radius=10, fill=(16, 14, 22, 170))
        draw_text_with_emojis(img, (bar_x + 14, y + 119),
                              "Aucune essence · inutilisable en combat",
                              f_small, fill=_DIM, emoji_size=15)
        return

    _bar(img, (bar_x, y + 110), (bar_w, 12), card.affinity / max(cap, 1), color, glow=True)
    if card.known and cap > 100:
        # Repère du plafond normal : montre ce que le don a ajouté.
        mx = bar_x + int(bar_w * 100 / cap)
        draw.line([(mx, y + 105), (mx, y + 126)], fill=(*_GOLD[:3], 230), width=2)
        draw_text_with_shadow(draw, (mx - 13, y + 89), "100", try_font(12, bold=True),
                              fill=(*_GOLD[:3], 230), shadow=_SHADOW)

    f_ess = try_font(14, bold=True)
    ey = y + 136
    draw_text_with_shadow(draw, (bar_x, ey), "ESSENCES", f_ess, fill=_DIM, shadow=_SHADOW)
    if card.next_cost is None:
        right_txt, ratio = "plafond atteint 🏆", 1.0
    else:
        right_txt = f"{card.essences} / {card.next_cost}"
        ratio = card.essences / max(card.next_cost, 1)
    rt_w = measure_text_with_emojis(right_txt, f_small, 17)
    ess_x = bar_x + 92
    _bar(img, (ess_x, ey + 5), (int(bar_w - 92 - rt_w - 14), 7), ratio, _lighten(color, 0.35))
    draw_text_with_emojis(img, (int(bar_x + bar_w - rt_w), ey - 3), right_txt, f_small,
                          fill=_MUTED, emoji_size=17)


def _draw_talent(img: Image.Image, anchor: tuple[int, int], card: AffinityCard) -> None:
    """Pastille de talent, sous le nom de l'élément."""
    draw = ImageDraw.Draw(img)
    left, ty = anchor
    f = try_font(15, bold=True)
    if not card.known:
        label = "❓ TALENT INCONNU"
        w = measure_text_with_emojis(label, f, 15) + 22
        box = (int(left), ty, int(left + w), ty + 28)
        _panel(img, (box[0], box[1]), (box[2] - box[0], 28), radius=13, fill=(46, 36, 70, 200))
        _dashed_round_rect(draw, box, (190, 160, 240, 200), radius=12)
        draw_text_with_emojis(img, (box[0] + 11, ty + 6), label, f, fill=(214, 196, 250, 255),
                              emoji_size=15)
        return
    if card.dead:
        label, fill, ink = "💀 TALENT 0", (60, 56, 70, 220), (190, 186, 200, 255)
    elif card.boosts:
        label, fill, ink = f"✨ DON · TALENT {card.talent}", (92, 70, 20, 230), (*_GOLD[:3], 255)
    else:
        label, fill, ink = f"TALENT {card.talent} · +{card.talent * 10} %", (40, 52, 46, 220), (150, 226, 170, 255)
    w = measure_text_with_emojis(label, f, 15) + 22
    _panel(img, (int(left), ty), (int(w), 28), radius=13, fill=fill)
    draw_text_with_emojis(img, (int(left) + 11, ty + 6), label, f, fill=ink, emoji_size=15)


def compose_affinities_image(
    output_path: str,
    *,
    display_name: str,
    cards: list[AffinityCard],
    is_self: bool,
    next_paper_price: int | None,
    seed: int = 0,
) -> None:
    rows = -(-len(cards) // _COLS)
    height = _HEADER_H + rows * _CARD_H + (rows - 1) * _GAP + _FOOTER_H + _PAD
    bg = gradient_background(WIDTH, height, (26, 22, 40, 255), (16, 14, 26, 255))
    draw_sakura_petals(bg, seed=seed)
    draw = ImageDraw.Draw(bg)

    f_title = try_font(32, bold=True)
    f_sub = try_font(17)
    f_chip = try_font(15, bold=True)

    # ---------------------------------------------------------------- en-tête
    title = "✨ Affinités élémentaires"
    draw_text_with_emojis(bg, (_PAD, _PAD), title, f_title, fill=_TEXT, emoji_size=32)
    who = "Ta maîtrise des huit éléments" if is_self else f"Maîtrise de {display_name}"
    draw_text_with_emojis(bg, (_PAD, _PAD + 46), f"{who}   ·   ⚔️ = fort contre", f_sub,
                          fill=_MUTED, emoji_size=17)

    known = sum(1 for c in cards if c.known)
    chips = [f"🔮 Talents découverts {known}/{len(cards)}"]
    alive = [c for c in cards if not c.dead]
    if alive:
        best = max(alive, key=lambda c: c.affinity)
        if best.affinity > 0:
            chips.append(f"{ELEMENT_EMOJIS.get(best.code, '')} Meilleur : "
                         f"{ELEMENT_LABELS.get(best.code, best.code)} {best.affinity}")
    cx = _PAD
    cy = _PAD + 78
    for chip in chips:
        cw = measure_text_with_emojis(chip, f_chip, 16) + 28
        _panel(bg, (int(cx), cy), (int(cw), 30), radius=15, fill=(40, 32, 60, 220),
               outline=(150, 120, 210, 120))
        draw_text_with_emojis(bg, (int(cx) + 14, cy + 6), chip, f_chip, fill=_TEXT, emoji_size=16)
        cx += cw + 10

    # ------------------------------------------------------------------ cartes
    card_w = (WIDTH - 2 * _PAD - (_COLS - 1) * _GAP) // _COLS
    for i, card in enumerate(cards):
        r, c = divmod(i, _COLS)
        _draw_card(bg, (_PAD + c * (card_w + _GAP), _HEADER_H + r * (_CARD_H + _GAP)),
                   (card_w, _CARD_H), card)

    # ------------------------------------------------------------------ pied
    fy = height - _FOOTER_H - _PAD + 18
    _panel(bg, (_PAD, fy), (WIDTH - 2 * _PAD, _FOOTER_H - 8), radius=16, fill=(36, 28, 54, 215),
           outline=(150, 120, 210, 110))
    f_foot = try_font(16)
    f_foot_b = try_font(17, bold=True)
    if known >= len(cards):
        if is_self:
            line1 = "🔮 Tu connais tous tes talents."
            line2 = "Les essences tombent au rythme de ton talent : farme les éléments qui te sourient."
        else:
            line1 = f"🔮 {display_name} connaît tous ses talents."
            line2 = "Les essences tombent au rythme du talent de chacun."
    elif not is_self:
        line1 = f"🔮 {display_name} a découvert {known} talent(s) sur {len(cards)}."
        line2 = "Chacun découvre les siens auprès d'Ysaline, la voyante (/voyante)."
    else:
        if next_paper_price == 0:
            line1 = "🔮 Ta première lecture chez la voyante est OFFERTE"
        else:
            price = f"{format_int(next_paper_price)} or"
            line1 = f"🔮 La voyante — prochaine lecture : {price}"
        line2 = ("Ysaline lit ton talent caché dans l'élément de ton choix : /voyante, "
                 "ou le bouton ci-dessous.")
    draw_text_with_emojis(bg, (_PAD + 20, fy + 12), line1, f_foot_b, fill=_GOLD, emoji_size=18)
    draw_text_with_shadow(draw, (_PAD + 20, fy + 42), line2, f_foot, fill=_MUTED, shadow=_SHADOW)

    bg.convert("RGB").save(output_path, "PNG", optimize=True)
