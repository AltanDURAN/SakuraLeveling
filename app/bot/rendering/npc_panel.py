"""Panneau visuel d'un PNJ (forgeron, artisane, marchand).

Deux moitiés : le portrait à gauche, la fiche de travail à droite. Quand aucun
objet n'est sélectionné, la fiche laisse la place à la réplique du personnage
et à sa jauge de maîtrise — le joueur voit d'abord QUI il a en face de lui.

Le portrait est une illustration carrée : on la cadre dans une vignette à
bords adoucis plutôt que de la détourer, ce qui laisse le décor de l'atelier
(braises de la forge, établi) participer à l'ambiance.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from app.bot.rendering.emoji_text import draw_text_with_emojis
from app.bot.rendering.pillow_utils import (
    draw_sakura_petals,
    draw_text_with_shadow,
    gradient_background,
    try_font,
)
from app.shared.enums import STAT_EMOJIS
from app.shared.paths import GENERATED_NPCS_DIR, ITEMS_ASSETS_DIR, NPCS_ASSETS_DIR

WIDTH = 1024
HEIGHT = 520

_TEXT = (245, 242, 250, 255)
_MUTED = (170, 164, 186, 255)
_DIM = (128, 122, 144, 255)
_GOLD = (240, 196, 92, 255)
_OK = (108, 206, 138, 255)
_BAD = (226, 106, 118, 255)
_SHADOW = (0, 0, 0, 170)

_PORTRAIT = 300
_PAD = 26


def _panel(img: Image.Image, xy: tuple[int, int], size: tuple[int, int],
           radius: int = 16, fill=(28, 24, 40, 200)) -> None:
    """Rectangle arrondi semi-transparent. Doit passer par une COUCHE : dessiner
    directement sur l'image aplatit l'alpha et rend le fond opaque."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        [xy, (xy[0] + size[0], xy[1] + size[1])], radius=radius, fill=fill,
    )
    img.alpha_composite(layer)


