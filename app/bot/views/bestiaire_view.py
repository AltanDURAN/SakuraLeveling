"""Vue paginée du bestiaire (1 monstre par page).

Bestiaire À DÉCOUVRIR (07/11/2026, demande de l'auteur) : un monstre que le
joueur n'a pas encore vaincu n'est qu'une silhouette, sans nom ni fiche ; une
fois vaincu, sa fiche complète (score de puissance, rang, stats, famille,
drops) et le nombre de victoires du joueur contre lui. Monstres triés par score
de puissance CROISSANT. Boutons ◀ / ▶, et un menu pour ne parcourir qu'une
famille (les joueurs le demandaient depuis mai).
"""

from __future__ import annotations

import asyncio
import io

import discord

from app.bot.rendering.silhouette import FILENAME as SILHOUETTE_FILE
from app.bot.rendering.silhouette import silhouette_png
from app.domain.entities.mob_definition import MobDefinition
from app.domain.services import element_service
from app.domain.services.gear_passives import get_passive
from app.domain.services.gear_service import DROP_RATES_PCT, RARITY_LABELS, PASSIVE_MIN_RARITY
from app.domain.services.mob_ability_service import is_group_elite
from app.domain.services.power_score_service import PowerScoreService
from app.shared.emoji_mappings import format_stat_bonuses_short
from app.shared.enums import ELEMENT_EMOJIS, ELEMENT_LABELS, GOLD_EMOJI
from app.infrastructure.encounters.farm_zone_loader import get_spawn_channel_for_family
from app.shared.paths import MOBS_ASSETS_DIR
from app.shared.formatters import format_int


ALL_FAMILIES = "__toutes__"


def family_label(family: str) -> str:
    """« mort_vivant » → « Mort-vivant »."""
    return (family or "Sans famille").replace("_", "-").capitalize()


def _element_line(element: str) -> str:
    """Ligne 'Élément' pour la fiche : emoji + nom + faiblesses (qui le battent)."""
    if not element:
        return "Élément : **neutre**"
    emoji = ELEMENT_EMOJIS.get(element, "")
    label = ELEMENT_LABELS.get(element, element)
    weaknesses = element_service.weaknesses_of(element)
    weak_str = ", ".join(
        f"{ELEMENT_EMOJIS.get(e.value, '')} {ELEMENT_LABELS.get(e.value, e.value)}"
        for e in weaknesses
    ) or "—"
    return f"Élément : {emoji} **{label}**\nFaible à : {weak_str}"


def _format_loot_line(loot_entry: dict, item_names: dict[str, str] | None = None) -> str:
    code = loot_entry.get("item_code", "?")
    name = (item_names or {}).get(code)
    rate_pct = int(float(loot_entry.get("drop_rate", 0)) * 100)
    qty_min = loot_entry.get("min_quantity", 1)
    qty_max = loot_entry.get("max_quantity", 1)
    qty_label = f"×{qty_min}" if qty_min == qty_max else f"×{qty_min}-{qty_max}"
    return f"• {name or f'`{code}`'} {qty_label} ({rate_pct}%)"


def _gear_field(mob: MobDefinition, items: dict) -> str | None:
    """Pièce que porte le monstre : stats en commun, passif, chance de drop."""
    item = items.get(getattr(mob, "gear_item_code", "") or "")
    if item is None:
        return None
    chance = f"{sum(DROP_RATES_PCT.values()):.1f}".replace(".", ",")
    lines = [
        f"**{item.name}** · {format_stat_bonuses_short(item.stat_bonuses or {})} (commun)",
    ]
    passive = get_passive(getattr(item, "passive", ""))
    if passive:
        lines.append(f"✨ {passive.name} — {passive.full_description} "
                     f"_(dès {RARITY_LABELS[PASSIVE_MIN_RARITY].lower()})_")
    lines.append(f"🎲 {chance} % de chance par victoire, rareté tirée au sort")
    return "\n".join(lines)


def _footer(idx: int, total: int, progress: str) -> str:
    parts = [f"Monstre {idx + 1}/{total}", progress, "trié par puissance croissante"]
    return " · ".join(part for part in parts if part)


