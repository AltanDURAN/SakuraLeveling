"""Textes des événements saisonniers (décembre 2026) : le panneau épinglé du
salon des événements, les écrans privés (Avent, cadeau de Noël, boutique)
et les annonces (ouverture de l'Avent, sucres d'orge, matin de Noël,
boutique, Nouvel An)."""

from __future__ import annotations

import discord

from app.domain.services import seasonal_service as ss
from app.shared.formatters import format_date_fr, format_int

#: Pied de page du panneau épinglé : c'est à lui qu'on le reconnaît.
PANEL_FOOTER = "Sakura · événements de saison"
COLOR = discord.Color.from_rgb(196, 40, 56)
GREEN = discord.Color.from_rgb(36, 128, 72)
GOLD = discord.Color.from_rgb(232, 186, 82)

KINDNESS_LABELS = {
    ss.UNKNOWN: "🤷 Le Père Noël ne t'a pas encore vu à l'œuvre",
    ss.NAUGHTY: "😈 Pas très sage…",
    ss.NICE: "😇 Sage",
    ss.ANGEL: "👼 Un cœur d'or",
}


def _day(d) -> str:
    return format_date_fr(d).rsplit(" ", 1)[0]          # « 25 décembre »


def _lines(granted) -> str:
    return "\n".join(f"{g.emoji} {g.text}" for g in granted) or "—"


def kindness_text(k: ss.Kindness) -> str:
    label = KINDNESS_LABELS.get(k.tier, k.tier)
    if not k.total:
        detail = "tu n'as encore jamais croisé la petite fille"
    else:
        detail = (f"{k.helps} aide{'s' if k.helps > 1 else ''}, {k.ignores} refus "
                  f"({round(100 * (k.ratio or 0))} % d'aide)")
    return f"{label} — {detail} → **cadeau à {k.pct} %**"


# --------------------------------------------------------------- panneau
def build_panel_embed(content: ss.SeasonalContent, now_happening: ss.Happening) -> discord.Embed:
    """Le panneau épinglé du salon des événements : ce qui se passe, ce qui
    vient. Les boutons ouvrent l'écran de chacun, en privé."""
    h = now_happening
    lines = []
    if h.new_year and content.new_year is not None:
        end = content.new_year.window()[1]
        lines.append(f"🎆 **{content.new_year.title}** Toutes les divinités bénissent le serveur jusqu'à "
                     f"<t:{int(end.timestamp())}:t> (voir `/offrande`).")
    if h.advent_day and content.advent is not None:
        lines.append(f"🎄 **{content.advent.name}** — case **{h.advent_day}** / {content.advent.size} à ouvrir "
                     "aujourd'hui (une case par jour, le jour même).")
    for drop in h.drops:
        lines.append(f"🍬 **{drop.name}** — chaque monstre vaincu en zone donne {drop.per_kill} × objet "
                     f"d'événement, jusqu'au {_day(drop.end)} au soir.")
    if h.christmas_open and content.christmas is not None:
        lines.append(f"🎅 **{content.christmas.name}** — ton cadeau t'attend jusqu'au "
                     f"{_day(content.christmas.claim_until)} : plus tu as aidé la petite fille, plus il est gros.")
    for shop in h.shops:
        lines.append(f"{shop.emoji} **{shop.name}** — ouvert jusqu'au {_day(shop.closes)}.")
    if not lines:
        lines.append("Pas d'événement en ce moment : on vous prévient ici dès le prochain !")
    embed = discord.Embed(title="🎉 Les fêtes du Grand Cerisier", description="\n\n".join(lines), color=COLOR)
    if h.upcoming:
        embed.add_field(name="📅 À venir",
                        value="\n".join(f"• {label} — {format_date_fr(d)}" for d, label in h.upcoming[:6]),
                        inline=False)
    if content.christmas is not None and content.christmas.enabled and not h.christmas_open \
            and any(label.startswith("🎅") for _, label in h.upcoming):
        embed.add_field(name="🎅 Sois sage…",
                        value=("Le Père Noël compte chaque fois que tu **aides** (ou ignores) la petite fille : "
                               "moins de la moitié du temps, ton cadeau sera réduit de moitié ; toujours aidée, "
                               "il sera une fois et demie plus gros. Le bouton « Mon cadeau » te dit où tu en es."),
                        inline=False)
    embed.set_footer(text=PANEL_FOOTER)
    return embed


# ---------------------------------------------------------------- l'Avent
def build_advent_embed(status, player_name: str, granted=None) -> discord.Embed:
    advent = status.advent
    day = status.today_day
    embed = discord.Embed(title=f"🎄 {advent.name}", color=COLOR)
    if granted:
        embed.description = f"Case **{day}** ouverte ! Tu reçois :\n{_lines(granted)}\n\nÀ demain pour la suivante !"
    elif day is None:
        if ss.paris_day() < advent.start:
            embed.description = f"Le calendrier s'ouvre le **{format_date_fr(advent.start)}**."
        else:
            embed.description = "Le calendrier est terminé — rendez-vous à Noël !"
    elif day in status.opened:
        embed.description = (f"✅ Tu as ouvert la case **{day}** aujourd'hui :\n{_lines(status.lines(day))}\n\n"
                             "Reviens demain pour la suivante.")
    else:
        embed.description = (f"Aujourd'hui, la case **{day}** t'attend. On n'ouvre que la case du jour : "
                             "une case pas ouverte le jour même est perdue.")
    embed.set_image(url="attachment://avent.png")
    embed.set_footer(text=f"{player_name} · {len(status.opened)} / {advent.size} cases ouvertes")
    return embed


