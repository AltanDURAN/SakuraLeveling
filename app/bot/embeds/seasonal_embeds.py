"""Textes des événements saisonniers (décembre 2026) : le panneau épinglé du
salon des événements, les écrans privés (Avent, cadeau de Noël, boutique)
et les annonces (ouverture de l'Avent, sucres d'orge, matin de Noël,
boutique, Nouvel An).

⚠️ SECRET (décision de l'auteur, 10/11/2026) : aucun texte ne dit aux joueurs
que la taille du cadeau de Noël vient de leurs choix face à la PETITE FILLE —
ils l'aideraient pour ça. Avant Noël, rien ne laisse entendre que le cadeau
dépend de quoi que ce soit ; à l'ouverture, un simple verdict (« tu as été
sage »), jamais sa cause. Test : `test_seasonal_bot.py`.
"""

from __future__ import annotations

from datetime import timedelta

import discord

from app.domain.services import seasonal_service as ss
from app.shared.formatters import format_date_fr, format_int

#: Pied de page du panneau épinglé : c'est à lui qu'on le reconnaît.
PANEL_FOOTER = "Sakura · événements de saison"
COLOR = discord.Color.from_rgb(196, 40, 56)
GREEN = discord.Color.from_rgb(36, 128, 72)
GOLD = discord.Color.from_rgb(232, 186, 82)

#: Verdict du Père Noël à l'ouverture du cadeau — jamais sa cause (secret).
VERDICTS = {
    ss.ANGEL: "👼 Le Père Noël a un faible pour toi cette année : ton cadeau déborde !",
    ss.NICE: "😇 Tu as été sage cette année : voici ton cadeau.",
    ss.UNKNOWN: "🎄 Le Père Noël n'oublie personne : voici ton cadeau.",
    ss.NAUGHTY: "😈 Le Père Noël a hésité… ton cadeau est un peu maigre cette année.",
}


def _day(d) -> str:
    return format_date_fr(d).rsplit(" ", 1)[0]          # « 25 décembre »


def _lines(granted) -> str:
    return "\n".join(f"{g.emoji} {g.text}" for g in granted) or "—"


def verdict(k: ss.Kindness) -> str:
    return VERDICTS.get(k.tier, VERDICTS[ss.NICE])


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
        lines.append(f"🎅 **{content.christmas.name}** — le Père Noël est passé : ton cadeau t'attend jusqu'au "
                     f"{_day(content.christmas.claim_until)}.")
    for shop in h.shops:
        lines.append(f"{shop.emoji} **{shop.name}** — ouvert jusqu'au {_day(shop.closes)}.")
    if not lines:
        lines.append("Pas d'événement en ce moment : on vous prévient ici dès le prochain !")
    embed = discord.Embed(title="🎉 Les fêtes du Grand Cerisier", description="\n\n".join(lines), color=COLOR)
    if h.upcoming:
        embed.add_field(name="📅 À venir",
                        value="\n".join(f"• {label} — {format_date_fr(d)}" for d, label in h.upcoming[:6]),
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
    """L'écran du cadeau. Rien sur ce qui en fixe la taille (secret)."""
    c = status.christmas
    embed = discord.Embed(title=f"🎅 {c.name}", color=GREEN)
    if granted:
        embed.description = f"{verdict(status.kindness)}\n\n🎁 Tu reçois :\n{_lines(granted)}"
    elif status.claimed:
        embed.description = "✅ Tu as déjà ouvert ton cadeau. Joyeux Noël !"
    elif status.open:
        embed.description = (f"Le Père Noël est passé ! Ton cadeau t'attend jusqu'au "
                             f"**{format_date_fr(c.claim_until)}**.")
    elif ss.paris_day() < c.gift_day:
        eve = c.gift_day - timedelta(days=1)
        embed.description = (f"Le Père Noël passera dans la nuit du **{_day(eve)}** au **{_day(c.gift_day)}** : "
                             f"un cadeau pour chacun, à ouvrir jusqu'au {_day(c.claim_until)}.")
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
            f"de Noël**, jusqu'au {_day(christmas.claim_until)}.")
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
    local = end.astimezone(ss.PARIS)
    until = "minuit" if (local.hour, local.minute) == (0, 0) else f"<t:{int(end.timestamp())}:t>"
    blessings = "\n".join(f"{d.emoji} **{d.name}** — {d.blessing}" for d in deities)
    embed = discord.Embed(
        title=f"🎆 {new_year.title}",
        description=(f"{new_year.message}\n\n{blessings}\n\n"
                     f"Jusqu'à {until}, toutes ces bénédictions s'additionnent. "
                     "Belle année à toutes et à tous, et bonne chasse !"),
        color=GOLD)
    embed.set_footer(text=PANEL_FOOTER)
    return embed
