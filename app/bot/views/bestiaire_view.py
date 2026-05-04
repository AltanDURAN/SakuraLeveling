"""Vue paginée du bestiaire (1 mob par page).

Chaque page affiche la fiche complète d'un mob : stats, famille, drops.
Boutons ◀ Précédent / Suivant ▶ pour naviguer.
"""

from __future__ import annotations

import discord

from app.domain.entities.mob_definition import MobDefinition


def _format_loot_line(loot_entry: dict) -> str:
    code = loot_entry.get("item_code", "?")
    rate_pct = int(float(loot_entry.get("drop_rate", 0)) * 100)
    qty_min = loot_entry.get("min_quantity", 1)
    qty_max = loot_entry.get("max_quantity", 1)
    qty_label = f"×{qty_min}" if qty_min == qty_max else f"×{qty_min}-{qty_max}"
    return f"• `{code}` {qty_label} ({rate_pct}%)"


def build_mob_embed(mob: MobDefinition, idx: int, total: int) -> discord.Embed:
    embed = discord.Embed(
        title=f"📖 {mob.name}",
        description=mob.description or "_Pas de description._",
        color=discord.Color.dark_red(),
    )
    embed.add_field(
        name="Identité",
        value=(
            f"`{mob.code}`\n"
            f"Famille : **{mob.family or '—'}**"
        ),
        inline=False,
    )
    embed.add_field(
        name="📊 Stats",
        value=(
            f"❤️ PV : **{mob.max_hp:,}**\n"
            f"⚔️ Atk : **{mob.attack:,}**\n"
            f"🛡️ Def : **{mob.defense:,}**\n"
            f"💨 Spd : **{mob.speed}**\n"
            f"🎯 Crit : **{mob.crit_chance}%** (×{mob.crit_damage}%)\n"
            f"🌀 Esquive : **{mob.dodge}%**"
        ),
        inline=True,
    )
    embed.add_field(
        name="💰 Récompenses",
        value=(
            f"✨ XP : **{mob.xp_reward}**\n"
            f"💰 Or : **{mob.gold_reward}**\n"
            f"⚖️ Poids spawn : {mob.spawn_weight}"
        ),
        inline=True,
    )
    if mob.loot_table:
        loot_lines = [_format_loot_line(entry) for entry in mob.loot_table]
        embed.add_field(
            name="🎁 Drops",
            value="\n".join(loot_lines)[:1024] or "_aucun_",
            inline=False,
        )

    if mob.image_name:
        embed.set_thumbnail(url=f"attachment://{mob.image_name}")

    embed.set_footer(text=f"Mob {idx + 1}/{total} · Naviguez avec les boutons")
    return embed


class BestiaireView(discord.ui.View):
    def __init__(
        self,
        author_id: int,
        mobs: list[MobDefinition],
        timeout: float = 300.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.mobs = mobs
        self.index = 0
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        self.prev_button.disabled = self.index <= 0
        self.next_button.disabled = self.index >= len(self.mobs) - 1
        self.counter.label = f"{self.index + 1} / {len(self.mobs)}"

    async def _check_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Cette navigation ne vous est pas destinée. Tape `/bestiaire`.",
                ephemeral=True,
            )
            return False
        return True

    def _build_embed(self) -> discord.Embed:
        return build_mob_embed(self.mobs[self.index], self.index, len(self.mobs))

    @discord.ui.button(label="◀ Précédent", style=discord.ButtonStyle.secondary)
    async def prev_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await self._check_owner(interaction):
            return
        if self.index > 0:
            self.index -= 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

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
        if self.index < len(self.mobs) - 1:
            self.index += 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)