# ------------------------------------------------------------------ Noël
def build_christmas_embed(status, granted=None) -> discord.Embed:
    c = status.christmas
    embed = discord.Embed(title=f"🎅 {c.name}", color=GREEN)
    embed.add_field(name="Ta gentillesse", value=kindness_text(status.kindness), inline=False)
    rules = c.kindness
    embed.add_field(name="Comment le Père Noël décide", value=(
        f"Il regarde tes choix face à la **petite fille** jusqu'au réveillon :\n"
        f"• moins de {rules.nice_from_pct} % d'aide → {rules.naughty_pct} % du cadeau\n"
        f"• au moins {rules.nice_from_pct} % → {rules.nice_pct} %\n"
        f"• toujours aidée → **{rules.angel_pct} %**\n"
        f"• jamais croisée → {rules.unknown_pct} %"), inline=False)
    if granted:
        embed.description = f"🎁 Tu ouvres ton cadeau… et tu reçois :\n{_lines(granted)}"
    elif status.claimed:
        embed.description = "✅ Tu as déjà ouvert ton cadeau. Joyeux Noël !"
    elif status.open:
        embed.description = (f"Le Père Noël est passé ! Ton cadeau t'attend jusqu'au "
                             f"**{format_date_fr(c.claim_until)}**.")
    elif ss.paris_day() < c.gift_day:
        embed.description = (f"Les cadeaux s'ouvrent le **{format_date_fr(c.gift_day)}**. D'ici là, sois sage : "
                             "aide la petite fille quand elle passe !")
    else:
        embed.description = "Le Père Noël est reparti. À l'année prochaine !"
    return embed


# --------------------------------------------------------------- boutique
def build_shop_embed(status, message: str = "") -> discord.Embed:
    shop = status.shop
    currency = status.currency_name
    embed = discord.Embed(title=shop.label, color=GOLD)
    lines = [shop.intro] if shop.intro else []
    if not status.open:
        lines.append(f"🔒 Ouvert du **{format_date_fr(shop.opens)}** au **{format_date_fr(shop.closes)}**.")
    lines.append(f"Tu as **{format_int(status.balance)}** × {currency}.")
    if message:
        lines.append(message)
    embed.description = "\n\n".join(lines)
    rows = []
    for offer in shop.offers:
        bought = status.bought.get(offer.item, 0)
        limit = f" · {bought}/{offer.limit}" if offer.limit else ""
        done = " ✅" if offer.limit and bought >= offer.limit else ""
        rows.append(f"**{status.names.get(offer.item, offer.item)}** — {format_int(offer.price)}{limit}{done}")
    embed.add_field(name=f"Articles (prix en {currency})", value="\n".join(rows)[:1024] or "—", inline=False)
    embed.set_footer(text=f"Jusqu'au {format_date_fr(shop.closes)} · limite par joueur indiquée après le prix")
    return embed


# ---------------------------------------------------------------- annonces
def build_advent_announcement(advent: ss.Advent) -> discord.Embed:
    embed = discord.Embed(
        title=f"🎄 Le {advent.name.lower()} est ouvert !",
        description=(f"Du **{_day(advent.start)}** au **{_day(advent.end)}**, une case par jour : une petite "
                     "surprise pour bien commencer l'aventure. On n'ouvre que la case du jour — ne la "
                     "laisse pas passer !\n\nBouton **Calendrier de l'Avent** ci-dessous, ou `/evenement`."),
        color=COLOR)
    embed.set_footer(text=PANEL_FOOTER)
    return embed


def build_drop_announcement(drop: ss.EventDrop, item_name: str) -> discord.Embed:
    text = drop.announce or (f"Jusqu'au {_day(drop.end)} au soir, chaque monstre vaincu en zone donne "
                             f"{drop.per_kill} × {item_name} à chaque survivant.")
    embed = discord.Embed(title=f"🍬 {drop.name} !", description=text, color=COLOR)
    embed.set_footer(text=PANEL_FOOTER)
    return embed


def build_christmas_announcement(christmas: ss.Christmas, shops) -> discord.Embed:
    text = ("Le Père Noël est passé au pied du Grand Cerisier ! Ouvre ton cadeau avec le bouton **Mon cadeau "
            f"de Noël** (jusqu'au {_day(christmas.claim_until)}) : plus tu as aidé la petite fille, plus il est "
            "gros.")
    for shop in shops:
        text += (f"\n\n{shop.emoji} **{shop.name}** ouvre ses portes jusqu'au {_day(shop.closes)}"
                 + (f" — {shop.intro}" if shop.intro else "."))
    embed = discord.Embed(title="🎅 Joyeux Noël !", description=text, color=GREEN)
    embed.set_footer(text=PANEL_FOOTER)
    return embed


def build_shop_announcement(shop: ss.EventShop) -> discord.Embed:
    embed = discord.Embed(
        title=f"{shop.label} ouvre !",
        description=(shop.intro + "\n\n" if shop.intro else "") + f"Jusqu'au {_day(shop.closes)} — bouton "
                    "**Boutique** ci-dessous, ou `/evenement`.",
        color=GOLD)
    embed.set_footer(text=PANEL_FOOTER)
    return embed


def build_new_year_announcement(new_year: ss.NewYear, deities) -> discord.Embed:
    end = new_year.window()[1]
    blessings = "\n".join(f"{d.emoji} **{d.name}** — {d.blessing}" for d in deities)
    embed = discord.Embed(
        title=f"🎆 {new_year.title}",
        description=(f"{new_year.message}\n\n{blessings}\n\n"
                     f"Jusqu'à <t:{int(end.timestamp())}:t>, toutes ces bénédictions s'additionnent. "
                     "Belle année à toutes et à tous, et bonne chasse !"),
        color=GOLD)
    embed.set_footer(text=PANEL_FOOTER)
    return embed
