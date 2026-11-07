"""Embed du règlement : le même partout (salon, /reglement, commande refusée)."""

from __future__ import annotations

from datetime import date

import discord

from app.domain.services.rules_service import Rules
from app.shared.formatters import format_date_fr

COLOR = discord.Color.from_rgb(255, 150, 195)
#: Bandeau du salon du règlement (pièce jointe du panneau).
BANNER = "reglement.png"


def footer_text(rules: Rules) -> str:
    parts = [f"Version {rules.version}"]
    try:
        parts.append(f"mise à jour le {format_date_fr(date.fromisoformat(rules.updated))}")
    except ValueError:
        pass
    if rules.footer:
        parts.append(rules.footer)
    return " · ".join(parts)


def build_rules_embed(rules: Rules, *, banner: bool = False) -> discord.Embed:
    embed = discord.Embed(title=rules.title, description=rules.intro, color=COLOR)
    for section in rules.sections:
        embed.add_field(name=section.heading, value=section.body, inline=False)
    embed.set_footer(text=footer_text(rules))
    if banner:
        embed.set_image(url=f"attachment://{BANNER}")
    return embed
