"""Bestiaire des world boss (`/bestiaire boss`, 07/11/2026) — remplace
`/boss list`, dans le style du bestiaire des monstres : une page par boss,
À DÉCOUVRIR. Un boss qu'on n'a jamais aidé à abattre n'est qu'une silhouette ;
abattu, sa fiche (stats, élément, mécaniques, butin) et le nombre de fois où
on l'a abattu.
"""

from __future__ import annotations

import discord

from app.bot.rendering.silhouette import FILENAME as SILHOUETTE_FILE
from app.bot.views.bestiaire_view import PagedBookView, _element_line, _format_loot_line, picture
from app.domain.entities.boss_definition import BossDefinition
from app.shared.formatters import format_int

#: Particularités d'un boss, dites simplement (ex-`/boss list`).
TRAIT_LABELS = {
    "damage_immunity_threshold": "ignore les coups trop faibles",
    "auto_heal_per_turn": "se soigne",
    "reflect_pct": "renvoie une part des dégâts",
    "crit_immunity": "insensible aux critiques",
    "adds": "invoque des renforts",
}
COLOR = discord.Color.dark_purple()


def _footer(idx: int, total: int, progress: str) -> str:
    parts = [f"Boss {idx + 1}/{total}", progress, "trié par niveau"]
    return " · ".join(part for part in parts if part)


def element_line(boss: BossDefinition) -> str:
    """Un boss change d'élément à chaque apparition (11/11/2026), sauf si sa
    fiche en impose un."""
    if boss.element:
        return _element_line(boss.element)
    return "Élément : 🎲 **tiré au hasard à chaque apparition** (il est annoncé avec le boss)"


def mechanics_lines(boss: BossDefinition) -> list[str]:
    """Phases, attaque ultime, gardes et particularités, en clair."""
    lines = []
    if boss.phases:
        lines.append("• Phases : " + " · ".join(
            f"{phase.get('name', '?')} ({phase.get('below_pct', '?')} %)" for phase in boss.phases))
    if boss.ultimate:
        lines.append(f"• Ultime : {boss.ultimate.get('name', '?')}, toutes les "
                     f"{boss.ultimate.get('every', '?')} actions, sur tout le groupe")
    if boss.guards:
        names = list(dict.fromkeys(guard.get("name", "?") for guard in boss.guards))
        lines.append(f"• {len(boss.guards)} gardes : {', '.join(names)}")
    traits = [label for key, label in TRAIT_LABELS.items() if boss.modifiers.get(key)]
    if traits:
        lines.append("• Particularités : " + ", ".join(traits))
    return lines


def build_boss_embed(boss: BossDefinition, idx: int, total: int, items: dict | None = None,
                     victories: int | None = None, progress: str = "") -> discord.Embed:
    items = items or {}
    embed = discord.Embed(title=f"👑 {boss.name}", description=boss.lore or boss.description or "_Pas d'histoire._",
                          color=COLOR)
    embed.add_field(name="🏆 Raid", value=f"Pour une équipe de niveau **{boss.level}**", inline=victories is not None)
    if victories is not None:
        embed.add_field(name="⚔️ Tes victoires", value=f"**{format_int(victories)}**", inline=True)
    embed.add_field(name="Identité", value=element_line(boss), inline=False)
    embed.add_field(
        name="📊 Stats",
        value=(
            f"❤️ PV : **{format_int(boss.max_hp)}**\n"
            f"⚔️ Atk : **{format_int(boss.attack)}**\n"
            f"🛡️ Def : **{format_int(boss.defense)}**\n"
            f"💨 Spd : **{boss.speed}**\n"
            f"🎯 Chance crit : **{boss.crit_chance}%**\n"
            f"💥 Dégâts crit : **{boss.crit_damage}%**\n"
            f"🌀 Esquive : **{boss.dodge}%**"
        ),
        inline=True,
    )
    mechanics = mechanics_lines(boss)
    if mechanics:
        embed.add_field(name="⚡ Mécaniques", value="\n".join(mechanics)[:1024], inline=True)
    if boss.loot_table:
        names = {code: item.name for code, item in items.items()}
        embed.add_field(name="🎁 Butin (chacun tente sa chance)", inline=False,
                        value="\n".join(_format_loot_line(entry, names) for entry in boss.loot_table)[:1024])
    if boss.image_name:
        embed.set_thumbnail(url=f"attachment://{boss.image_name}")
    embed.set_footer(text=_footer(idx, total, progress))
    return embed


def build_unknown_boss_embed(boss: BossDefinition, idx: int, total: int, progress: str = "",
                             silhouette: bool = False, boss_channel_id: int = 0) -> discord.Embed:
    """Un boss jamais abattu : sa silhouette, où et quand il vient, rien d'autre."""
    embed = discord.Embed(
        title="❔ ???",
        description=("Tu ne l'as pas encore abattu. Participe aux assauts d'un raid qui en vient à bout "
                     "pour découvrir son nom et sa fiche : stats, mécaniques, butin."),
        color=discord.Color.dark_grey(),
    )
    when = f"quand le serveur approche le niveau **{boss.level}**."
    embed.add_field(name="🗺️ Où le trouver", inline=False,
                    value=f"<#{boss_channel_id}>, {when}" if boss_channel_id else f"Il vient {when}")
    if silhouette:
        embed.set_thumbnail(url=f"attachment://{SILHOUETTE_FILE}")
    embed.set_footer(text=_footer(idx, total, progress))
    return embed


class BossBestiaryView(PagedBookView):
    command = "/bestiaire boss"

    def __init__(self, author_id: int, bosses: list[BossDefinition], timeout: float = 300.0,
                 items: dict | None = None, victories: dict[str, int] | None = None,
                 boss_channel_id: int = 0) -> None:
        super().__init__(author_id, sorted(bosses, key=lambda b: b.level), timeout=timeout)
        self.items = items or {}
        #: Boss abattus par le joueur, par code ; None = tout est visible.
        self.victories = victories
        self.boss_channel_id = boss_channel_id
        self._refresh_buttons()

    def discovered(self, boss: BossDefinition) -> bool:
        return self.victories is None or self.victories.get(boss.code, 0) > 0

    def progress(self) -> str:
        """« 👑 1/5 vaincus » (rien si tout est visible)."""
        if self.victories is None:
            return ""
        return f"👑 {sum(1 for b in self.pages if self.discovered(b))}/{len(self.pages)} vaincus"

    async def render(self) -> tuple[discord.Embed, discord.File | None]:
        boss = self.pages[self.index]
        known = self.discovered(boss)
        file = await picture(boss.image_name, known)
        if not known:
            return build_unknown_boss_embed(boss, self.index, len(self.pages), self.progress(),
                                            silhouette=file is not None,
                                            boss_channel_id=self.boss_channel_id), file
        embed = build_boss_embed(boss, self.index, len(self.pages), self.items,
                                 victories=None if self.victories is None else self.victories.get(boss.code, 0),
                                 progress=self.progress())
        if file is None:
            embed.set_thumbnail(url=None)
        return embed, file