def build_unknown_embed(mob: MobDefinition, idx: int, total: int, progress: str = "",
                        silhouette: bool = False) -> discord.Embed:
    """Un monstre pas encore vaincu : sa silhouette, où le trouver, rien d'autre
    (pas même sa famille : « Slime », « Gobelin »… donneraient son nom)."""
    embed = discord.Embed(
        title="❔ ???",
        description=("Tu ne l'as pas encore vaincu. Bats-le dans un combat de zone pour "
                     "découvrir son nom et sa fiche : stats, butin, équipement."),
        color=discord.Color.dark_grey(),
    )
    embed.add_field(name="🗺️ Où le trouver", value=f"<#{get_spawn_channel_for_family(mob.family)}>", inline=False)
    if is_group_elite(mob.code):
        embed.add_field(name="⚠️ Élite", value="On ne le bat qu'en groupe.", inline=False)
    if silhouette:
        embed.set_thumbnail(url=f"attachment://{SILHOUETTE_FILE}")
    embed.set_footer(text=_footer(idx, total, progress))
    return embed


def build_mob_embed(
    mob: MobDefinition,
    idx: int,
    total: int,
    power_score: str,
    rank: str,
    items: dict | None = None,
    kills: int | None = None,
    progress: str = "",
) -> discord.Embed:
    items = items or {}
    embed = discord.Embed(
        title=f"📖 {mob.name}",
        description=mob.description or "_Pas de description._",
        color=discord.Color.dark_red(),
    )
    # Puissance bien visible : score + rang, et les victoires du joueur.
    embed.add_field(
        name="🏆 Puissance",
        value=f"Score : **{power_score}**\nRang : **{rank}**",
        inline=kills is not None,
    )
    if kills is not None:
        embed.add_field(name="⚔️ Tes victoires", value=f"**{format_int(kills)}**", inline=True)
    embed.add_field(
        name="Identité",
        value=f"Famille : **{family_label(mob.family)}**\n{_element_line(mob.element)}",
        inline=False,
    )
    embed.add_field(
        name="📊 Stats",
        value=(
            f"❤️ PV : **{format_int(mob.max_hp)}**\n"
            f"⚔️ Atk : **{format_int(mob.attack)}**\n"
            f"🛡️ Def : **{format_int(mob.defense)}**\n"
            f"💨 Spd : **{mob.speed}**\n"
            f"🎯 Chance crit : **{mob.crit_chance}%**\n"
            f"💥 Dégâts crit : **{mob.crit_damage}%**\n"
            f"🌀 Esquive : **{mob.dodge}%**"
        ),
        inline=True,
    )
    embed.add_field(
        name="💰 Récompenses",
        value=(
            f"✨ XP : **{mob.xp_reward}**\n"
            f"{GOLD_EMOJI} Or : **{mob.gold_reward}**"
        ),
        inline=True,
    )
    gear = _gear_field(mob, items)
    if gear:
        embed.add_field(name="⚔️ Équipement porté", value=gear[:1024], inline=False)
    if mob.loot_table:
        names = {code: item.name for code, item in items.items()}
        loot_lines = [_format_loot_line(entry, names) for entry in mob.loot_table]
        embed.add_field(
            name="🎁 Drops",
            value="\n".join(loot_lines)[:1024] or "_aucun_",
            inline=False,
        )

    if mob.image_name:
        embed.set_thumbnail(url=f"attachment://{mob.image_name}")

    embed.set_footer(text=_footer(idx, total, progress))
    return embed


