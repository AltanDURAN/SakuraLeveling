"""Écrans du bot en image, dans la DA commune (demande de l'auteur, 21/11/2026) :
`/quetes` et `/quetes_hebdo`, `/daily`, `/defi`, `/cd`, `/inventaire`.

Chaque fonction dessine une image et ne fait rien d'autre : les cogs la
lancent dans un thread et gardent leur embed texte en repli si le rendu
échoue. Les données arrivent déjà prêtes (aucun accès à la base ici).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image, ImageDraw

from app.bot.rendering import ui_kit as ui
from app.bot.rendering.emoji_text import draw_text_with_emojis, measure_text_with_emojis
from app.bot.rendering.pillow_utils import try_font
from app.shared.formatters import format_int
from app.shared.paths import ITEMS_ASSETS_DIR

TIER_COLORS = {"easy": ui.GREEN, "medium": ui.GOLD, "hard": ui.HP}
TIER_LABELS = {"easy": "FACILE", "medium": "MOYENNE", "hard": "DIFFICILE"}


# ------------------------------------------------------------------ quêtes --
@dataclass(frozen=True)
class QuestCard:
    name: str
    description: str
    tier: str
    progress: int
    total: int
    gold: int
    xp: int
    items: str = ""                 # « 2× Potion de soin, … » (déjà nommé)
    completed: bool = False
    claimed: bool = False


def compose_quests(output_path: str, *, title: str, subtitle: str, quests: list[QuestCard],
                   empty_text: str, seed: int = 0) -> None:
    card_h = 150
    n = max(1, len(quests))
    to_claim = sum(1 for q in quests if q.completed and not q.claimed)
    height = ui.PAD + 128 + n * card_h + (n - 1) * ui.GAP + ui.GAP + 56 + ui.PAD
    img = ui.canvas(height, seed)
    draw = ImageDraw.Draw(img)
    top = ui.header(img, title, subtitle, accent=ui.GREEN)
    done = sum(1 for q in quests if q.claimed)
    f_chip = try_font(16, bold=True)
    x = ui.PAD + ui.chip(img, ui.PAD, top, f"📋 {done}/{len(quests)} réclamée{'s' if done > 1 else ''}", f_chip,
                         fill=(30, 52, 40, 225), outline=(*ui.GREEN, 170), ink=(*ui.GREEN, 255)) + 10
    if to_claim:
        ui.gold_chip(img, x, top, f"🎁 {to_claim} à réclamer", f_chip)

    y = top + 42
    if not quests:
        ui.panel(img, (ui.PAD, y), (ui.WIDTH - 2 * ui.PAD, card_h), fill=(28, 24, 40, 205), outline=(*ui.LILAC, 90))
        lines = ui.wrap(draw, empty_text, try_font(18), ui.WIDTH - 2 * ui.PAD - 40, 3)
        for i, line in enumerate(lines):
            ui.shadow_text(draw, (ui.PAD + 20, y + 40 + i * 26), line, try_font(18), fill=ui.MUTED)
    for q in quests:
        color = (110, 104, 124) if q.claimed else TIER_COLORS.get(q.tier, ui.LILAC)
        w = ui.WIDTH - 2 * ui.PAD
        ui.tinted_card(img, (ui.PAD, y), (w, card_h), color)
        # Statut à droite : à faire / à réclamer / réclamée.
        if q.claimed:
            status, fill, ink = "✓ RÉCLAMÉE", (44, 40, 56, 230), ui.DIM
        elif q.completed:
            status, fill, ink = "🎁 À RÉCLAMER", (92, 70, 20, 235), (*ui.GOLD, 255)
        else:
            status, fill, ink = TIER_LABELS.get(q.tier, "QUÊTE"), (40, 32, 60, 220), (*ui.lighten(color, 0.2), 255)
        f_status = try_font(14, bold=True)
        sw = measure_text_with_emojis(status, f_status, 14) + 24
        ui.panel(img, (ui.PAD + w - 20 - sw, y + 18), (sw, 28), radius=14, fill=fill)
        draw_text_with_emojis(img, (ui.PAD + w - 20 - sw + 12, y + 24), status, f_status, fill=ink, emoji_size=14)

        f_name = try_font(22, bold=True)
        name = ui.clip(draw, q.name, f_name, w - sw - 70)
        ui.shadow_text(draw, (ui.PAD + 20, y + 18), name, f_name, fill=ui.DIM if q.claimed else ui.TEXT)
        f_desc = try_font(15)
        for i, line in enumerate(ui.wrap(draw, q.description, f_desc, w - 40, 1)):
            ui.shadow_text(draw, (ui.PAD + 20, y + 52 + i * 20), line, f_desc, fill=ui.MUTED)

        # Progression
        ratio = q.progress / max(q.total, 1)
        count = f"{format_int(min(q.progress, q.total))} / {format_int(q.total)}"
        f_count = try_font(16, bold=True)
        cw = draw.textlength(count, font=f_count)
        ui.bar(img, (ui.PAD + 20, y + 86), (int(w - 60 - cw), 12), ratio, color, glow=not q.claimed)
        ui.shadow_text(draw, (ui.PAD + w - 20 - cw, y + 81), count, f_count,
                       fill=(*ui.lighten(color, 0.2), 255) if not q.claimed else ui.DIM)
        # Récompenses : chaque chose à sa couleur (or, XP, objets).
        f_rew = try_font(15, bold=True)
        parts = [(f"💰 {format_int(q.gold)} or", ui.GOLD), (f"✨ {format_int(q.xp)} XP", ui.XP)]
        if q.items:
            parts.append((f"🎁 {q.items}", ui.ITEM))
        if q.claimed:
            parts = [(text, ui.DIM) for text, _ in parts]
        ui.segments(img, (ui.PAD + 20, y + 112), parts, f_rew, max_w=w - 40)
        y += card_h + ui.GAP

    note = ("🎁 Clique sur « Réclamer » sous l'image pour toucher tes récompenses."
            if to_claim else "⏳ Les quêtes avancent toutes seules en jouant : combats, tour, défis.")
    ui.footer(img, y, note, color=ui.GOLD if to_claim else ui.GREEN)
    ui.save(img, output_path)


# --------------------------------------------------------------- solde du jour --
STREAK_STEPS = ((7, "Habitué"), (30, "Taverne Addict"), (100, "Pilier"))


def compose_daily(output_path: str, *, name: str, streak: int, gold: int, bonus_pct: int,
                  days_missed: int = 0, streak_before: int = 0, guard_used: bool = False,
                  titles: list[str] | None = None, bonus_items: list[tuple[str, int]] | None = None,
                  seed: int = 0) -> None:
    notes: list[tuple[str, tuple]] = []
    if guard_used:
        notes.append(("⏳ Ton sablier de fidélité s'est brisé : un jour manqué t'est pardonné.", ui.TIME))
    if days_missed:
        notes.append((f"💔 {days_missed} jour{'s' if days_missed > 1 else ''} manqué{'s' if days_missed > 1 else ''} : "
                      f"ta série de {streak_before} a été divisée par deux par jour d'absence.", ui.HP))
    for title in titles or []:
        notes.append((f"🏷️ Nouveau titre : {title}", ui.CRIT_DMG))
    for item, qty in bonus_items or []:
        notes.append((f"🎁 Bonus de titre : {qty}× {item}", ui.ITEM))
    height = ui.PAD + 88 + 200 + ui.GAP + 120 + len(notes) * 30 + ui.GAP + 56 + ui.PAD
    img = ui.canvas(height, seed)
    draw = ImageDraw.Draw(img)
    top = ui.header(img, "🌅 Solde du jour", f"La guilde paie {name}", accent=ui.GOLD)

    # Montant et série, côte à côte.
    w = (ui.WIDTH - 2 * ui.PAD - ui.GAP) // 2
    ui.tinted_card(img, (ui.PAD, top), (w, 200), ui.GOLD)
    ui.shadow_text(draw, (ui.PAD + 22, top + 24), "TU REÇOIS", try_font(16, bold=True), fill=(*ui.GOLD, 255))
    amount = format_int(gold)
    f_amount = ui.fit(draw, amount, 64, w - 130)
    ui.shadow_text(draw, (ui.PAD + 22, top + 56), amount, f_amount, fill=ui.TEXT)
    aw = draw.textlength(amount, font=f_amount)
    draw_text_with_emojis(img, (int(ui.PAD + 32 + aw), top + 76), "💰 or", try_font(24, bold=True),
                          fill=(*ui.GOLD, 255), emoji_size=28)
    if bonus_pct:
        ui.gold_chip(img, ui.PAD + 22, top + 146, f"🔥 dont +{bonus_pct} % de série", try_font(15, bold=True))

    x2 = ui.PAD + w + ui.GAP
    flame = ui.FIRE
    ui.tinted_card(img, (x2, top), (w, 200), flame)
    ui.shadow_text(draw, (x2 + 22, top + 24), "SÉRIE", try_font(16, bold=True), fill=(*flame, 255))
    days = f"{streak}"
    f_days = try_font(64, bold=True)
    ui.shadow_text(draw, (x2 + 22, top + 56), days, f_days, fill=ui.TEXT)
    dw = draw.textlength(days, font=f_days)
    draw_text_with_emojis(img, (int(x2 + 32 + dw), top + 76), f"🔥 jour{'s' if streak > 1 else ''}",
                          try_font(24, bold=True), fill=(*flame, 255), emoji_size=28)
    ui.bar(img, (x2 + 22, top + 154), (w - 44, 10), min(1.0, bonus_pct / 90), flame, glow=True)
    ui.shadow_text(draw, (x2 + 22, top + 170), "bonus de série : +3 % par jour, jusqu'à +90 %", try_font(13),
                   fill=ui.DIM)

    # Paliers de la série (titres).
    y = top + 200 + ui.GAP
    ui.panel(img, (ui.PAD, y), (ui.WIDTH - 2 * ui.PAD, 120), radius=16, fill=(40, 26, 30, 215),
             outline=(*flame, 140))
    ui.shadow_text(draw, (ui.PAD + 20, y + 14), "PALIERS DE LA SÉRIE · un titre à chacun", try_font(13, bold=True),
                   fill=(*ui.lighten(flame, 0.2), 255))
    track_x, track_w, track_y = ui.PAD + 30, ui.WIDTH - 2 * ui.PAD - 60, y + 58
    ui.bar(img, (track_x, track_y), (track_w, 10), min(1.0, streak / 100), flame, glow=True)
    for step, label in STREAK_STEPS:
        mx = track_x + int(track_w * step / 100)
        reached = streak >= step
        color = (*flame, 255) if reached else (90, 84, 110, 255)
        draw.ellipse([mx - 9, track_y - 4, mx + 9, track_y + 14], fill=color, outline=(20, 16, 30, 255), width=2)
        f_step = try_font(14, bold=True)
        text = f"{'✓ ' if reached else ''}{step} j · {label}"
        tw = measure_text_with_emojis(text, f_step, 14)
        draw_text_with_emojis(img, (int(min(max(ui.PAD + 20, mx - tw / 2), ui.WIDTH - ui.PAD - 20 - tw)), track_y + 24),
                              text, f_step, fill=ui.TEXT if reached else ui.DIM, emoji_size=14)
    y += 120 + ui.GAP
    for note, color in notes:
        draw_text_with_emojis(img, (ui.PAD + 4, y), ui.clip(draw, note, try_font(16, bold=True), ui.WIDTH - 2 * ui.PAD),
                              try_font(16, bold=True), fill=(*ui.lighten(color, 0.15), 255), emoji_size=17)
        y += 30
    if notes:
        y += 4
    ui.footer(img, y, "📋 Ta routine du jour : /quetes · /tour · /defi. Un jour manqué divise la série par deux.",
              color=ui.FIRE)
    ui.save(img, output_path)


# --------------------------------------------------------------------- défis --
ROLE_COLORS = {"dps": ui.ATK, "tank": ui.DEF, "soutien": ui.REGEN}


@dataclass(frozen=True)
class TrialCard:
    role: str
    label: str              # « ⚔️ DPS »
    variant: str
    description: str
    best: str = ""          # « 12 345 · 2 essais · 1er sur 3 » (vide : pas tenté)


def compose_trials(output_path: str, *, title: str, subtitle: str, cards: list[TrialCard], week: str = "",
                   banner: str = "", seed: int = 0) -> None:
    card_h = 250
    height = ui.PAD + 128 + card_h + ui.GAP + (64 if week else 0) + 56 + ui.PAD
    img = ui.canvas(height, seed)
    draw = ImageDraw.Draw(img)
    top = ui.header(img, title, subtitle, accent=ui.CRIT)
    if banner:
        ui.gold_chip(img, ui.PAD, top, banner, try_font(15, bold=True))
    y = top + 42
    w = (ui.WIDTH - 2 * ui.PAD - 2 * ui.GAP) // 3
    for i, card in enumerate(cards):
        x = ui.PAD + i * (w + ui.GAP)
        color = ROLE_COLORS.get(card.role, ui.LILAC)
        ui.tinted_card(img, (x, y), (w, card_h), color)
        draw_text_with_emojis(img, (x + 18, y + 20), card.label, try_font(20, bold=True),
                              fill=(*ui.lighten(color, 0.2), 255), emoji_size=20)
        f_var = ui.fit(draw, card.variant, 20, w - 36)
        ui.shadow_text(draw, (x + 18, y + 54), card.variant, f_var)
        for j, line in enumerate(ui.wrap(draw, card.description, try_font(14), w - 36, 4)):
            ui.shadow_text(draw, (x + 18, y + 88 + j * 19), line, try_font(14), fill=ui.MUTED)
        if card.best:
            ui.panel(img, (x + 14, y + card_h - 62), (w - 28, 46), radius=12, fill=(*color, 40),
                     outline=(*color, 140))
            ui.shadow_text(draw, (x + 26, y + card_h - 56), "TON MEILLEUR", try_font(11, bold=True),
                           fill=(*ui.lighten(color, 0.3), 255))
            ui.shadow_text(draw, (x + 26, y + card_h - 40), ui.clip(draw, card.best, try_font(15, bold=True), w - 52),
                           try_font(15, bold=True))
        else:
            ui.shadow_text(draw, (x + 18, y + card_h - 40), "Pas encore tenté aujourd'hui", try_font(14), fill=ui.DIM)
    y += card_h + ui.GAP
    if week:
        ui.panel(img, (ui.PAD, y), (ui.WIDTH - 2 * ui.PAD, 48), radius=14, fill=(24, 40, 46, 215),
                 outline=(*ui.TIME, 150))
        draw_text_with_emojis(img, (ui.PAD + 20, y + 14), ui.clip(draw, f"📅 Ta semaine : {week}", try_font(16, bold=True),
                                                                  ui.WIDTH - 2 * ui.PAD - 40),
                              try_font(16, bold=True), fill=(*ui.lighten(ui.TIME, 0.2), 255), emoji_size=17)
        y += 48 + ui.GAP
    ui.footer(img, y, "🎯 /defi role: pour tenter · même build = même score · potions et élixirs interdits",
              color=ui.CRIT)
    ui.save(img, output_path)


# ---------------------------------------------------------- temps de recharge --
@dataclass(frozen=True)
class Timer:
    label: str              # « 🌅 Récompense quotidienne »
    ready: str              # « prêt à 21:05 · dans 3 h 12 »
    ratio: float | None = None  # part déjà écoulée (0 → 1) ; None = pas de barre
    color: tuple = (90, 210, 230)


def compose_cooldowns(output_path: str, *, name: str, timers: list[Timer], tickets: str, extras: list[str],
                      seed: int = 0) -> None:
    row_h = 70
    rows = max(1, len(timers))
    height = ui.PAD + 98 + rows * (row_h + 10) + ui.GAP + len(extras) * 30 + 56 + 56 + ui.PAD
    img = ui.canvas(height, seed)
    draw = ImageDraw.Draw(img)
    y = ui.header(img, f"⏳ Temps de recharge de {name}", "Ce qui attend, et quand ce sera prêt", accent=ui.TIME) + 6
    w = ui.WIDTH - 2 * ui.PAD
    if not timers:
        ui.panel(img, (ui.PAD, y), (w, row_h), radius=14, fill=(30, 46, 38, 215), outline=(*ui.GREEN, 140))
        draw_text_with_emojis(img, (ui.PAD + 20, y + 24), "✅ Rien ne recharge : tout est disponible !",
                              try_font(19, bold=True), fill=(*ui.GREEN, 255), emoji_size=20)
        y += row_h + 10
    for timer in timers:
        color = timer.color
        ui.panel(img, (ui.PAD, y), (w, row_h), radius=14, fill=(*[int(c * 0.16) + 18 for c in color], 225),
                 outline=(*color, 150))
        ui.panel(img, (ui.PAD + 8, y + 12), (5, row_h - 24), radius=3, fill=(*color, 255))
        f_label = try_font(18, bold=True)
        draw_text_with_emojis(img, (ui.PAD + 26, y + 12), ui.clip(draw, timer.label, f_label, w / 2), f_label,
                              fill=(*ui.lighten(color, 0.3), 255), emoji_size=18)
        f_ready = try_font(16, bold=True)
        rw = measure_text_with_emojis(timer.ready, f_ready, 16)
        draw_text_with_emojis(img, (int(ui.PAD + w - 20 - rw), y + 13), timer.ready, f_ready,
                              fill=ui.TEXT, emoji_size=16)
        ui.bar(img, (ui.PAD + 26, y + 46), (w - 46, 8), timer.ratio if timer.ratio is not None else 1.0, color,
               glow=True)
        y += row_h + 10
    y += ui.GAP - 10
    tower = (150, 140, 230)
    ui.panel(img, (ui.PAD, y), (w, 48), radius=14, fill=(34, 30, 56, 220), outline=(*tower, 160))
    draw_text_with_emojis(img, (ui.PAD + 20, y + 14), ui.clip(draw, tickets, try_font(16, bold=True), w - 40),
                          try_font(16, bold=True), fill=(*ui.lighten(tower, 0.3), 255), emoji_size=17)
    y += 48 + 8
    for extra in extras:
        draw_text_with_emojis(img, (ui.PAD + 4, y), ui.clip(draw, extra, try_font(16, bold=True), w),
                              try_font(16, bold=True), fill=(*ui.lighten(ui.ITEM, 0.2), 255), emoji_size=17)
        y += 30
    ui.footer(img, y + 4, "🔔 La case Confort « notifications » de l'arbre te prévient quand c'est prêt.",
              color=ui.TIME)
    ui.save(img, output_path)


# ---------------------------------------------------------------- inventaire --
@dataclass(frozen=True)
class Slot:
    code: str
    name: str
    quantity: int
    category: str = ""


def item_color(code: str, category: str = "") -> tuple:
    """La couleur d'un objet, d'après ce qu'il fait (même logique partout)."""
    if "mana" in code:
        return ui.MANA
    if "soin" in code:
        return ui.HP
    if code.startswith("elixir_recuperation"):
        return ui.REGEN
    if code.startswith("elixir_force"):
        return ui.ATK
    if code.startswith("elixir_garde"):
        return ui.DEF
    if code.startswith("elixir"):
        return ui.CRIT_DMG
    if category == "cosmetic" or code.startswith(("booster", "carte")):
        return ui.PINK
    if code.startswith(("cor_", "sceau_", "parchemin", "jeton", "sablier")):
        return ui.GOLD
    if category == "resource":
        return ui.EARTH
    return ui.ITEM


