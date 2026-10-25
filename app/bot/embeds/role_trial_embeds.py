"""Embeds des défis de rôle (`/defi`) : programme du jour, essai, résultats."""

from __future__ import annotations

from datetime import date

import discord
from discord.utils import escape_markdown

from app.domain.services import role_trial_service as rts
from app.shared.formatters import format_int

_MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
_DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
           "septembre", "octobre", "novembre", "décembre")
_UNITS = {"dps": "dégâts infligés", "tank": "dégâts encaissés", "soutien": "PV soignés"}

RULES = ("Essais illimités, mais **même build = même score** : change d'équipement, "
         "d'arbre, de points ou de /tactique pour faire mieux. Le meilleur score du "
         "jour est gardé ; la semaine compte tes 5 meilleurs jours. "
         f"Résultats le dimanche à {rts.RESULTS_HOUR} h.")


def _day_label(day: date) -> str:
    return f"{_DAYS[day.weekday()]} {day.day} {_MONTHS[day.month - 1]}"


def _place(place: int) -> str:
    return "1er" if place == 1 else f"{place}e"


def build_day_embed(day: date, mine: dict | None = None, week: dict | None = None) -> discord.Embed:
    """Programme du jour ; avec `mine` ({rôle: (score, essais, place, total)})
    et `week` ({clé: (place, score) | None}), les scores du joueur."""
    embed = discord.Embed(
        title=f"🎯 Défis du jour — {_day_label(day)}",
        description="Trois épreuves, une par rôle : `/defi role:` pour tenter ta chance.",
        color=discord.Color.teal(),
    )
    for role in rts.ROLES:
        variant = rts.variant_of_day(day, role)
        value = variant.description
        if mine is not None:
            entry = mine.get(role)
            if entry:
                score, attempts, place, total = entry
                value += (f"\n**Ton meilleur : {format_int(score)}** "
                          f"({attempts} essai{'s' if attempts > 1 else ''}) · "
                          f"{_place(place)} sur {total}")
            else:
                value += "\n_Pas encore tenté aujourd'hui._"
        embed.add_field(name=f"{rts.ROLE_LABELS[role]} — {variant.name}", value=value, inline=False)
    if week is not None:
        parts = []
        for key, label in [*rts.ROLE_LABELS.items(), (rts.GENERAL, rts.GENERAL_LABEL)]:
            entry = week.get(key)
            score = "—" if entry is None else (
                f"{_place(entry[0])} ({format_int(round(entry[1]))})")
            parts.append(f"{label} {score}")
        embed.add_field(name="Ta semaine", value=" · ".join(parts), inline=False)
    embed.set_footer(text=RULES.replace("**", ""))
    return embed


def build_attempt_embed(outcome) -> discord.Embed:
    role, variant = outcome.role, outcome.variant
    if role == "dps":
        detail = f"en {rts.DPS_TICKS // 10} secondes"
    elif role == "tank":
        detail = f"en {outcome.actions} action{'s' if outcome.actions > 1 else ''} avant de tomber"
    else:
        detail = ("avant la chute de la recrue" if not outcome.survived
                  else "— la recrue tient encore debout !")
    lines = [f"**{format_int(outcome.score)}** {_UNITS[role]} {detail}."]
    if outcome.improved:
        lines.append("✨ **Nouveau record du jour !**")
    else:
        lines.append(f"Ton record du jour reste **{format_int(outcome.best)}**.")
    lines.append(f"Place du jour : **{_place(outcome.day_rank)}** sur {outcome.day_count} · "
                 f"essai n°{outcome.attempts}")
    embed = discord.Embed(
        title=f"{rts.ROLE_LABELS[role]} — {variant.name}",
        description="\n".join(lines),
        color=discord.Color.gold() if outcome.improved else discord.Color.blurple(),
    )
    embed.set_footer(text="Même build, même score : change d'équipement, d'arbre, de points "
                          "ou de /tactique pour faire mieux.")
    return embed


def build_results_embed(week: date, results: dict) -> discord.Embed:
    """Annonce du dimanche : podium de chaque classement, or et titres."""
    from app.infrastructure.titles.title_loader import get_definition

    embed = discord.Embed(
        title="🏆 Résultats des défis de la semaine",
        description=(f"Semaine du {_day_label(week)} — les 5 meilleurs jours de chacun. "
                     "Le premier de chaque classement porte le titre de la semaine."),
        color=discord.Color.gold(),
    )
    for key, label in [*rts.ROLE_LABELS.items(), (rts.GENERAL, rts.GENERAL_LABEL)]:
        podium = results.get(key) or []
        title = get_definition(rts.WEEKLY_TITLES[key])
        if not podium:
            value = "_Personne cette semaine._"
        else:
            rows = []
            for place, entry in enumerate(podium, start=1):
                score = (f"{entry['score']:.1f}".replace(".", ",") + " / 100" if key == rts.GENERAL
                         else format_int(round(entry["score"])))
                rows.append(f"{_MEDALS.get(place, place)} <@{entry['discord_id']}> "
                            f"({escape_markdown(entry['name'])}) — {score} · "
                            f"+{format_int(entry['gold'])} or")
            value = "\n".join(rows)
            if title is not None:
                value += f"\n{title.icon} Titre : **{title.name}**"
        embed.add_field(name=label, value=value, inline=False)
    embed.set_footer(text="Nouveaux défis à minuit. Le général = moyenne des trois rôles, "
                          "chacun ramené à 100 = le meilleur de la semaine.")
    return embed