def _rounded_portrait(path: Path, size: int, radius: int = 20) -> Image.Image:
    src = Image.open(path).convert("RGBA")
    # Les illustrations générées gardent une marge claire sur les bords : on
    # rogne 6 % de chaque côté, sinon elle ressort en angles blancs dans la
    # vignette arrondie.
    w, h = src.size
    inset = int(min(w, h) * 0.06)
    src = src.crop((inset, inset, w - inset, h - inset))
    # Recadrage carré centré sur le haut (le visage), puis mise à l'échelle.
    w, h = src.size
    side = min(w, h)
    left = (w - side) // 2
    src = src.crop((left, 0, left + side, side)).resize(
        (size, size), Image.LANCZOS,
    )
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([(0, 0), (size, size)], radius=radius, fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(src, (0, 0), mask)
    return out


def _bar(img: Image.Image, xy: tuple[int, int], size: tuple[int, int],
         ratio: float, color: tuple[int, int, int]) -> None:
    x, y = xy
    w, h = size
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([(x, y), (x + w, y + h)], radius=h // 2, fill=(60, 54, 78, 220))
    filled = int(w * max(0.0, min(1.0, ratio)))
    if filled > 2:
        d.rounded_rectangle(
            [(x, y), (x + filled, y + h)], radius=h // 2, fill=(*color, 255),
        )
    img.alpha_composite(layer)


def _fit(draw, text: str, font, max_w: int) -> str:
    """Tronque à la LARGEUR réelle (pas au nombre de caractères)."""
    if draw.textlength(text, font=font) <= max_w:
        return text
    ell = "…"
    while text and draw.textlength(text + ell, font=font) > max_w:
        text = text[:-1]
    return text + ell


def _wrap(draw, text: str, font, max_w: int, max_lines: int = 3) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines and words:
        lines[-1] = _fit(draw, lines[-1], font, max_w)
    return lines


def _format_duration(seconds: int) -> str:
    if seconds <= 0:
        return "immédiat"
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes:02d}"
    if minutes:
        return f"{minutes} min" if not sec else f"{minutes} min {sec:02d}"
    return f"{sec} s"


def compose_npc_panel(
    output_path: str,
    *,
    npc_name: str,
    npc_title: str,
    image_name: str,
    accent: tuple[int, int, int],
    greeting: str,
    # Maîtrise (artisans uniquement ; None pour le marchand)
    tier_name: str | None = None,
    tier_level: int = 0,
    tier_total: int = 4,
    tier_progress: float = 1.0,
    orders_completed: int = 0,
    orders_to_next: int = 0,
    # Fiche du travail sélectionné (None = écran d'accueil)
    selection: dict | None = None,
    #: Lignes « ce qu'il sait faire » de l'accueil : (label, valeur).
    info_rows: list[tuple[str, str]] | None = None,
    #: Commande en cours : {item_name, progress, ready_label, ready}
    active_order: dict | None = None,
    seed: int = 0,
) -> None:
    bg = gradient_background(
        WIDTH, HEIGHT, (26, 22, 40, 255), (16, 14, 26, 255),
    )
    draw_sakura_petals(bg, seed=seed)
    draw = ImageDraw.Draw(bg)

    f_name = try_font(34, bold=True)
    f_title = try_font(19, bold=True)
    f_body = try_font(19)
    f_small = try_font(16)
    f_label = try_font(15, bold=True)

    # ---------------------------------------------------------- portrait --
    px, py = _PAD, _PAD
    portrait_path = NPCS_ASSETS_DIR / image_name if image_name else None
    if portrait_path and portrait_path.exists():
        portrait = _rounded_portrait(portrait_path, _PORTRAIT)
        # Halo d'accent derrière la vignette : ancre le personnage sans
        # l'entourer d'un cadre dur.
        halo = Image.new("RGBA", bg.size, (0, 0, 0, 0))
        ImageDraw.Draw(halo).rounded_rectangle(
            [(px - 6, py - 6), (px + _PORTRAIT + 6, py + _PORTRAIT + 6)],
            radius=26, fill=(*accent, 70),
        )
        bg.alpha_composite(halo.filter(ImageFilter.GaussianBlur(9)))
        bg.alpha_composite(portrait, (px, py))
    else:
        _panel(bg, (px, py), (_PORTRAIT, _PORTRAIT), radius=20)
        draw_text_with_shadow(
            draw, (px + 110, py + _PORTRAIT // 2 - 12), "PNJ", f_title, fill=_DIM, shadow=_SHADOW,)

    # Nom + fonction sous le portrait
    name_y = py + _PORTRAIT + 14
    draw_text_with_shadow(draw, (px, name_y), npc_name, f_name, fill=_TEXT, shadow=_SHADOW)
    draw_text_with_shadow(
        draw, (px, name_y + 42), npc_title.upper(), f_label, fill=(*accent, 255), shadow=_SHADOW,)

    # Jauge de maîtrise (artisans seulement)
    if tier_name:
        my = name_y + 70
        label = f"{tier_name}  ·  {tier_level}/{tier_total}"
        draw_text_with_shadow(draw, (px, my), label, f_small, fill=_MUTED, shadow=_SHADOW)
        _bar(bg, (px, my + 26), (_PORTRAIT, 8), tier_progress, accent)
        hint = (
            f"{orders_to_next} commande(s) avant le palier suivant"
            if orders_to_next
            else "maîtrise maximale atteinte"
        )
        draw_text_with_shadow(draw, (px, my + 42), hint, f_small, fill=_DIM, shadow=_SHADOW)

    # ------------------------------------------------------------- fiche --
    cx = px + _PORTRAIT + 28
    cw = WIDTH - cx - _PAD

    if selection is None:
        _panel(bg, (cx, py), (cw, HEIGHT - 2 * _PAD), radius=18)
        ty = py + 26
        for line in _wrap(draw, f"\u00ab {greeting} \u00bb", f_body, cw - 48, max_lines=3):
            draw_text_with_shadow(
                draw, (cx + 24, ty), line, f_body, fill=_TEXT, shadow=_SHADOW,
            )
            ty += 29
        ty += 12

        # Tableau « ce qu'il sait faire » : évite l'écran vide et répond aux
        # questions que le joueur se pose avant d'ouvrir les menus.
        # Colonne des valeurs calculée sur le libellé le plus LARGE : en dur,
        # un libellé un peu long chevauchait sa propre valeur.
        rows = info_rows or []
        label_w = max(
            (draw.textlength(lbl.upper(), font=f_label) for lbl, _ in rows),
            default=0,
        )
        value_x = cx + 24 + int(label_w) + 22
        for label, value in rows:
            draw_text_with_shadow(
                draw, (cx + 24, ty), label.upper(), f_label, fill=_DIM,
                shadow=_SHADOW,
            )
            draw_text_with_emojis(
                bg, (value_x, ty - 2),
                _fit(draw, value, f_small, WIDTH - _PAD - 24 - value_x),
                f_small, fill=_TEXT, emoji_size=16,
            )
            ty += 28

        # Commande en cours : la ramener sous les yeux du joueur, sinon il
        # relance une forge et se fait refuser sans comprendre pourquoi.
        if active_order:
            oy = py + (HEIGHT - 2 * _PAD) - 96
            _panel(bg, (cx + 14, oy), (cw - 28, 82), radius=12,
                   fill=(18, 15, 28, 200))
            ready = active_order.get("ready", False)
            head = "\u2705 Pr\u00eat \u00e0 r\u00e9cup\u00e9rer" if ready else "\u23f3 Travail en cours"
            draw_text_with_emojis(
                bg, (cx + 32, oy + 12), head, f_label,
                fill=_OK if ready else _GOLD, emoji_size=16,
            )
            draw_text_with_shadow(
                draw, (cx + 32, oy + 34),
                _fit(draw, active_order.get("item_name", ""), f_small, cw - 80),
                f_small, fill=_TEXT, shadow=_SHADOW,
            )
            _bar(bg, (cx + 32, oy + 62), (cw - 200, 8),
                 active_order.get("progress", 0.0), accent)
            label = active_order.get("ready_label", "")
            if label:
                draw_text_with_shadow(
                    draw, (cx + cw - 156, oy + 56), label, f_small,
                    fill=_MUTED, shadow=_SHADOW,
                )

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        bg.convert("RGB").save(output_path, "PNG", optimize=True)
        return

    _panel(bg, (cx, py), (cw, HEIGHT - 2 * _PAD), radius=18)
    ix, iy = cx + 24, py + 22
    inner_w = cw - 48

    # Vignette de l'objet + nom
    thumb = 76
    asset = ITEMS_ASSETS_DIR / f"{selection.get('item_code', '')}.png"
    if asset.exists():
        try:
            item_img = Image.open(asset).convert("RGBA").resize(
                (thumb, thumb), Image.LANCZOS,
            )
            bg.alpha_composite(item_img, (ix, iy))
        except Exception:  # noqa: BLE001  — un asset corrompu ne casse pas l'écran
            pass
    else:
        _panel(bg, (ix, iy), (thumb, thumb), radius=12, fill=(44, 38, 60, 200))

    tx = ix + thumb + 16
    draw_text_with_shadow(
        draw, (tx, iy + 4),
        _fit(draw, selection.get("item_name", ""), f_title, inner_w - thumb - 16),
        f_title, fill=_TEXT, shadow=_SHADOW,)
    qty = selection.get("result_quantity", 1)
    sub = selection.get("category_label", "")
    if qty > 1:
        sub += f"  ·  ×{qty}"
    draw_text_with_shadow(draw, (tx, iy + 32), sub, f_small, fill=_MUTED, shadow=_SHADOW)

    # Stats apportées
    sy = iy + thumb + 16
    bonuses = selection.get("stat_bonuses") or {}
    if bonuses:
        parts = [
            f"{STAT_EMOJIS[k]} {'+' if v > 0 else ''}{v}"
            for k, v in bonuses.items()
            if k in STAT_EMOJIS and isinstance(v, (int, float)) and v
        ][:6]
        draw_text_with_emojis(
            bg, (ix, sy), "   ".join(parts), f_body, fill=_TEXT, emoji_size=19,
        )
        sy += 34

    # Corps de fiche : le marchand VEND (description + panier), les artisans
    # FABRIQUENT (liste d'ingrédients). Deux lectures du même emplacement.
    if selection.get("kind") == "purchase":
        desc = selection.get("description") or ""
        if desc:
            for line in _wrap(draw, desc, f_small, inner_w, max_lines=3):
                draw_text_with_shadow(
                    draw, (ix, sy), line, f_small, fill=_MUTED, shadow=_SHADOW,
                )
                sy += 22
            sy += 6
        draw_text_with_shadow(
            draw, (ix, sy), "PANIER", f_label, fill=_DIM, shadow=_SHADOW,
        )
        sy += 26
        qty = selection.get("quantity", 1)
        unit = selection.get("unit_price", 0)
        draw_text_with_shadow(
            draw, (ix, sy), f"×{qty}  ·  {unit} or l'unité", f_small,
            fill=_TEXT, shadow=_SHADOW,
        )
        sy += 24
        draw_text_with_shadow(
            draw, (ix, sy),
            f"tu en possèdes déjà {selection.get('owned', 0)}",
            f_small, fill=_DIM, shadow=_SHADOW,
        )
        sy += 24
    else:
        draw_text_with_shadow(
            draw, (ix, sy), "INGRÉDIENTS", f_label, fill=_DIM, shadow=_SHADOW,
        )
        sy += 24
    for ing in (selection.get("ingredients") or [])[:4]:
        ok = ing.get("owned", 0) >= ing.get("required", 0)
        mark = "✅" if ok else "❌"
        text = (
            f"{mark} {ing.get('name', '?')} ×{ing.get('required', 0)}"
            f"   ({ing.get('owned', 0)} en stock)"
        )
        draw_text_with_emojis(
            bg, (ix, sy), text, f_small,
            fill=_OK if ok else _BAD, emoji_size=15,
        )
        sy += 24
    if not selection.get("ingredients") and selection.get("kind") != "purchase":
        draw_text_with_shadow(
            draw, (ix, sy), "aucun", f_small, fill=_DIM, shadow=_SHADOW,
        )
        sy += 24

    # Devis : prix + délai + puissance, en bas de la fiche
    by = py + (HEIGHT - 2 * _PAD) - 74
    _panel(bg, (ix - 10, by - 10), (inner_w + 20, 64), radius=12,
           fill=(18, 15, 28, 190))
    gold = selection.get("gold_cost", 0)
    afford = selection.get("can_afford", True)
    draw_text_with_emojis(
        bg, (ix, by), f"💰 {gold} or", f_title,
        fill=_GOLD if afford else _BAD, emoji_size=20,
    )
    if selection.get("kind") == "purchase":
        draw_text_with_shadow(
            draw, (ix + 190, by + 3), "prix total", f_small, fill=_MUTED,
            shadow=_SHADOW,
        )
    else:
        draw_text_with_emojis(
            bg, (ix + 190, by),
            f"⏱ {_format_duration(selection.get('duration_s', 0))}",
            f_title, fill=_TEXT, emoji_size=20,
        )
        draw_text_with_shadow(
            draw, (ix + 380, by + 3),
            f"puissance {selection.get('item_power', 0)}", f_small,
            fill=_MUTED, shadow=_SHADOW,
        )
    reason = selection.get("blocking_reason") or ""
    if reason:
        draw_text_with_shadow(
            draw, (ix, by + 32),
            _fit(draw, reason.replace("**", ""), f_small, inner_w), f_small,
            fill=_BAD, shadow=_SHADOW,)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(output_path, "PNG", optimize=True)


def panel_path(npc_code: str, player_id: int) -> str:
    GENERATED_NPCS_DIR.mkdir(parents=True, exist_ok=True)
    return str(GENERATED_NPCS_DIR / f"npc_{npc_code}_{player_id}.png")
