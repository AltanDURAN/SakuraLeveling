"""Garde-fous des limites de Discord pour les embeds (revue du 13/11/2026).

Une liste qui grossit avec le jeu (joueurs d'un raid, objets d'un échange,
titres…) finit par dépasser une limite : 1 024 caractères pour la valeur d'un
champ, 4 096 pour une description, 6 000 pour l'embed entier — et Discord
refuse alors TOUT le message (400 Bad Request). Ces fonctions découpent ou
coupent proprement, et disent ce qui n'est pas montré.
"""

from __future__ import annotations

from collections.abc import Sequence

import discord

FIELD_VALUE_MAX = 1024
DESCRIPTION_MAX = 4096
EMBED_MAX = 6000
#: Marge sous la limite d'un champ (emojis et caractères comptés à part).
FIELD_BUDGET = 1000


def clip(text: str, limit: int) -> str:
    """`text` ramené à `limit` caractères, terminé par « … » s'il est coupé."""
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def chunk_lines(lines: Sequence[str], budget: int = FIELD_BUDGET) -> list[str]:
    """Des lignes regroupées en blocs d'au plus `budget` caractères (une ligne
    trop longue est coupée, jamais répartie sur deux blocs)."""
    chunks: list[list[str]] = [[]]
    size = 0
    for line in lines:
        line = clip(line, budget)
        if chunks[-1] and size + len(line) + 1 > budget:
            chunks.append([])
            size = 0
        chunks[-1].append(line)
        size += len(line) + 1
    return ["\n".join(chunk) for chunk in chunks if chunk]


def fit_lines(lines: Sequence[str], budget: int = FIELD_BUDGET, more: str = "… et {n} de plus") -> str:
    """Autant de lignes entières que `budget` le permet ; le reste est COMPTÉ
    (« … et 12 de plus »), jamais coupé au milieu d'une ligne ni en silence."""
    kept: list[str] = []
    size = 0
    for index, line in enumerate(lines):
        rest = len(lines) - index
        tail = len(more.format(n=rest)) + 1
        if size + len(line) + 1 + (tail if rest > 1 else 0) > budget:
            return "\n".join([*kept, more.format(n=rest)])
        kept.append(line)
        size += len(line) + 1
    return "\n".join(kept)


def add_lines(embed: discord.Embed, name: str, lines: Sequence[str], *, inline: bool = False,
              max_fields: int = 3, empty: str | None = None, more: str = "… et {n} de plus") -> None:
    """Ajoute `lines` en un ou plusieurs champs (« nom », « nom (suite) »…),
    `max_fields` au plus ; au-delà, le dernier champ compte ce qui manque."""
    if not lines:
        if empty is not None:
            embed.add_field(name=name, value=empty, inline=inline)
        return
    chunks = chunk_lines(lines)
    if len(chunks) > max_fields:
        shown = sum(chunk.count("\n") + 1 for chunk in chunks[: max_fields - 1])
        chunks = [*chunks[: max_fields - 1], fit_lines(lines[shown:], more=more)]
    for index, chunk in enumerate(chunks):
        embed.add_field(name=name if index == 0 else f"{name} (suite)", value=chunk, inline=inline)
