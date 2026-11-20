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

TIER_COLORS = {"easy": (120, 220, 140), "medium": (240, 196, 92), "hard": (235, 90, 100)}
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
    height = ui.PAD + 120 + n * card_h + (n - 1) * ui.GAP + ui.GAP + 56 + ui.PAD
    img = ui.canvas(height, seed)
    draw = ImageDraw.Draw(img)
    top = ui.header(img, title, subtitle)
    done = sum(1 for q in quests if q.claimed)
    f_chip = try_font(16, bold=True)
    x = ui.PAD + ui.chip(img, ui.PAD, top, f"📋 {done}/{len(quests)} réclamée{'s' if done > 1 else ''}", f_chip) + 10
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
                       fill=ui.TEXT if not q.claimed else ui.DIM)
        # Récompenses
        rewards = f"💰 {format_int(q.gold)} or   ✨ {format_int(q.xp)} XP" + (f"   🎁 {q.items}" if q.items else "")
        f_rew = try_font(15, bold=True)
        rewards = ui.clip(draw, rewards, f_rew, w - 40)
        draw_text_with_emojis(img, (ui.PAD + 20, y + 112), rewards, f_rew, fill=ui.DIM if q.claimed else ui.MUTED,
                              emoji_size=16)
        y += card_h + ui.GAP

    note = ("🎁 Clique sur « Réclamer » sous l'image pour toucher tes récompenses."
            if to_claim else "⏳ Les quêtes avancent toutes seules en jouant : combats, tour, défis.")
    ui.footer(img, y, note)
    ui.save(img, output_path)


# --------------------------------------------------------------- solde du jour --
STREAK_STEPS = ((7, "Habitué"), (30, "Taverne Addict"), (100, "Pilier"))


def compose_daily(output_path: str, *, name: str, streak: int, gold: int, bonus_pct: int,
                  days_missed: int = 0, streak_before: int = 0, guard_used: bool = False,
                  titles: list[str] | None = None, bonus_items: list[tuple[str, int]] | None = None,
                  seed: int = 0) -> None:
    notes: list[str] = []
    if guard_used:
        notes.append("⏳ Ton sablier de fidélité s'est brisé : un jour manqué t'est pardonné.")
    if days_missed:
        notes.append(f"💔 {days_missed} jour{'s' if days_missed > 1 else ''} manqué{'s' if days_missed > 1 else ''} : "
                     f"ta série de {streak_before} a été divisée par deux par jour d'absence.")
    for title in titles or []:
        notes.append(f"🏷️ Nouveau titre : {title}")
    for item, qty in bonus_items or []:
        notes.append(f"🎁 Bonus de titre : {qty}× {item}")
    height = ui.PAD + 80 + 200 + ui.GAP + 120 + len(notes) * 30 + ui.GAP + 56 + ui.PAD
    img = ui.canvas(height, seed)
    draw = ImageDraw.Draw(img)
    top = ui.header(img, "🌅 Solde du jour", f"La guilde paie {name}")

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
    flame = (255, 130, 60)
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
    ui.panel(img, (ui.PAD, y), (ui.WIDTH - 2 * ui.PAD, 120), radius=16, fill=(28, 24, 40, 205),
             outline=(*ui.LILAC, 90))
    ui.shadow_text(draw, (ui.PAD + 20, y + 14), "PALIERS DE LA SÉRIE · un titre à chacun", try_font(13, bold=True),
                   fill=ui.DIM)
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
    for note in notes:
        draw_text_with_emojis(img, (ui.PAD + 4, y), ui.clip(draw, note, try_font(16), ui.WIDTH - 2 * ui.PAD),
                              try_font(16), fill=ui.MUTED, emoji_size=17)
        y += 30
    if notes:
        y += 4
    ui.footer(img, y, "📋 Ta routine du jour : /quetes · /tour · /defi. Un jour manqué divise la série par deux.")
    ui.save(img, output_path)


# --------------------------------------------------------------------- défis --
ROLE_COLORS = {"dps": (255, 120, 80), "tank": (90, 160, 230), "soutien": (120, 220, 140)}


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
    height = ui.PAD + 120 + card_h + ui.GAP + (64 if week else 0) + 56 + ui.PAD
    img = ui.canvas(height, seed)
    draw = ImageDraw.Draw(img)
    top = ui.header(img, title, subtitle)
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
        ui.panel(img, (ui.PAD, y), (ui.WIDTH - 2 * ui.PAD, 48), radius=14, fill=(28, 24, 40, 205),
                 outline=(*ui.LILAC, 90))
        draw_text_with_emojis(img, (ui.PAD + 20, y + 14), ui.clip(draw, f"📅 Ta semaine : {week}", try_font(16),
                                                                  ui.WIDTH - 2 * ui.PAD - 40),
                              try_font(16), fill=ui.MUTED, emoji_size=17)
        y += 48 + ui.GAP
    ui.footer(img, y, "🎯 /defi role: pour tenter · même build = même score · potions et élixirs interdits")
    ui.save(img, output_path)