def _icon(code: str, size: int) -> Image.Image | None:
    for ext in ("png", "webp", "jpg"):
        path = ITEMS_ASSETS_DIR / f"{code}.{ext}"
        if path.exists():
            try:
                with Image.open(path) as raw:
                    icon = raw.convert("RGBA")
                icon.thumbnail((size, size))
                return icon
            except OSError:
                return None
    return None


MAX_SLOTS = 32


def compose_inventory(output_path: str, *, name: str, page_label: str, slots: list[Slot],
                      empty_text: str, seed: int = 0) -> None:
    cols, tile_h = 4, 128
    shown = slots[:MAX_SLOTS]
    rows = max(1, -(-len(shown) // cols))
    height = ui.PAD + 128 + rows * (tile_h + 12) + ui.GAP + 56 + ui.PAD
    img = ui.canvas(height, seed)
    draw = ImageDraw.Draw(img)
    total = sum(s.quantity for s in slots)
    top = ui.header(img, f"🎒 Inventaire de {name}", page_label, accent=ui.ITEM)
    ui.chip(img, ui.PAD, top, f"{len(slots)} objet{'s' if len(slots) > 1 else ''} · {format_int(total)} en tout",
            try_font(15, bold=True), fill=(44, 32, 64, 225), outline=(*ui.ITEM, 170), ink=(*ui.lighten(ui.ITEM, 0.3), 255))
    y = top + 44
    w = ui.WIDTH - 2 * ui.PAD
    if not slots:
        ui.panel(img, (ui.PAD, y), (w, tile_h), radius=14, fill=(28, 24, 40, 205), outline=(*ui.LILAC, 90))
        for i, line in enumerate(ui.wrap(draw, empty_text, try_font(18), w - 40, 3)):
            ui.shadow_text(draw, (ui.PAD + 20, y + 34 + i * 26), line, try_font(18), fill=ui.MUTED)
    tile_w = (w - (cols - 1) * 12) // cols
    for i, slot in enumerate(shown):
        r, c = divmod(i, cols)
        x, ty = ui.PAD + c * (tile_w + 12), y + r * (tile_h + 12)
        color = item_color(slot.code, slot.category)
        ui.panel(img, (x, ty), (tile_w, tile_h), radius=14, fill=(*[int(c * 0.14) + 18 for c in color], 225),
                 outline=(*color, 150))
        ui.panel(img, (x + 14, ty), (tile_w - 28, 4), radius=2, fill=(*color, 255))
        icon = _icon(slot.code, 72)
        if icon is not None:
            img.alpha_composite(icon, (x + 14 + (72 - icon.width) // 2, ty + 14 + (72 - icon.height) // 2))
        else:
            ui.panel(img, (x + 14, ty + 14), (72, 72), radius=12, fill=(44, 38, 62, 220))
            draw_text_with_emojis(img, (x + 34, ty + 34), "📦", try_font(28), fill=ui.TEXT, emoji_size=32)
        qty = f"×{format_int(slot.quantity)}"
        f_qty = ui.fit(draw, qty, 26, tile_w - 104)
        ui.shadow_text(draw, (x + 96, ty + 34), qty, f_qty, fill=(*ui.lighten(color, 0.2), 255))
        for j, line in enumerate(ui.wrap(draw, slot.name, try_font(14, bold=True), tile_w - 24, 2)):
            ui.shadow_text(draw, (x + 12, ty + 92 + j * 17), line, try_font(14, bold=True))
    y += rows * (tile_h + 12) - 12 + ui.GAP
    more = len(slots) - len(shown)
    note = (f"… et {more} autre{'s' if more > 1 else ''} objet{'s' if more > 1 else ''}."
            if more else "🧪 Les potions se boivent avec /utiliser · ⚔️ l'équipement est dans /equipement_liste.")
    ui.footer(img, y, note, color=ui.ITEM)
    ui.save(img, output_path)


# ---------------------------------------------------------- listes à sections --
@dataclass(frozen=True)
class Row:
    icon: str
    text: str                       # le nom (gras)
    right: str = ""                 # la valeur, à droite
    sub: str = ""                   # une ligne de détail, en dessous
    ratio: float | None = None      # une barre de progression (0 → 1)
    tone: str = ""                  # "gold" (à toi), "dim" (grisé), "" (normal)


@dataclass(frozen=True)
class Section:
    heading: str
    rows: list[Row] = field(default_factory=list)
    color: tuple[int, int, int] = (150, 120, 210)


def compose_list(output_path: str, *, title: str, subtitle: str, sections: list[Section], footer: str = "",
                 chips: list[str] | None = None, accent=ui.GOLD, seed: int = 0) -> None:
    """Un écran de listes (titres, records…) : sections teintées, une ligne par
    élément, sa valeur à droite, un détail et une barre facultatifs."""
    def row_h(r: Row) -> int:
        return 34 + (22 if r.sub else 0) + (14 if r.ratio is not None else 0)

    body = sum(56 + sum(row_h(r) for r in s.rows) + 10 for s in sections) + max(0, len(sections) - 1) * ui.GAP
    height = ui.PAD + 128 + body + ui.GAP + (56 + ui.GAP if footer else 0) + ui.PAD
    img = ui.canvas(height, seed)
    draw = ImageDraw.Draw(img)
    top = ui.header(img, title, subtitle, accent=accent)
    x = ui.PAD
    f_chip = try_font(15, bold=True)
    for text in chips or []:
        x += ui.gold_chip(img, x, top, text, f_chip) + 10
    y = top + (44 if chips else 4)
    w = ui.WIDTH - 2 * ui.PAD
    f_head, f_name, f_right, f_sub = try_font(15, bold=True), try_font(17, bold=True), try_font(16, bold=True), try_font(14)
    for section in sections:
        h = 56 + sum(row_h(r) for r in section.rows) + 10
        ui.tinted_card(img, (ui.PAD, y), (w, h), section.color)
        draw_text_with_emojis(img, (ui.PAD + 20, y + 20), section.heading.upper(), f_head,
                              fill=(*ui.lighten(section.color, 0.25), 255), emoji_size=16)
        ry = y + 52
        for r in section.rows:
            ink = (*ui.GOLD, 255) if r.tone == "gold" else ui.DIM if r.tone == "dim" else ui.TEXT
            right_w = measure_text_with_emojis(r.right, f_right, 16) if r.right else 0
            draw_text_with_emojis(img, (ui.PAD + 20, ry + 4), r.icon, f_name, fill=ink, emoji_size=19)
            name = ui.clip(draw, r.text, f_name, w - 90 - right_w - 20)
            ui.shadow_text(draw, (ui.PAD + 50, ry + 4), name, f_name, fill=ink)
            if r.right:
                draw_text_with_emojis(img, (int(ui.PAD + w - 20 - right_w), ry + 5), r.right, f_right,
                                      fill=(*ui.GOLD, 255) if r.tone == "gold" else (*ui.lighten(section.color, 0.25), 255),
                                      emoji_size=16)
            ny = ry + 30
            if r.sub:
                sub = ui.clip(draw, r.sub, f_sub, w - 90)
                draw_text_with_emojis(img, (ui.PAD + 50, ny), sub, f_sub, fill=ui.MUTED if r.tone != "dim" else ui.DIM,
                                      emoji_size=14)
                ny += 22
            if r.ratio is not None:
                ui.bar(img, (ui.PAD + 50, ny + 2), (w - 90, 6), r.ratio, section.color)
            ry += row_h(r)
        y += h + ui.GAP
    if footer:
        ui.footer(img, y, footer, color=accent)
    ui.save(img, output_path)


# --------------------------------------------------------------------- bourse --
def compose_gold(output_path: str, *, name: str, gold: int, career: int, is_self: bool, seed: int = 0) -> None:
    height = ui.PAD + 88 + 190 + ui.GAP + 56 + ui.PAD
    img = ui.canvas(height, seed)
    draw = ImageDraw.Draw(img)
    top = ui.header(img, "💰 Ta bourse" if is_self else f"💰 Bourse de {name}",
                    "L'or se gagne en combat, en quêtes, aux défis et à la solde du jour", accent=ui.GOLD)
    w = (ui.WIDTH - 2 * ui.PAD - ui.GAP) // 2
    for i, (label, value, color) in enumerate((("OR ACTUEL", gold, ui.GOLD),
                                              ("OR AMASSÉ DEPUIS LE DÉBUT", career, ui.REGEN))):
        x = ui.PAD + i * (w + ui.GAP)
        ui.tinted_card(img, (x, top), (w, 190), color)
        ui.shadow_text(draw, (x + 22, top + 24), label, try_font(16, bold=True), fill=(*color, 255))
        text = format_int(value)
        font = ui.fit(draw, text, 60, w - 130)
        ui.shadow_text(draw, (x + 22, top + 60), text, font)
        tw = draw.textlength(text, font=font)
        draw_text_with_emojis(img, (int(x + 32 + tw), top + 80), "💰", try_font(24), fill=ui.TEXT, emoji_size=30)
    ui.footer(img, top + 190 + ui.GAP, "🛒 Sorn (/marchand), Borak (/forgeron), Elna (/alchimiste) et la /brocante attendent ton or.",
              color=ui.GOLD)
    ui.save(img, output_path)


# ------------------------------------------------------------------ classement --
def compose_leaderboard(output_path: str, *, title: str, entries: list[tuple[str, str]], viewer_rank: int | None,
                        viewer: tuple[str, str] | None, total: int, seed: int = 0) -> None:
    """`entries` : (nom, valeur affichée) du 1er au 10e ; `viewer` : la ligne
    du joueur s'il est classé plus bas."""
    podium = entries[:3]
    rest = entries[3:]
    extra = 1 if viewer and viewer_rank and viewer_rank > len(entries) else 0
    height = ui.PAD + 88 + (250 if podium else 120) + ui.GAP + (len(rest) + extra) * 66 + ui.GAP + 56 + ui.PAD
    img = ui.canvas(height, seed)
    draw = ImageDraw.Draw(img)
    place = "" if viewer_rank is None else (" · ta place : 1ʳᵉ" if viewer_rank == 1 else f" · ta place : {viewer_rank}ᵉ")
    top = ui.header(img, f"🏆 {title}", f"{total} joueur{'s' if total > 1 else ''} classé{'s' if total > 1 else ''}{place}",
                    accent=ui.GOLD)
    w = ui.WIDTH - 2 * ui.PAD
    if not entries:
        ui.panel(img, (ui.PAD, top), (w, 120), radius=16, fill=(28, 24, 40, 205), outline=(*ui.LILAC, 90))
        ui.shadow_text(draw, (ui.PAD + 24, top + 46), "Personne n'est encore classé : à toi de prendre la tête !",
                       try_font(18), fill=ui.MUTED)
        y = top + 120 + ui.GAP
    else:
        medals = (("🥇", (240, 196, 92), 250), ("🥈", (200, 206, 220), 220), ("🥉", (214, 140, 90), 200))
        order = [1, 0, 2]                       # 2e, 1er, 3e : le premier au centre, plus haut
        cw = (w - 2 * ui.GAP) // 3
        for slot, idx in enumerate(order):
            if idx >= len(podium):
                continue
            medal, color, h = medals[idx]
            x = ui.PAD + slot * (cw + ui.GAP)
            cy = top + (250 - h)
            ui.tinted_card(img, (x, cy), (cw, h), color)
            if viewer_rank == idx + 1:                  # c'est toi
                ui.panel(img, (x, cy), (cw, h), radius=16, fill=(0, 0, 0, 0), outline=(*ui.GOLD, 255), width=3)
            draw_text_with_emojis(img, (x + cw // 2 - 20, cy + 16), medal, try_font(30), fill=ui.TEXT, emoji_size=40)
            name, value = podium[idx]
            # Le nom en GRAND (demande de l'auteur, 21/11/2026 : on le voyait mal).
            f_n = ui.fit(draw, name, 36 if idx == 0 else 32, cw - 24, floor=16)
            nw = draw.textlength(name, font=f_n)
            ui.shadow_text(draw, (x + (cw - nw) / 2, cy + 70), name, f_n)
            f_v = ui.fit(draw, value, 26, cw - 30)
            vw = draw.textlength(value, font=f_v)
            ui.shadow_text(draw, (x + (cw - vw) / 2, cy + 70 + f_n.size + 14), value, f_v, fill=(*color, 255))
        y = top + 250 + ui.GAP
        rows = [(i + 4, n, v, i + 4 == viewer_rank) for i, (n, v) in enumerate(rest)]
        if extra:
            rows.append((viewer_rank, viewer[0], viewer[1], True))
        ladder = (ui.ATK, ui.REGEN, ui.TIME, ui.DEF, ui.ITEM, ui.PINK, ui.EARTH)   # jamais l'or : c'est ta ligne
        for rank, name, value, me in rows:
            color = ui.GOLD if me else ladder[(rank - 4) % len(ladder)]
            ui.panel(img, (ui.PAD, y), (w, 56), radius=14,
                     fill=(92, 70, 20, 200) if me else (*[int(c * 0.14) + 18 for c in color], 225),
                     outline=(*color, 200 if me else 130))
            ui.panel(img, (ui.PAD + 8, y + 12), (5, 32), radius=3, fill=(*color, 255))
            ui.shadow_text(draw, (ui.PAD + 22, y + 14), f"#{rank}", try_font(22, bold=True),
                           fill=(*ui.lighten(color, 0.2), 255))
            f_v = try_font(22, bold=True)
            vw = draw.textlength(value, font=f_v)
            f_name = ui.fit(draw, name, 26, w - 150 - vw, floor=18)
            ui.shadow_text(draw, (ui.PAD + 90, y + 13 + (26 - f_name.size) // 2),
                           ui.clip(draw, name, f_name, w - 150 - vw), f_name,
                           fill=(*ui.GOLD, 255) if me else ui.TEXT)
            ui.shadow_text(draw, (ui.PAD + w - 20 - vw, y + 14), value, f_v, fill=(*ui.lighten(color, 0.3), 255))
            y += 66
        y += ui.GAP - 8
    ui.footer(img, y, "📊 /classement pour choisir une autre catégorie : niveau, puissance, or, tour, défis, chasse…",
              color=ui.GOLD)
    ui.save(img, output_path)


# --------------------------------------------------------------- essai de défi --
def compose_attempt(output_path: str, *, role: str, label: str, variant: str, score: str, unit: str,
                    detail: str, improved: bool, best: str, place: str, gold: str = "", seed: int = 0) -> None:
    color = ROLE_COLORS.get(role, ui.LILAC)
    height = ui.PAD + 88 + 230 + ui.GAP + 56 + ui.PAD
    img = ui.canvas(height, seed)
    draw = ImageDraw.Draw(img)
    top = ui.header(img, f"{label} — {variant}", "Défi du jour", accent=color)
    w = ui.WIDTH - 2 * ui.PAD
    ui.tinted_card(img, (ui.PAD, top), (w, 230), ui.GOLD if improved else color)
    ui.shadow_text(draw, (ui.PAD + 24, top + 24), "TON SCORE", try_font(16, bold=True), fill=(*ui.lighten(color, 0.2), 255))
    f_score = ui.fit(draw, score, 72, w / 2)
    ui.shadow_text(draw, (ui.PAD + 24, top + 54), score, f_score)
    sw = draw.textlength(score, font=f_score)
    ui.shadow_text(draw, (ui.PAD + 40 + sw, top + 84), unit, try_font(22, bold=True), fill=(*ui.lighten(color, 0.2), 255))
    ui.shadow_text(draw, (ui.PAD + 24, top + 140), ui.clip(draw, detail, try_font(17), w - 48), try_font(17), fill=ui.MUTED)
    x = ui.PAD + 24
    f_chip = try_font(15, bold=True)
    if improved:
        x += ui.gold_chip(img, x, top + 178, "✨ Nouveau record du jour !", f_chip) + 10
    else:
        x += ui.chip(img, x, top + 178, f"Ton record du jour : {best}", f_chip) + 10
    x += ui.chip(img, x, top + 178, place, f_chip, fill=(24, 40, 46, 225), outline=(*ui.TIME, 170),
                 ink=(*ui.lighten(ui.TIME, 0.2), 255)) + 10
    if gold:
        ui.gold_chip(img, x, top + 178, gold, f_chip)
    ui.footer(img, top + 230 + ui.GAP, "🔁 Même build, même score : change d'équipement, d'arbre, de points ou de /tactique.",
              color=color)
    ui.save(img, output_path)


def plain(text: str) -> str:
    """Le texte Discord sans sa mise en forme (gras, italique, code) : l'image
    l'écrit tel quel."""
    import re

    text = re.sub(r"<[@#][!&]?\d+>", "", text or "")
    return re.sub(r"[*_`]", "", text).replace("  ", " ").strip()
