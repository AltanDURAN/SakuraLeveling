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

from app.bot.rendering.emoji_text import (
    draw_text_with_emojis,
    measure_text_with_emojis,
)
from app.bot.rendering.pillow_utils import (
    draw_text_with_shadow,
    gradient_background,
    try_font,
)
from app.bot.rendering.element_visuals import tint_by_element
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
    element_code: str = ""        # code brut ("feu", "eau"…) pour la teinte
    # Inscrits au PROCHAIN assaut : ceux qui ont cliqué « Rejoindre » et
    # attendent 21h. Distinct de `warriors`, qui compte ceux ayant DÉJÀ frappé.
    registered: int = 0


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


def _plural(n: int, word: str) -> str:
    """Accord en nombre : « 1 combattant » / « 12 combattants »."""
    return f"{n} {word}" if n <= 1 else f"{n} {word}s"


def _compact(n: int) -> str:
    n = int(n)
    if n < 1_000:
        return str(n)
    if n < 1_000_000:
        s = f"{n / 1_000:.1f}".rstrip("0").rstrip(".")
        return f"{s}K"
    s = f"{n / 1_000_000:.2f}".rstrip("0").rstrip(".")
    return f"{s}M"


def _fit_font(draw, text: str, max_width: int, start: int, minimum: int = 26):
    """Réduit la fonte jusqu'à ce que `text` tienne dans `max_width`.

    Les noms de boss vont de « Slime » à « Seigneur de Guerre Gobelin » : sans
    ajustement, les longs débordaient sur le compte à rebours."""
    size = start
    while size > minimum:
        font = try_font(size, bold=True)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 2
    return try_font(minimum, bold=True)