# ---------------------------------------------------------- temps de recharge --
@dataclass(frozen=True)
class Timer:
    label: str              # « 🌅 Récompense quotidienne »
    ready: str              # « prêt à 21:05 · dans 3 h 12 »
    ratio: float = 0.0      # part déjà écoulée (0 → 1), pour la barre


def compose_cooldowns(output_path: str, *, name: str, timers: list[Timer], tickets: str, extras: list[str],
                      seed: int = 0) -> None:
    row_h = 70
    rows = max(1, len(timers))
    height = ui.PAD + 90 + rows * (row_h + 10) + ui.GAP + len(extras) * 30 + 56 + 56 + ui.PAD
    img = ui.canvas(height, seed)
    draw = ImageDraw.Draw(img)
    y = ui.header(img, f"⏳ Temps de recharge de {name}", "Ce qui attend, et quand ce sera prêt") + 6
    w = ui.WIDTH - 2 * ui.PAD
    if not timers:
        ui.panel(img, (ui.PAD, y), (w, row_h), radius=14, fill=(30, 46, 38, 215), outline=(*ui.GREEN, 140))
        draw_text_with_emojis(img, (ui.PAD + 20, y + 24), "✅ Rien ne recharge : tout est disponible !",
                              try_font(19, bold=True), fill=(*ui.GREEN, 255), emoji_size=20)
        y += row_h + 10
    for timer in timers:
        ui.panel(img, (ui.PAD, y), (w, row_h), radius=14, fill=(28, 24, 40, 210), outline=(*ui.LILAC, 90))
        f_label = try_font(18, bold=True)
        draw_text_with_emojis(img, (ui.PAD + 20, y + 12), ui.clip(draw, timer.label, f_label, w / 2), f_label,
                              fill=ui.TEXT, emoji_size=18)
        f_ready = try_font(16, bold=True)
        rw = measure_text_with_emojis(timer.ready, f_ready, 16)
        draw_text_with_emojis(img, (int(ui.PAD + w - 20 - rw), y + 13), timer.ready, f_ready,
                              fill=(*ui.GOLD, 255), emoji_size=16)
        ui.bar(img, (ui.PAD + 20, y + 46), (w - 40, 8), timer.ratio, (110, 190, 255), glow=True)
        y += row_h + 10
    y += ui.GAP - 10
    ui.panel(img, (ui.PAD, y), (w, 48), radius=14, fill=(28, 24, 40, 205), outline=(*ui.LILAC, 90))
    draw_text_with_emojis(img, (ui.PAD + 20, y + 14), ui.clip(draw, tickets, try_font(16), w - 40), try_font(16),
                          fill=ui.MUTED, emoji_size=17)
    y += 48 + 8
    for extra in extras:
        draw_text_with_emojis(img, (ui.PAD + 4, y), ui.clip(draw, extra, try_font(16), w), try_font(16),
                              fill=ui.MUTED, emoji_size=17)
        y += 30
    ui.footer(img, y + 4, "🔔 La case Confort « notifications » de l'arbre te prévient quand c'est prêt.")
    ui.save(img, output_path)


# ---------------------------------------------------------------- inventaire --
@dataclass(frozen=True)
class Slot:
    code: str
    name: str
    quantity: int


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
    height = ui.PAD + 120 + rows * (tile_h + 12) + ui.GAP + 56 + ui.PAD
    img = ui.canvas(height, seed)
    draw = ImageDraw.Draw(img)
    total = sum(s.quantity for s in slots)
    top = ui.header(img, f"🎒 Inventaire de {name}", page_label)
    ui.chip(img, ui.PAD, top, f"{len(slots)} objet{'s' if len(slots) > 1 else ''} · {format_int(total)} en tout",
            try_font(15, bold=True))
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
        ui.panel(img, (x, ty), (tile_w, tile_h), radius=14, fill=(28, 24, 40, 215), outline=(*ui.LILAC, 80))
        icon = _icon(slot.code, 72)
        if icon is not None:
            img.alpha_composite(icon, (x + 14 + (72 - icon.width) // 2, ty + 14 + (72 - icon.height) // 2))
        else:
            ui.panel(img, (x + 14, ty + 14), (72, 72), radius=12, fill=(44, 38, 62, 220))
            draw_text_with_emojis(img, (x + 34, ty + 34), "📦", try_font(28), fill=ui.TEXT, emoji_size=32)
        qty = f"×{format_int(slot.quantity)}"
        f_qty = ui.fit(draw, qty, 26, tile_w - 104)
        ui.shadow_text(draw, (x + 96, ty + 34), qty, f_qty, fill=(*ui.GOLD, 255))
        for j, line in enumerate(ui.wrap(draw, slot.name, try_font(14, bold=True), tile_w - 24, 2)):
            ui.shadow_text(draw, (x + 12, ty + 92 + j * 17), line, try_font(14, bold=True))
    y += rows * (tile_h + 12) - 12 + ui.GAP
    more = len(slots) - len(shown)
    note = (f"… et {more} autre{'s' if more > 1 else ''} objet{'s' if more > 1 else ''}."
            if more else "🧪 Les potions se boivent avec /utiliser · ⚔️ l'équipement est dans /equipement_liste.")
    ui.footer(img, y, note)
    ui.save(img, output_path)
