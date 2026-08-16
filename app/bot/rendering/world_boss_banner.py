"""Bannière de RAID du world boss — la pièce maîtresse visuelle de l'événement
hebdomadaire.

Remplace l'embed « barre de PV en emojis » par une image qui doit se lire en
une seconde, même en vignette Discord :
    • où en est le boss (barre de PV géante + phase + paliers franchis) ;
    • où en est la SEMAINE (jour N/7, prochaine offensive) ;
    • qui porte le raid (classement de contribution avec barres relatives) ;
    • l'effort collectif (combattants, dégâts cumulés, assauts).

Le rendu est pur (aucun accès DB) : on lui passe un `RaidBannerData`, il rend
un PNG. Ça le rend testable et rejouable hors Discord.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from app.bot.rendering.emoji_text import draw_text_with_emojis
from app.bot.rendering.pillow_utils import (
    draw_text_with_shadow,
    gradient_background,
    try_font,
)
from app.shared.paths import MOBS_ASSETS_DIR

WIDTH, HEIGHT = 1280, 760

# --- Palette : cohérente avec la bannière de profil, mais plus sombre/tendue --
C_BG_TOP = (14, 10, 20, 255)
C_BG_BOTTOM = (46, 18, 34, 255)
C_PANEL = (0, 0, 0, 150)
C_BORDER = (255, 255, 255, 40)
C_TEXT = (255, 255, 255, 245)
C_MUTED = (196, 186, 206, 255)
C_GOLD = (255, 214, 110, 255)
C_SHADOW = (0, 0, 0, 220)

# Phases du raid : (seuil bas de PV %, libellé, couleur de la barre)
PHASES: list[tuple[float, str, tuple[int, int, int, int]]] = [
    (0.75, "ÉVEIL", (90, 200, 120, 255)),
    (0.50, "COLÈRE", (240, 200, 80, 255)),
    (0.25, "FUREUR", (245, 140, 60, 255)),
    (0.00, "AGONIE", (230, 70, 80, 255)),
]

_MEDALS = ["🥇", "🥈", "🥉"]


@dataclass
class Contributor:
    display_name: str
    damage: int
    tanked: int = 0
    healed: int = 0


@dataclass
class RaidBannerData:
    boss_name: str
    image_name: str
    current_hp: int
    max_hp: int
    element_label: str = ""
    element_emoji: str = ""
    week_label: str = ""          # ex. "Semaine 34"
    day_index: int = 1            # jour N de la semaine de raid
    day_total: int = 7
    warriors: int = 0             # combattants distincts
    assaults: int = 0             # nombre d'assauts cumulés
    next_assault: str = ""        # ex. "21h00 (dans 4 h 12)"
    contributors: list[Contributor] = field(default_factory=list)
    defeated: bool = False
    # Stats de combat du colosse — info tactique, affichée UNE seule fois
    # (l'embed ne les répète plus).
    attack: int = 0
    defense: int = 0
    speed: int = 0
    crit_chance: int = 0
    weaknesses: str = ""          # ex. "🔥 Feu · 🌿 Plante"


def _ratio(data: RaidBannerData) -> float:
    if data.max_hp <= 0:
        return 0.0
    return max(0.0, min(1.0, data.current_hp / data.max_hp))


def phase_for(ratio: float) -> tuple[str, tuple[int, int, int, int]]:
    """Phase courante du raid selon les PV restants."""
    for threshold, label, color in PHASES:
        if ratio > threshold:
            return label, color
    return PHASES[-1][1], PHASES[-1][2]


def _compact(n: int) -> str:
    n = int(n)
    if n < 1_000:
        return str(n)
    if n < 1_000_000:
        s = f"{n / 1_000:.1f}".rstrip("0").rstrip(".")
        return f"{s}K"
    s = f"{n / 1_000_000:.2f}".rstrip("0").rstrip(".")
    return f"{s}M"


def _panel(base: Image.Image, box: tuple[int, int, int, int], radius: int = 18,
           fill=C_PANEL, border=C_BORDER) -> None:
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(box, radius=radius, fill=fill,
                                            outline=border, width=2)
    base.alpha_composite(layer)


def _load_boss_art(image_name: str, max_w: int, max_h: int) -> Image.Image | None:
    if not image_name:
        return None
    path = MOBS_ASSETS_DIR / image_name
    if not path.exists():
        return None
    try:
        art = Image.open(path).convert("RGBA")
    except Exception:  # noqa: BLE001
        return None
    art.thumbnail((max_w, max_h), Image.LANCZOS)
    return art


def _draw_hp_bar(base: Image.Image, box: tuple[int, int, int, int],
                 ratio: float, color: tuple[int, int, int, int]) -> None:
    """Barre de PV géante avec dégradé, lueur et marques de phases."""
    x1, y1, x2, y2 = box
    h = y2 - y1
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    d.rounded_rectangle(box, radius=h // 2, fill=(18, 14, 22, 235),
                        outline=(255, 255, 255, 45), width=2)

    fill_w = int((x2 - x1 - 6) * ratio)
    if fill_w > 8:
        bar = Image.new("RGBA", (fill_w, h - 6), (0, 0, 0, 0))
        bd = ImageDraw.Draw(bar)
        r, g, b, _ = color
        for i in range(fill_w):  # dégradé horizontal : sombre → vif
            t = i / max(1, fill_w - 1)
            bd.line([(i, 0), (i, h - 6)],
                    fill=(int(r * (0.55 + 0.45 * t)), int(g * (0.55 + 0.45 * t)),
                          int(b * (0.55 + 0.45 * t)), 255))
        mask = Image.new("L", bar.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [(0, 0), (bar.width - 1, bar.height - 1)], radius=(h - 6) // 2, fill=255)
        layer.paste(bar, (x1 + 3, y1 + 3), mask)

        glow = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ImageDraw.Draw(glow).rounded_rectangle(
            [(x1 + 3, y1 + 3), (x1 + 3 + fill_w, y2 - 3)],
            radius=(h - 6) // 2, fill=(*color[:3], 60))
        layer.alpha_composite(glow.filter(ImageFilter.GaussianBlur(9)))

    # Marques des paliers de phase : DISCRÈTES et uniquement sur la partie
    # déjà entamée (sinon elles segmentent la barre et on lit mal le taux réel).
    for threshold, _, _ in PHASES[:-1]:
        if threshold >= ratio:
            mx = int(x1 + (x2 - x1) * threshold)
            d.line([(mx, y1 + 9), (mx, y2 - 9)], fill=(255, 255, 255, 38), width=1)

    base.alpha_composite(layer)


def compose_raid_banner(output_path: str, data: RaidBannerData) -> str:
    bg = gradient_background(WIDTH, HEIGHT, C_BG_TOP, C_BG_BOTTOM)
    draw = ImageDraw.Draw(bg)

    ratio = _ratio(data)
    phase_label, phase_color = phase_for(ratio)
    # Victoire : la bannière bascule en or — c'est l'aboutissement de la
    # semaine, il doit se voir immédiatement dans le fil du salon.
    if data.defeated:
        phase_color = C_GOLD

    f_kicker = try_font(24, bold=True)
    f_title = try_font(60, bold=True)
    f_phase = try_font(30, bold=True)
    f_hp = try_font(34, bold=True)
    f_label = try_font(24, bold=True)
    f_row = try_font(26, bold=True)
    f_small = try_font(22)

    # ---------------- bandeau haut ----------------
    _panel(bg, (28, 24, WIDTH - 28, 132), radius=20)
    kicker = "RAID DE LA SEMAINE"
    if data.week_label:
        kicker += f"  ·  {data.week_label}"
    draw_text_with_shadow(draw, (56, 42), kicker, f_kicker, C_GOLD, C_SHADOW)
    title = data.boss_name.upper()
    draw_text_with_shadow(draw, (54, 68), title, f_title, C_TEXT, C_SHADOW)

    day_txt = f"JOUR {data.day_index}/{data.day_total}"
    dw = int(draw.textlength(day_txt, font=f_label))
    draw_text_with_shadow(draw, (WIDTH - 56 - dw, 46), day_txt, f_label, C_TEXT, C_SHADOW)
    if data.element_label:
        el = f"{data.element_emoji} {data.element_label}".strip()
        elw = int(draw.textlength(el, font=f_small)) + 30
        draw_text_with_emojis(bg, (WIDTH - 56 - max(dw, elw), 78), el, f_small,
                              fill=C_TEXT, emoji_size=f_small.size)
    if data.weaknesses:
        wk = f"faible à {data.weaknesses}"
        wkw = int(draw.textlength(wk, font=f_small)) + 40
        draw_text_with_emojis(bg, (WIDTH - 56 - wkw, 104), wk, f_small,
                              fill=C_MUTED, emoji_size=f_small.size - 2)

    # ---------------- art du boss ----------------
    art_box = (28, 148, 500, HEIGHT - 128)
    art = _load_boss_art(data.image_name, art_box[2] - art_box[0] - 16,
                         art_box[3] - art_box[1] - 16)
    if art is not None and data.defeated:
        # Colosse abattu : on le vide de ses couleurs et on l'assombrit.
        grey = art.convert("LA").convert("RGBA")
        grey.putalpha(art.getchannel("A"))
        art = Image.blend(art, grey, 0.85)
        dark = Image.new("RGBA", art.size, (0, 0, 0, 90))
        dark.putalpha(Image.eval(art.getchannel("A"), lambda a: min(a, 90)))
        art = Image.alpha_composite(art, dark)
    if art is not None:
        ax = art_box[0] + (art_box[2] - art_box[0] - art.width) // 2
        ay = art_box[1] + (art_box[3] - art_box[1] - art.height) // 2
        # Halo derrière le boss, teinté par la phase : donne de la présence et
        # signale l'état du raid même en vignette (vert → jaune → orange → rouge).
        halo = Image.new("RGBA", bg.size, (0, 0, 0, 0))
        hd = ImageDraw.Draw(halo)
        cx, cy = ax + art.width // 2, ay + art.height // 2
        rad = int(max(art.width, art.height) * 0.62)
        for i in range(6):
            a = int(46 * (1 - i / 6))
            rr = rad - i * 12
            hd.ellipse([(cx - rr, cy - rr), (cx + rr, cy + rr)],
                       fill=(*phase_color[:3], a))
        bg.alpha_composite(halo.filter(ImageFilter.GaussianBlur(38)))
        # Ombre portée au sol pour ancrer la créature.
        sh = Image.new("RGBA", bg.size, (0, 0, 0, 0))
        sw = int(art.width * 0.55)
        ImageDraw.Draw(sh).ellipse(
            [(cx - sw, ay + art.height - 18), (cx + sw, ay + art.height + 26)],
            fill=(0, 0, 0, 130))
        bg.alpha_composite(sh.filter(ImageFilter.GaussianBlur(18)))
        bg.alpha_composite(art, (ax, ay))

    # ---------------- colonne droite ----------------
    rx1, rx2 = 520, WIDTH - 28

    # PV
    _panel(bg, (rx1, 148, rx2, 336), radius=20)
    hp_txt = f"{data.current_hp:,} / {data.max_hp:,}".replace(",", " ")
    draw_text_with_shadow(draw, (rx1 + 28, 168), hp_txt, f_hp, C_TEXT, C_SHADOW)
    pct = f"{ratio * 100:.1f}%"
    pw = int(draw.textlength(pct, font=f_hp))
    draw_text_with_shadow(draw, (rx2 - 28 - pw, 168), pct, f_hp, phase_color, C_SHADOW)
    _draw_hp_bar(bg, (rx1 + 28, 214, rx2 - 28, 254), ratio, phase_color)
    phase_no = len(PHASES) - sum(1 for th, _, _ in PHASES if ratio > th) + 1
    phase_txt = f"PHASE {phase_no} — {phase_label}"
    if data.defeated:
        phase_txt = "⚑ BOSS TERRASSÉ"
    draw_text_with_shadow(draw, (rx1 + 28, 262), phase_txt, f_phase, phase_color, C_SHADOW)
    # Effort collectif : la part du colosse déjà abattue cette semaine. C'est LA
    # métrique qui donne le sentiment d'avancer ensemble.
    done_pct = (1 - ratio) * 100
    done_txt = f"{done_pct:.1f}% abattu par le raid"
    dtw = int(draw.textlength(done_txt, font=f_small))
    draw_text_with_shadow(draw, (rx2 - 28 - dtw, 268), done_txt, f_small, C_MUTED, C_SHADOW)

    # Stats de combat : ce qu'il faut savoir pour préparer l'assaut. Affichées
    # ICI et nulle part ailleurs (plus de doublon avec l'embed).
    stat_line = (f"⚔️ ATK {_compact(data.attack)}   "
                 f"🛡️ DEF {_compact(data.defense)}   "
                 f"💨 VIT {data.speed}   "
                 f"🎯 CRIT {data.crit_chance}%")
    draw_text_with_emojis(bg, (rx1 + 28, 300), stat_line, f_small,
                          fill=C_TEXT, emoji_size=f_small.size)

    # Classement de contribution
    _panel(bg, (rx1, 352, rx2, HEIGHT - 128), radius=20)
    draw_text_with_emojis(bg, (rx1 + 28, 370), "🏆 MEILLEURS COMBATTANTS",
                          f_label, fill=C_GOLD)
    top = data.contributors[:4]
    best = max((c.damage for c in top), default=1) or 1
    row_y = 408
    for i, c in enumerate(top):
        medal = _MEDALS[i] if i < 3 else f"{i + 1}."
        name = c.display_name if len(c.display_name) <= 14 else c.display_name[:13] + "…"
        draw_text_with_emojis(bg, (rx1 + 28, row_y), f"{medal} {name}", f_row,
                              fill=C_TEXT, emoji_size=f_row.size)
        dmg = _compact(c.damage)
        dw2 = int(draw.textlength(dmg, font=f_row))
        draw_text_with_shadow(draw, (rx1 + 300 - dw2, row_y), dmg, f_row, C_GOLD, C_SHADOW)
        bar_x1, bar_x2 = rx1 + 320, rx2 - 28
        bw = int((bar_x2 - bar_x1) * (c.damage / best))
        # ⚠️ Pillow : dessiner en semi-transparent DIRECTEMENT sur l'image la
        # rend opaque une fois aplatie (le canal alpha est écrasé, pas fondu).
        # La piste doit donc passer par un calque composité.
        track = Image.new("RGBA", bg.size, (0, 0, 0, 0))
        ImageDraw.Draw(track).rounded_rectangle(
            [(bar_x1, row_y + 8), (bar_x2, row_y + 24)], radius=8,
            fill=(255, 255, 255, 18), outline=(255, 255, 255, 30), width=1)
        bg.alpha_composite(track)
        if bw > 6:
            draw.rounded_rectangle([(bar_x1, row_y + 8), (bar_x1 + bw, row_y + 24)],
                                   radius=8, fill=(*phase_color[:3], 255))
        row_y += 44
    if not top:
        draw_text_with_shadow(draw, (rx1 + 28, 418),
                              "Aucun assaut pour l'instant — soyez les premiers.",
                              f_small, C_MUTED, C_SHADOW)

    # HONNEURS D'ÉQUIPE : le raid ne se gagne pas qu'aux dégâts. Mettre le
    # meilleur tank et le meilleur soutien à l'honneur valorise explicitement
    # les rôles de soutien et pousse à composer une vraie équipe.
    if data.contributors:
        best_tank = max(data.contributors, key=lambda c: c.tanked)
        best_heal = max(data.contributors, key=lambda c: c.healed)
        # Position calculée depuis la FIN réelle de la liste (elle est de
        # taille variable) — un offset fixe chevauchait les dernières lignes.
        hy = row_y + 10
        sep = Image.new("RGBA", bg.size, (0, 0, 0, 0))
        ImageDraw.Draw(sep).line([(rx1 + 28, hy - 14), (rx2 - 28, hy - 14)],
                                 fill=(255, 255, 255, 30), width=1)
        bg.alpha_composite(sep)
        parts = []
        if best_tank.tanked > 0:
            parts.append(f"🛡️ {best_tank.display_name} {_compact(best_tank.tanked)}")
        if best_heal.healed > 0:
            parts.append(f"💚 {best_heal.display_name} {_compact(best_heal.healed)}")
        honor_line = "   ·   ".join(parts) if parts else (
            "🛡️ Rempart et 💚 Soutien : à conquérir")
        draw_text_with_emojis(bg, (rx1 + 28, hy), honor_line, f_small,
                              fill=C_MUTED, emoji_size=f_small.size)

    # ---------------- bandeau bas ----------------
    _panel(bg, (28, HEIGHT - 112, WIDTH - 28, HEIGHT - 24), radius=20)
    total_damage = sum(c.damage for c in data.contributors)
    stats = (f"👥 {data.warriors} combattants   ·   "
             f"💥 {_compact(total_damage)} dégâts   ·   "
             f"⚔️ {data.assaults} assauts")
    draw_text_with_emojis(bg, (56, HEIGHT - 96), stats, f_row, fill=C_TEXT)
    if data.next_assault:
        draw_text_with_emojis(bg, (56, HEIGHT - 58),
                              f"⏳ Prochaine offensive : {data.next_assault}",
                              f_small, fill=C_MUTED)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(output_path, "PNG", optimize=True)
    return output_path


# ---------------------------------------------------------------------------
# Bannière de VICTOIRE — l'aboutissement de la semaine.
# ---------------------------------------------------------------------------

@dataclass
class VictoryRow:
    display_name: str
    damage: int
    tanked: int
    healed: int
    tier_label: str
    share: float
    gold: int


@dataclass
class VictoryBannerData:
    boss_name: str
    image_name: str
    max_hp: int
    week_label: str = ""
    days_taken: int = 0
    warriors: int = 0
    assaults: int = 0
    rows: list[VictoryRow] = field(default_factory=list)
    is_record: bool = False


def compose_victory_banner(output_path: str, data: VictoryBannerData) -> str:
    """Tableau d'honneur de fin de raid : qui a fait quoi, et à quel palier.

    Volontairement différent de la bannière hebdo (fond doré, pas de barre de
    PV) : c'est un moment, pas un état.
    """
    rows = sorted(data.rows, key=lambda r: r.share, reverse=True)[:10]
    height = max(560, 340 + len(rows) * 46)
    bg = gradient_background(WIDTH, height, (30, 22, 10, 255), (58, 34, 12, 255))
    draw = ImageDraw.Draw(bg)

    f_kicker = try_font(24, bold=True)
    f_title = try_font(56, bold=True)
    f_label = try_font(23, bold=True)
    f_row = try_font(24, bold=True)
    f_small = try_font(21)

    _panel(bg, (28, 24, WIDTH - 28, 140), radius=20)
    kicker = "RAID TERMINÉ"
    if data.week_label:
        kicker += f"  ·  {data.week_label}"
    if data.is_record:
        kicker += "  ·  🔥 NOUVEAU RECORD"
    draw_text_with_emojis(bg, (56, 42), kicker, f_kicker, fill=C_GOLD,
                          emoji_size=f_kicker.size)
    draw_text_with_shadow(draw, (54, 70), f"{data.boss_name.upper()} EST TOMBÉ",
                          f_title, C_GOLD, C_SHADOW)

    # Vignette du colosse abattu, dans le bandeau de titre (hors des colonnes
    # du tableau, qu'elle recouvrait).
    art = _load_boss_art(data.image_name, 96, 96)
    if art is not None:
        grey = art.convert("LA").convert("RGBA")
        grey.putalpha(art.getchannel("A"))
        bg.alpha_composite(Image.blend(art, grey, 0.9),
                           (WIDTH - 28 - art.width - 22, 32))

    summary = (f"👥 {data.warriors} combattants   ·   ⚔️ {data.assaults} assauts"
               f"   ·   🗓️ abattu en {data.days_taken} jour"
               f"{'s' if data.days_taken > 1 else ''}")
    draw_text_with_emojis(bg, (56, 168), summary, f_row, fill=C_TEXT,
                          emoji_size=f_row.size)

    _panel(bg, (28, 210, WIDTH - 28, height - 24), radius=20)
    draw_text_with_emojis(bg, (56, 228), "🏅 TABLEAU D'HONNEUR DE LA SEMAINE",
                          f_label, fill=C_GOLD, emoji_size=f_label.size)
    head_y = 264
    draw_text_with_shadow(draw, (56, head_y), "COMBATTANT", f_small, C_MUTED, C_SHADOW)
    draw_text_with_shadow(draw, (330, head_y), "PALIER", f_small, C_MUTED, C_SHADOW)
    draw_text_with_shadow(draw, (600, head_y), "DÉGÂTS", f_small, C_MUTED, C_SHADOW)
    draw_text_with_shadow(draw, (760, head_y), "ENCAISSÉ", f_small, C_MUTED, C_SHADOW)
    draw_text_with_shadow(draw, (930, head_y), "SOINS", f_small, C_MUTED, C_SHADOW)
    draw_text_with_shadow(draw, (1090, head_y), "OR", f_small, C_MUTED, C_SHADOW)

    y = head_y + 34
    for i, r in enumerate(rows):
        rank = _MEDALS[i] if i < 3 else f"{i + 1}."
        name = r.display_name if len(r.display_name) <= 15 else r.display_name[:14] + "…"
        draw_text_with_emojis(bg, (56, y), f"{rank} {name}", f_row, fill=C_TEXT,
                              emoji_size=f_row.size)
        draw_text_with_emojis(bg, (330, y), r.tier_label, f_small, fill=C_GOLD,
                              emoji_size=f_small.size)
        draw_text_with_shadow(draw, (600, y), _compact(r.damage), f_row, C_TEXT, C_SHADOW)
        draw_text_with_shadow(draw, (760, y), _compact(r.tanked), f_row, C_MUTED, C_SHADOW)
        draw_text_with_shadow(draw, (930, y), _compact(r.healed), f_row, C_MUTED, C_SHADOW)
        draw_text_with_shadow(draw, (1090, y), _compact(r.gold), f_row, C_GOLD, C_SHADOW)
        y += 46

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(output_path, "PNG", optimize=True)
    return output_path