def _truncate_to_width(text: str, font, max_width: int) -> str:
    """Tronque au caractère près selon la largeur RÉELLE rendue (une limite en
    nombre de caractères ne marche pas : « Alexandrine » est bien plus large
    que « Illiillii »)."""
    if measure_text_with_emojis(text, font, font.size) <= max_width:
        return text
    cut = text
    while cut and measure_text_with_emojis(cut + "…", font, font.size) > max_width:
        cut = cut[:-1]
    return (cut + "…") if cut else "…"


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
    """Bannière hebdo. Priorités de mise en page, dans cet ordre :

    1. QUAND se connecter (le compte à rebours de l'assaut) — l'info la plus
       actionnable, donc en gros dans l'en-tête ;
    2. OÙ EN EST le raid (PV, phase, % abattu) ;
    3. QUI porte l'effort (classement + honneurs) ;
    4. le colosse lui-même (art + stats), qui sert de contexte.

    L'art est volontairement réduit : à la taille où Discord affiche l'image
    (~550 px de large), la place doit aller aux données.
    """
    bg = gradient_background(WIDTH, HEIGHT, C_BG_TOP, C_BG_BOTTOM)
    draw = ImageDraw.Draw(bg)

    ratio = _ratio(data)
    phase_label, phase_color = phase_for(ratio)
    if data.defeated:
        phase_color = C_GOLD

    f_kicker = try_font(24, bold=True)
    f_title = try_font(58, bold=True)
    f_cta = try_font(40, bold=True)
    f_phase = try_font(30, bold=True)
    f_hp = try_font(36, bold=True)
    f_label = try_font(25, bold=True)
    f_row = try_font(27, bold=True)
    f_small = try_font(24)

    # ---------------- en-tête : identité + APPEL À L'ACTION ----------------
    _panel(bg, (24, 20, WIDTH - 24, 168), radius=20)
    kicker = "RAID DE LA SEMAINE"
    if data.week_label:
        kicker += f"  ·  {data.week_label}"
    kicker += f"  ·  JOUR {data.day_index}/{data.day_total}"
    draw_text_with_shadow(draw, (52, 36), kicker, f_kicker, C_GOLD, C_SHADOW)
    # Le compte à rebours occupe la droite : on calcule la place restante et on
    # ajuste la fonte du nom en conséquence.
    cta_reserved = 430 if (data.next_assault or data.defeated) else 60
    title_font = _fit_font(draw, data.boss_name.upper(),
                           WIDTH - 50 - cta_reserved, start=58, minimum=30)
    draw_text_with_shadow(draw, (50, 62), data.boss_name.upper(), title_font,
                          C_TEXT, C_SHADOW)

    # Élément + faiblesses : tactique, donc lisible (plus de gris minuscule).
    if data.element_label:
        el = f"{data.element_emoji} {data.element_label}".strip()
        if data.weaknesses:
            el += f"   —   faible à {data.weaknesses}"
        draw_text_with_emojis(bg, (52, 128), el, f_small, fill=C_MUTED,
                              emoji_size=f_small.size)

    # Compte à rebours : ce que le joueur doit retenir → gros, doré, à droite.
    if data.next_assault and not data.defeated:
        cta_main, _, cta_sub = data.next_assault.partition("(")
        cta_sub = cta_sub.rstrip(")")
        big = cta_sub.upper() if cta_sub else cta_main.strip().upper()
        small_txt = cta_main.strip() if cta_sub else "prochain assaut"
        bw = int(draw.textlength(big, font=f_cta))
        draw_text_with_emojis(bg, (WIDTH - 52 - bw - 44, 44), "⏳", f_cta,
                              fill=C_GOLD, emoji_size=f_cta.size)
        draw_text_with_shadow(draw, (WIDTH - 52 - bw, 46), big, f_cta,
                              C_GOLD, C_SHADOW)
        sw = int(draw.textlength(small_txt, font=f_small))
        draw_text_with_shadow(draw, (WIDTH - 52 - sw, 96), small_txt, f_small,
                              C_MUTED, C_SHADOW)
    elif data.defeated:
        txt = "COLOSSE TERRASSÉ"
        bw = int(draw.textlength(txt, font=f_cta))
        draw_text_with_shadow(draw, (WIDTH - 52 - bw, 60), txt, f_cta,
                              C_GOLD, C_SHADOW)

    # ---------------- colonne gauche : le colosse (contexte) ----------------
    art_x1, art_y1, art_x2, art_y2 = 24, 184, 392, HEIGHT - 104
    art = _load_boss_art(data.image_name, art_x2 - art_x1 - 8, art_y2 - art_y1 - 60)
    # Teinte élémentaire — même traitement que les spawns de monstres, pour que
    # le boss appartienne visuellement au même monde.
    if art is not None and data.element_code and not data.defeated:
        art = tint_by_element(art, data.element_code)
    if art is not None and data.defeated:
        grey = art.convert("LA").convert("RGBA")
        grey.putalpha(art.getchannel("A"))
        art = Image.blend(art, grey, 0.85)
    if art is not None:
        ax = art_x1 + (art_x2 - art_x1 - art.width) // 2
        ay = art_y1 + (art_y2 - 60 - art_y1 - art.height) // 2
        halo = Image.new("RGBA", bg.size, (0, 0, 0, 0))
        hd = ImageDraw.Draw(halo)
        cx, cy = ax + art.width // 2, ay + art.height // 2
        rad = int(max(art.width, art.height) * 0.60)
        for i in range(6):
            rr = rad - i * 12
            hd.ellipse([(cx - rr, cy - rr), (cx + rr, cy + rr)],
                       fill=(*phase_color[:3], int(46 * (1 - i / 6))))
        bg.alpha_composite(halo.filter(ImageFilter.GaussianBlur(38)))
        sh = Image.new("RGBA", bg.size, (0, 0, 0, 0))
        sw2 = int(art.width * 0.5)
        ImageDraw.Draw(sh).ellipse(
            [(cx - sw2, ay + art.height - 14), (cx + sw2, ay + art.height + 22)],
            fill=(0, 0, 0, 130))
        bg.alpha_composite(sh.filter(ImageFilter.GaussianBlur(16)))
        bg.alpha_composite(art, (ax, ay))

    # Stats du colosse, sous l'art (deux lignes lisibles plutôt qu'une longue).
    _panel(bg, (art_x1, art_y2 - 74, art_x2, art_y2), radius=14)
    # Une seule ligne : le calcul de largeur de textlength() ignore les emojis,
    # donc un alignement à droite se chevauchait avec la colonne de gauche.
    f_stats = try_font(22, bold=True)
    # Deux lignes : une seule ligne de 4 stats débordait de cette colonne étroite.
    draw_text_with_emojis(
        bg, (art_x1 + 20, art_y2 - 64),
        f"⚔️ ATK {_compact(data.attack)}      🛡️ DEF {_compact(data.defense)}",
        f_stats, fill=C_TEXT, emoji_size=f_stats.size)
    draw_text_with_emojis(
        bg, (art_x1 + 20, art_y2 - 34),
        f"💨 VIT {data.speed}      🎯 CRIT {data.crit_chance}%",
        f_stats, fill=C_TEXT, emoji_size=f_stats.size)

    # ---------------- colonne droite : l'état du raid ----------------
    rx1, rx2 = 412, WIDTH - 24

    _panel(bg, (rx1, 184, rx2, 322), radius=20)
    hp_txt = f"{data.current_hp:,} / {data.max_hp:,}".replace(",", " ")
    draw_text_with_shadow(draw, (rx1 + 26, 202), hp_txt, f_hp, C_TEXT, C_SHADOW)
    pct = f"{ratio * 100:.1f}%"
    pw = int(draw.textlength(pct, font=f_hp))
    draw_text_with_shadow(draw, (rx2 - 26 - pw, 202), pct, f_hp, phase_color, C_SHADOW)
    _draw_hp_bar(bg, (rx1 + 26, 248, rx2 - 26, 286), ratio, phase_color)
    phase_no = len(PHASES) - sum(1 for th, _, _ in PHASES if ratio > th) + 1
    phase_txt = "⚑ BOSS TERRASSÉ" if data.defeated else f"PHASE {phase_no} — {phase_label}"
    draw_text_with_emojis(bg, (rx1 + 26, 292), phase_txt, f_phase,
                          fill=phase_color, emoji_size=f_phase.size)
    done_txt = f"{(1 - ratio) * 100:.1f}% abattu par le raid"
    dtw = int(draw.textlength(done_txt, font=f_small))
    draw_text_with_shadow(draw, (rx2 - 26 - dtw, 298), done_txt, f_small,
                          C_MUTED, C_SHADOW)

    # Bandeau des INSCRITS au prochain assaut : avant 21h, c'est l'information
    # qui compte (combien serons-nous ?) et le bonus d'équipe qu'elle promet.
    if not data.defeated:
        _panel(bg, (rx1, 338, rx2, 392), radius=16,
               fill=(255, 214, 110, 26), border=(255, 214, 110, 90))
        bonus = min(50, max(0, (data.registered - 1) * 5))
        if data.registered > 0:
            insc = (f"🛡️ {_plural(data.registered, 'inscrit')} "
                    f"pour le prochain assaut   ·   +{bonus}% de stats en équipe")
        else:
            insc = "🛡️ Personne d'inscrit — cliquez sur Rejoindre pour l'assaut de 21h"
        draw_text_with_emojis(bg, (rx1 + 26, 352), insc, f_small, fill=C_GOLD,
                              emoji_size=f_small.size)
        rank_top = 404
    else:
        rank_top = 338

    # Classement des combattants (ceux qui ont DÉJÀ frappé cette semaine).
    _panel(bg, (rx1, rank_top, rx2, HEIGHT - 104), radius=20)
    draw_text_with_emojis(bg, (rx1 + 26, rank_top + 16), "🏆 MEILLEURS COMBATTANTS",
                          f_label, fill=C_GOLD, emoji_size=f_label.size)

    top = data.contributors[:4] if not data.defeated else data.contributors[:5]
    best = max((c.damage for c in top), default=1) or 1
    row_y = rank_top + 54
    for i, c in enumerate(top):
        medal = _MEDALS[i] if i < 3 else f"{i + 1}."
        dmg = _compact(c.damage)
        dw2 = int(draw.textlength(dmg, font=f_row))
        # Colonne du nom = de la marge gauche jusqu'au début du nombre.
        name_max = (rx1 + 390 - dw2) - (rx1 + 26) - 16
        label = _truncate_to_width(f"{medal} {c.display_name}", f_row, name_max)
        draw_text_with_emojis(bg, (rx1 + 26, row_y), label, f_row,
                              fill=C_TEXT, emoji_size=f_row.size)
        draw_text_with_shadow(draw, (rx1 + 390 - dw2, row_y), dmg, f_row,
                              C_GOLD, C_SHADOW)
        bar_x1, bar_x2 = rx1 + 410, rx2 - 26
        bw3 = int((bar_x2 - bar_x1) * (c.damage / best))
        track = Image.new("RGBA", bg.size, (0, 0, 0, 0))
        ImageDraw.Draw(track).rounded_rectangle(
            [(bar_x1, row_y + 8), (bar_x2, row_y + 24)], radius=8,
            fill=(255, 255, 255, 18), outline=(255, 255, 255, 30), width=1)
        bg.alpha_composite(track)
        if bw3 > 6:
            draw.rounded_rectangle([(bar_x1, row_y + 8), (bar_x1 + bw3, row_y + 24)],
                                   radius=8, fill=(*phase_color[:3], 255))
        row_y += 38
    if not top:
        draw_text_with_shadow(draw, (rx1 + 26, rank_top + 60),
                              "Aucun assaut cette semaine — soyez les premiers.",
                              f_small, C_MUTED, C_SHADOW)

    # Honneurs d'équipe : le raid ne se gagne pas qu'aux dégâts.
    if data.contributors:
        best_tank = max(data.contributors, key=lambda c: c.tanked)
        best_heal = max(data.contributors, key=lambda c: c.healed)
        hy = row_y + 8
        sep = Image.new("RGBA", bg.size, (0, 0, 0, 0))
        ImageDraw.Draw(sep).line([(rx1 + 26, hy - 10), (rx2 - 26, hy - 10)],
                                 fill=(255, 255, 255, 30), width=1)
        bg.alpha_composite(sep)
        parts = []
        if best_tank.tanked > 0:
            parts.append(f"🛡️ {best_tank.display_name} {_compact(best_tank.tanked)}")
        if best_heal.healed > 0:
            parts.append(f"💚 {best_heal.display_name} {_compact(best_heal.healed)}")
        honor = "   ·   ".join(parts) or "🛡️ Rempart et 💚 Soutien : à conquérir"
        draw_text_with_emojis(bg, (rx1 + 26, hy), honor, f_small, fill=C_MUTED,
                              emoji_size=f_small.size)

    # ---------------- pied : l'effort cumulé de la semaine ----------------
    _panel(bg, (24, HEIGHT - 88, WIDTH - 24, HEIGHT - 20), radius=18)
    total_damage = sum(c.damage for c in data.contributors)
    footer = (f"💥 {_compact(total_damage)} dégâts cumulés   ·   "
              f"⚔️ {_plural(data.assaults, 'assaut')}   ·   "
              f"👥 {_plural(data.warriors, 'combattant')}")
    draw_text_with_emojis(bg, (52, HEIGHT - 74), footer, f_row, fill=C_TEXT,
                          emoji_size=f_row.size)

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