class PagedBookView(discord.ui.View):
    """Un livre à pages (◀ n/N ▶), réservé à celui qui l'a ouvert : socle du
    bestiaire des monstres et de celui des boss. Les sous-classes rendent la
    page courante (`render`)."""

    #: La commande à rappeler à un autre joueur qui clique.
    command = "/bestiaire monstres"

    def __init__(self, author_id: int, pages: list, timeout: float = 300.0) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.pages = pages
        self.index = 0

    async def render(self) -> tuple[discord.Embed, discord.File | None]:
        raise NotImplementedError

    def _refresh_buttons(self) -> None:
        self.prev_button.disabled = self.index <= 0
        self.next_button.disabled = self.index >= len(self.pages) - 1
        self.counter.label = f"{self.index + 1} / {len(self.pages)}"

    async def _check_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                f"❌ Cette navigation ne t'est pas destinée. Tape `{self.command}`.",
                ephemeral=True,
            )
            return False
        return True

    async def _send_page(self, interaction: discord.Interaction) -> None:
        self._refresh_buttons()
        embed, file = await self.render()
        attachments = [file] if file is not None else []
        await interaction.response.edit_message(
            embed=embed, attachments=attachments, view=self,
        )

    @discord.ui.button(label="◀ Précédent", style=discord.ButtonStyle.secondary)
    async def prev_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await self._check_owner(interaction):
            return
        if self.index > 0:
            self.index -= 1
        await self._send_page(interaction)

    @discord.ui.button(label="1 / 1", style=discord.ButtonStyle.primary, disabled=True)
    async def counter(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        pass

    @discord.ui.button(label="Suivant ▶", style=discord.ButtonStyle.secondary)
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await self._check_owner(interaction):
            return
        if self.index < len(self.pages) - 1:
            self.index += 1
        await self._send_page(interaction)


async def picture(image_name: str | None, known: bool) -> discord.File | None:
    """La vignette d'une page : l'image, ou sa silhouette si l'entrée n'est pas
    encore découverte ; None sans image."""
    path = MOBS_ASSETS_DIR / image_name if image_name else None
    if path is None or not path.exists():
        return None
    if known:
        return discord.File(str(path), filename=image_name)
    data = await asyncio.to_thread(silhouette_png, path)
    return discord.File(io.BytesIO(data), filename=SILHOUETTE_FILE)


class BestiaireView(PagedBookView):
    def __init__(
        self,
        author_id: int,
        mobs: list[MobDefinition],
        timeout: float = 300.0,
        items: dict | None = None,
        kills: dict[str, int] | None = None,
    ) -> None:
        super().__init__(author_id, mobs, timeout=timeout)
        self.all_mobs = mobs
        self.items = items or {}  # code → ItemDefinition
        #: Victoires du joueur par monstre ; None = tout est visible (sans joueur).
        self.kills = kills
        self._pss = PowerScoreService()
        families = list(dict.fromkeys(m.family or "" for m in mobs))
        if len(families) > 1:
            self.add_item(_FamilySelect(self, families))
        self._refresh_buttons()

    @property
    def mobs(self) -> list[MobDefinition]:
        """Les monstres parcourus (une famille, ou tous)."""
        return self.pages

    @mobs.setter
    def mobs(self, value: list[MobDefinition]) -> None:
        self.pages = value

    def discovered(self, mob: MobDefinition) -> bool:
        return self.kills is None or self.kills.get(mob.code, 0) > 0

    def progress(self, mobs: list[MobDefinition] | None = None) -> str:
        """« 📖 14/50 découverts » (rien si tout est visible)."""
        if self.kills is None:
            return ""
        mobs = self.all_mobs if mobs is None else mobs
        return f"📖 {sum(1 for m in mobs if self.discovered(m))}/{len(mobs)} découverts"

    async def show_family(self, interaction: discord.Interaction, family: str) -> None:
        if not await self._check_owner(interaction):
            return
        self.mobs = self.all_mobs if family == ALL_FAMILIES else \
            [m for m in self.all_mobs if (m.family or "") == family]
        self.index = 0
        await self._send_page(interaction)

    async def render(self) -> tuple[discord.Embed, discord.File | None]:
        """Embed du monstre courant + son image (ou sa silhouette) en vignette.
        File=None sans image."""
        mob = self.mobs[self.index]
        known = self.discovered(mob)
        file = await picture(mob.image_name, known)
        if not known:
            return build_unknown_embed(mob, self.index, len(self.mobs), self.progress(),
                                       silhouette=file is not None), file
        score = self._pss.calculate_from_mob(mob)
        embed = build_mob_embed(
            mob, self.index, len(self.mobs),
            power_score=self._pss.format_score(score),
            rank=self._pss.compute_rank(score),
            items=self.items,
            kills=None if self.kills is None else self.kills.get(mob.code, 0),
            progress=self.progress(),
        )
        if file is None:
            embed.set_thumbnail(url=None)  # pas d'image → pas de thumbnail cassé
        return embed, file


class _FamilySelect(discord.ui.Select):
    """Une famille à la fois, dans l'ordre de puissance (donc des zones)."""

    def __init__(self, owner: BestiaireView, families: list[str]) -> None:
        def progress(family: str | None) -> str | None:
            mobs = owner.all_mobs if family is None else [m for m in owner.all_mobs if (m.family or "") == family]
            return owner.progress(mobs) or None

        options = [discord.SelectOption(label="Tous les monstres", value=ALL_FAMILIES, default=True,
                                        description=progress(None))]
        options += [discord.SelectOption(label=family_label(family), value=family or "_",
                                         description=progress(family))
                    for family in families[:24]]
        super().__init__(placeholder="Choisis une famille…", options=options, row=1)
        self._owner = owner

    async def callback(self, interaction: discord.Interaction) -> None:
        value = self.values[0]
        for option in self.options:
            option.default = option.value == value
        await self._owner.show_family(interaction, "" if value == "_" else value)
