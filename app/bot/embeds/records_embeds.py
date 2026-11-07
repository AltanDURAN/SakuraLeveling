"""Salon des records (07/11/2026) : le tableau de la nuit, ce qui a changé,
et `/records` (où en est un joueur)."""

from __future__ import annotations

from datetime import date

import discord

from app.domain.services import records_service as rs
from app.infrastructure.titles.title_loader import get_definition as get_title
from app.shared.formatters import format_date_fr, format_int

COLOR = discord.Color.gold()
FIELD_MAX = 1024


def value_text(record: rs.RecordDef, value: int) -> str:
    if record.code == rs.TOWER.code:
        return f"**étage {value}**"
    return f"**{format_int(value)}**" + (f" {record.unit}" if record.unit else "")


def mention(names: dict, player_id: int) -> str:
    discord_id, name = names.get(player_id, (0, "?"))
    return f"<@{discord_id}>" if discord_id else f"**{name}**"


def title_line(code: str, holder: int | None, names: dict, count: int = 0) -> str:
    """« 🥇 Légende des records · @X · 5 records · +5 % d'or »."""
    title = get_title(code)
    icon, name = (title.icon, title.name) if title else ("🏅", code)
    gold = sum(int(e.get("value", 0)) for e in (title.effects if title else []) if e.get("type") == "gold_bonus_pct")
    who = mention(names, holder) if holder is not None else "_personne_"
    held = f" · {count} record{'s' if count > 1 else ''}" if holder is not None and count else ""
    return f"{icon} **{name}** · {who}{held} · +{gold} % d'or"


def _fields(records: list[rs.RecordDef], line) -> list[tuple[str, str]]:
    fields = []
    for category, heading in rs.CATEGORIES:
        lines = [line(r) for r in records if r.category == category]
        if lines:
            text = "\n".join(lines)
            fields.append((heading, text if len(text) <= FIELD_MAX else text[:FIELD_MAX - 1] + "…"))
    return fields


def build_board_embed(records: list[rs.RecordDef], held: dict[str, rs.Entry], standings: list[rs.Standing],
                      names: dict, day: date) -> discord.Embed:
    """Le tableau épinglé du salon, réécrit chaque nuit."""
    counts = {s.player_id: s.count for s in standings}
    titles = rs.title_awards(standings)
    embed = discord.Embed(
        title="🏆 Les records du Grand Cerisier",
        description=(
            "Chaque nuit à minuit, les records sont mis à jour. Fais **strictement mieux** qu'un détenteur "
            "et le record est à toi. Où en es-tu ? `/records`\n\n"
            + "\n".join(title_line(code, holder, names, counts.get(holder, 0)) for code, holder in titles.items())
        ),
        color=COLOR,
    )

    def line(record: rs.RecordDef) -> str:
        entry = held.get(record.code)
        if entry is None:
            return f"{record.emoji} {record.label} · _personne_"
        against = f" · {entry.detail}" if record.category == "exploits" and entry.detail else ""
        return f"{record.emoji} {record.label} · {value_text(record, entry.value)} · {mention(names, entry.player_id)}{against}"

    for name, value in _fields(records, line):
        embed.add_field(name=name, value=value, inline=False)
    embed.set_footer(text=f"Mis à jour le {format_date_fr(day)} à minuit · comptes admin exclus · "
                          "exploits hors lunes")
    return embed


def build_news(changes: list[rs.Change], new_titles: dict[str, int], standings: list[rs.Standing],
               names: dict, first: bool = False) -> tuple[discord.Embed | None, list[int]]:
    """Ce qui a bougé cette nuit, et les joueurs à mentionner (les nouveaux
    détenteurs). (None, []) si rien n'a bougé."""
    lines = []
    ping: list[int] = []
    for change in changes:
        record, new, old = change.record, change.new, change.old
        who = mention(names, new.player_id)
        value = value_text(record, new.value)
        before = f" (avant : {value_text(record, old.value)})" if old is not None else ""
        if old is None:
            lines.append(f"{record.emoji} **{record.label}** : {who} — {value}")
        elif change.taken:
            lines.append(f"{record.emoji} **{record.label}** : {who} bat {mention(names, old.player_id)} — {value}{before}")
        else:
            lines.append(f"{record.emoji} **{record.label}** : {who} améliore son record — {value}{before}")
        if new.player_id not in ping:
            ping.append(new.player_id)
    counts = {s.player_id: s.count for s in standings}
    titles = [title_line(code, holder, names, counts.get(holder, 0)) for code, holder in new_titles.items()]
    for holder in new_titles.values():
        if holder not in ping:
            ping.append(holder)
    if not lines and not titles:
        return None, []
    embed = discord.Embed(title="🏆 Les premiers records" if first else "🌙 Cette nuit dans les records",
                          description="\n".join(lines)[:4000] or None, color=COLOR)
    if titles:
        embed.add_field(name="Nouveaux titres", value="\n".join(titles)[:FIELD_MAX], inline=False)
    return embed, ping


def build_personal_embed(view, player_id: int) -> discord.Embed:
    """`/records` : chaque record, son détenteur, et où en est le joueur."""
    mine_held = sum(1 for e in view.held.values() if e.player_id == player_id)
    description = f"Tu détiens **{mine_held}** record{'s' if mine_held > 1 else ''} sur {len(view.records)}."
    if view.excluded:
        description += "\n_Compte admin : tu n'entres pas dans les records._"
    description += "\nMis à jour chaque nuit à minuit : bats un record aujourd'hui, il est à toi cette nuit."
    embed = discord.Embed(title="🏆 Tes records", description=description, color=COLOR)

    def line(record: rs.RecordDef) -> str:
        entry, mine = view.held.get(record.code), view.mine.get(record.code)
        mine_value = mine.value if mine else 0
        if entry is None:
            head = f"{record.emoji} {record.label} · _personne_"
            if mine_value and not view.excluded:
                tail = f"toi {value_text(record, mine_value)} : à toi cette nuit"
            else:
                tail = f"toi {value_text(record, mine_value)}" if mine_value else "à prendre"
        elif entry.player_id == player_id:
            return f"{record.emoji} {record.label} · {value_text(record, entry.value)} · 👑 **c'est toi**"
        else:
            head = f"{record.emoji} {record.label} · {value_text(record, entry.value)} · {mention(view.names, entry.player_id)}"
            if mine_value > entry.value:
                tail = f"🔥 toi {value_text(record, mine_value)} : mieux que le record !"
            elif mine_value:
                tail = f"toi {value_text(record, mine_value)} · il te manque **{format_int(entry.value - mine_value + 1)}**"
            else:
                tail = "toi : —"
        return f"{head}\n　{tail}"

    for name, value in _fields(view.records, line):
        embed.add_field(name=name, value=value, inline=False)
    return embed
