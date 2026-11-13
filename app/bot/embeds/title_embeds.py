"""`/titre` : un livre à pages qui tient dans les limites de Discord.

Avant (jusqu'au 13/11/2026), tout tenait dans UN message : avec les 83 titres
du jeu (dont 50 « Chasseur légendaire »), la liste des titres à débloquer
dépassait à elle seule les 6 000 caractères d'un embed — la commande plantait
pour presque tous les joueurs (de 2 à 13 titres débloqués), et la liste des
titres débloqués était coupée en silence au-delà de 1 024 caractères.

Les titres sont rangés par sections (débloqués, puis à débloquer par type),
découpées en champs puis en pages : chaque page reste loin des limites, quel
que soit le nombre de titres du jeu.
"""

from __future__ import annotations

from collections.abc import Sequence

import discord

from app.bot.embeds.limits import chunk_lines, clip

#: Budget d'une page (caractères des champs) — la limite de Discord est 6 000.
PAGE_BUDGET = 3200
#: Une valeur de champ (limite de Discord : 1 024).
FIELD_MAX = 1000
#: Une ligne (un titre) : jamais plus, même avec un nom ou un texte très long.
LINE_MAX = 400
#: Champs par page (limite de Discord : 25).
MAX_FIELDS = 6

#: Sections des titres à débloquer : (nom, types de condition), dans l'ordre.
LOCKED_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Progression", ("kills_total", "dodges_total", "daily_streak", "event")),
    ("Chasse par famille", ("kills_family",)),
    ("Titres disputés", ("weekly_role_trial", "kills_record", "records_rank", "world_boss_mvp")),
    ("World boss", ("world_boss_kill",)),
    ("Cartes", ("card_album", "card_brillante")),
    ("Chasseurs légendaires", ("kills_mob",)),
)
OTHER_SECTION = "Autres titres"


def _fields(lines: Sequence[str]) -> list[str]:
    """Des lignes aux valeurs de champ (aucune ne dépasse `FIELD_MAX`)."""
    return chunk_lines([clip(line, LINE_MAX) for line in lines], FIELD_MAX)


def unlocked_line(title, active: bool) -> str:
    marker = " ⭐ _affiché sur ton profil_" if active else ""
    return f"{title.icon} **{title.name}**{marker}\n> {title.description}"


def locked_line(title, label: str) -> str:
    return f"{title.icon} **{title.name}** — {label}"


def locked_sections(locked: Sequence, labels: dict[str, str],
                    closeness: dict[str, float] | None = None) -> list[tuple[str, list[str]]]:
    """Les titres à débloquer, rangés par section. Dans une section, le plus
    PROCHE d'être débloqué vient d'abord (`closeness` : 0 → 1), puis l'ordre
    du contenu."""
    closeness = closeness or {}
    by_type: dict[str, list] = {}
    for title in locked:
        by_type.setdefault(title.condition_type, []).append(title)
    sections: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    for name, types in LOCKED_SECTIONS:
        titles = [t for kind in types for t in by_type.get(kind, [])]
        seen.update(types)
        if titles:
            titles.sort(key=lambda t: -closeness.get(t.code, 0.0))        # tri stable
            sections.append((name, [locked_line(t, labels.get(t.code, "_à découvrir_")) for t in titles]))
    others = [t for kind, titles in by_type.items() if kind not in seen for t in titles]
    if others:
        sections.append((OTHER_SECTION, [locked_line(t, labels.get(t.code, "_à découvrir_")) for t in others]))
    return sections


def build_title_pages(
    display_name: str,
    unlocked: Sequence,
    locked: Sequence,
    labels: dict[str, str],
    *,
    active_code: str | None = None,
    total: int | None = None,
    closeness: dict[str, float] | None = None,
) -> list[discord.Embed]:
    """Les pages de `/titre`. Toujours au moins une page."""
    total = total if total is not None else len(unlocked) + len(locked)
    sections: list[tuple[str, list[str]]] = []
    if unlocked:
        sections.append((f"✅ Débloqués ({len(unlocked)})",
                         [unlocked_line(t, t.code == active_code) for t in unlocked]))
    sections.extend((f"🔒 À débloquer — {name}", lines) for name, lines in locked_sections(locked, labels, closeness))

    header = f"**{len(unlocked)}** débloqué(s) sur **{total}**."
    if unlocked:
        header += "\nChoisis celui qui s'affiche sur ton profil avec `/titre_actif`."
    else:
        header += "\nAucun titre pour l'instant : les premiers se gagnent en chassant."

    # Chaque section devient un ou plusieurs champs ; les champs remplissent
    # les pages l'un après l'autre.
    pages: list[list[tuple[str, str]]] = [[]]
    used = 0
    for name, lines in sections:
        for index, value in enumerate(_fields(lines)):
            field_name = name if index == 0 else f"{name} (suite)"
            cost = len(field_name) + len(value)
            if pages[-1] and (used + cost > PAGE_BUDGET or len(pages[-1]) >= MAX_FIELDS):
                pages.append([])
                used = 0
            pages[-1].append((field_name, value))
            used += cost

    embeds: list[discord.Embed] = []
    title = clip(f"🏷️ Titres de {display_name}", 250)
    for fields in pages:
        embed = discord.Embed(title=title, description=header, color=discord.Color.gold())
        for field_name, value in fields:
            embed.add_field(name=field_name, value=value, inline=False)
        embeds.append(embed)
    return embeds
