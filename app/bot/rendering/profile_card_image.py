"""Rendu Pillow de la fiche joueur, RÉPLIQUE de la carte du site admin.

Même agencement que la carte web : header (avatar photo, nom, @user·ID, méta
classe/or/points/streak/puissance, dates), badges Niveau + emblème de rang
(emblème LoL + sakura + lettre), 3 barres de progression (PV/Mana/XP) et une
grille de stats de combat. Emojis couleur via NotoColorEmoji.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from app.bot.rendering.emoji_text import draw_text_with_emojis, measure_text_with_emojis
from app.bot.rendering.image_utils import add_outline, crop_to_circle, download_image
from app.bot.rendering.pillow_utils import try_font
from app.shared.formatters import format_int

_RANKS_DIR = Path(__file__).resolve().parents[3] / "webapp" / "static" / "admin" / "ranks"

# Palette (thème clair du site).
C_BG = (253, 247, 250, 255)
C_CARD = (255, 255, 255, 255)
C_SOFT = (247, 238, 244, 255)
C_BORDER = (240, 216, 230, 255)
C_TEXT = (45, 34, 51, 255)
C_TSOFT = (110, 90, 114, 255)
C_TFAINT = (163, 149, 173, 255)
C_ACCENT = (217, 107, 170, 255)
C_ACCENT_SOFT = (251, 229, 241, 255)
C_VIOLET = (155, 109, 209, 255)

# Rang (lettre de base) -> (tier = fichier emblème, couleur).
_TIER = {
    "F": ("iron", (138, 138, 138)), "E": ("bronze", (176, 106, 59)),
    "D": ("silver", (184, 194, 207)), "C": ("gold", (227, 178, 60)),
    "B": ("platinum", (87, 201, 214)), "A": ("emerald", (46, 204, 113)),
    "S": ("diamond", (110, 168, 255)), "SS": ("master", (176, 111, 224)),
    "SSS": ("grandmaster", (227, 91, 74)), "Ω": ("challenger", (236, 208, 110)),
}

WIDTH = 960


def _tier(rank_label: str) -> tuple[str, tuple[int, int, int]]:
    base = (rank_label or "F").replace("+", "").replace("-", "")
    return _TIER.get(base, ("iron", (138, 138, 138)))


def _bar(draw: ImageDraw.ImageDraw, x, y, w, h, ratio, color):
    """Barre de progression arrondie (track + remplissage)."""
    r = h // 2
    draw.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=C_SOFT, outline=C_BORDER, width=1)
    fw = max(0, min(1.0, ratio)) * w
    if fw >= 2:
        draw.rounded_rectangle([x, y, x + fw, y + h], radius=r, fill=color)


def _panel(draw, x, y, w, h, radius=12, fill=C_SOFT, outline=C_BORDER):
    draw.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=fill, outline=outline, width=1)


def _emblem(rank_label: str, tier: str) -> Image.Image:
    """Compose l'emblème : image LoL (base) + 🌸 + lettre de rang. Taille ~84×74."""
    W, H = 88, 76
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    # base : image d'emblème en bas
    p = _RANKS_DIR / f"{tier}.png"
    if p.exists():
        emb = Image.open(p).convert("RGBA")
        ew, eh = emb.size
        s = min(84 / ew, 50 / eh)
        emb = emb.resize((max(1, int(ew * s)), max(1, int(eh * s))), Image.LANCZOS)
        canvas.alpha_composite(emb, ((W - emb.width) // 2, H - emb.height))
    # fleur de sakura au-dessus
    flower_font = try_font(44)
    draw_text_with_emojis(canvas, ((W - 44) // 2, -2), "🌸", flower_font, fill=(0, 0, 0, 255))
    # lettre de rang centrée sur la fleur (halo blanc)
    rank_font = try_font(20 if len(rank_label) <= 2 else 15, bold=True)
    d = ImageDraw.Draw(canvas)
    bb = d.textbbox((0, 0), rank_label, font=rank_font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    tx, ty = (W - tw) // 2 - bb[0], 16 - bb[1]
    d.text((tx, ty), rank_label, font=rank_font, fill=(122, 44, 83, 255),
           stroke_width=3, stroke_fill=(255, 255, 255, 255))
    return canvas


def render_profile_card(
    *, output_path: str, display_name: str, username: str, discord_id: int,
    avatar_url: str | None, level: int, class_name: str, rank_label: str,
    gold: int, skill_points: int, daily_streak: int, power: str,
    joined: str, last_seen: str, bars: dict, stats: dict,
) -> None:
    tier, tier_rgb = _tier(rank_label)
    margin = 44
    H = 496
    img = Image.new("RGBA", (WIDTH, H), C_BG)
    d = ImageDraw.Draw(img)
    # carte
    _panel(d, margin - 14, margin - 14, WIDTH - 2 * (margin - 14), H - 2 * (margin - 14),
           radius=22, fill=C_CARD, outline=C_BORDER)

    f_name = try_font(32, bold=True)
    f_sub = try_font(17)
    f_meta = try_font(17)
    f_dates = try_font(14)
    f_barlbl = try_font(17, bold=True)
    f_barval = try_font(15, bold=True)
    f_stat_lbl = try_font(14)
    f_stat_val = try_font(22, bold=True)
    f_pill = try_font(16, bold=True)

    # ---- HEADER ----
    ax, ay, asize = margin, margin, 92
    av = None
    if avatar_url:
        try:
            av = download_image(avatar_url)
        except Exception:
            av = None
    if av is None:
        av = Image.new("RGBA", (asize, asize), (200, 190, 205, 255))
    av = add_outline(crop_to_circle(av, asize), outline_size=3, outline_color=C_BORDER)
    img.alpha_composite(av, (ax - 3, ay - 3))

    ix = ax + asize + 22
    d.text((ix, ay - 2), display_name, font=f_name, fill=C_TEXT)
    draw_text_with_emojis(img, (ix, ay + 40), f"@{username} · ID {discord_id}", f_sub,
                          fill=C_TSOFT, shadow=None)
    meta = f"🧬 {class_name}   💰 {format_int(gold)}   📚 {skill_points} pts   🔥 {daily_streak}   ⚡ {power}"
    draw_text_with_emojis(img, (ix, ay + 66), meta, f_meta, fill=C_TSOFT, shadow=None)
    dates = f"🎉 Arrivé le {joined}    🕓 Dernière commande {last_seen}"
    draw_text_with_emojis(img, (ix, ay + 92), dates, f_dates, fill=C_TFAINT, shadow=None)

    # badges (haut droite) : pill Niveau + emblème
    right = WIDTH - margin
    pill_txt = f"Niv {level}"
    pw = int(d.textlength(pill_txt, font=f_pill)) + 26
    px = right - pw
    _panel(d, px, ay, pw, 30, radius=15, fill=C_ACCENT_SOFT, outline=C_ACCENT_SOFT)
    d.text((px + 13, ay + 5), pill_txt, font=f_pill, fill=C_ACCENT)
    emb = _emblem(rank_label, tier)
    img.alpha_composite(emb, (right - emb.width, ay + 36))

    # ---- BARRES PV / MANA / XP ----
    by = ay + asize + 44
    bx, bw, bh = margin, WIDTH - 2 * margin, 16
    gap = 44
    bar_specs = [
        ("❤️ PV", bars["hp"], (227, 91, 109), True),
        ("🔷 Mana", bars["mana"], (79, 134, 255), True),
        (f"⚡ XP → Niv {level + 1}", bars["xp"], C_ACCENT[:3], False),
    ]
    for i, (label, b, color, show_regen) in enumerate(bar_specs):
        y = by + i * gap
        draw_text_with_emojis(img, (bx, y), label, f_barlbl, fill=C_TSOFT, shadow=None)
        cur, mx = int(b["cur"]), max(1, int(b["max"]))
        val = f"{format_int(cur)} / {format_int(mx)}"
        if show_regen and b.get("regen"):
            val += f"  +{b['regen']}/min"
        vw = measure_text_with_emojis(val, f_barval, f_barval.size)
        draw_text_with_emojis(img, (bx + bw - vw, y + 1), val, f_barval, fill=C_TSOFT, shadow=None)
        _bar(d, bx, y + 22, bw, bh, cur / mx, color)

    # ---- STATS GRID (3 × 2) ----
    sy = by + 3 * gap + 6
    cols, cgap = 3, 14
    cw = (WIDTH - 2 * margin - cgap * (cols - 1)) // cols
    ch, rgap = 62, 12
    cells = [
        ("⚔️ Attaque", str(stats["attack"])),
        ("🛡️ Défense", str(stats["defense"])),
        ("💨 Vitesse", str(stats["speed"])),
        ("🎯 Crit", f"{stats['crit_chance']}% / {stats['crit_damage']}%"),
        ("🌀 Esquive", f"{stats['dodge']}%"),
        ("✨ Régén", f"PV {stats['hp_regeneration']} · M {stats['mana_regeneration']}"),
    ]
    for idx, (lbl, val) in enumerate(cells):
        cxx = margin + (idx % cols) * (cw + cgap)
        cyy = sy + (idx // cols) * (ch + rgap)
        _panel(d, cxx, cyy, cw, ch)
        draw_text_with_emojis(img, (cxx + 12, cyy + 10), lbl, f_stat_lbl, fill=C_TFAINT, shadow=None)
        d.text((cxx + 12, cyy + 30), val, font=f_stat_val, fill=C_TEXT)

    img.convert("RGB").save(output_path)
