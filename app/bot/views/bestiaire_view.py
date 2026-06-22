"""Vue paginée du bestiaire (1 mob par page).

Chaque page : fiche complète d'un mob (score de puissance, rang, stats,
famille, drops) + aperçu de son image en thumbnail (haut-droite de l'embed).
Mobs triés par score de puissance CROISSANT. Boutons ◀ / ▶.
"""

from __future__ import annotations

import discord

from app.domain.entities.mob_definition import MobDefinition
from app.domain.services import element_service
from app.domain.services.power_score_service import PowerScoreService
from app.shared.enums import ELEMENT_EMOJIS, ELEMENT_LABELS
from app.shared.paths import MOBS_ASSETS_DIR


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


def _format_loot_line(loot_entry: dict) -> str:
    code = loot_entry.get("item_code", "?")
    rate_pct = int(float(loot_entry.get("drop_rate", 0)) * 100)
    qty_min = loot_entry.get("min_quantity", 1)
    qty_max = loot_entry.get("max_quantity", 1)
    qty_label = f"×{qty_min}" if qty_min == qty_max else f"×{qty_min}-{qty_max}"
    return f"• `{code}` {qty_label} ({rate_pct}%)"


def build_mob_embed(
    mob: MobDefinition,
    idx: int,
    total: int,
    power_score: str,
    rank: str,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"📖 {mob.name}",
        description=mob.description or "_Pas de description._",
        color=discord.Color.dark_red(),
    )
    # Puissance bien visible : score + rang
    embed.add_field(
        name="🏆 Puissance",
        value=f"Score : **{power_score}**\nRang : **{rank}**",
        inline=False,
    )
    embed.add_field(
        name="Identité",
        value=f"`{mob.code}`\nFamille : **{mob.family or '—'}**\n{_element_line(mob.element)}",
        inline=False,
    )
    embed.add_field(
        name="📊 Stats",
        value=(
            f"❤️ PV : **{mob.max_hp:,}**\n"
            f"⚔️ Atk : **{mob.attack:,}**\n"
            f"🛡️ Def : **{mob.defense:,}**\n"
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

    embed.set_footer(text=f"Mob {idx + 1}/{total} · trié par puissance croissante")
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
        self._pss = PowerScoreService()
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

    def render_current(self) -> tuple[discord.Embed, discord.File | None]:
        """Embed du mob courant + son image (thumbnail). File=None si absente."""
        mob = self.mobs[self.index]
        score = self._pss.calculate_from_mob(mob)
        embed = build_mob_embed(
            mob, self.index, len(self.mobs),
            power_score=self._pss.format_score(score),
            rank=self._pss.compute_rank(score),
        )
        file = None
        if mob.image_name:
            path = MOBS_ASSETS_DIR / mob.image_name
            if path.exists():
                file = discord.File(str(path), filename=mob.image_name)
            else:
                embed.set_thumbnail(url=None)  # pas d'image → pas de thumbnail cassé
        return embed, file

    async def _send_page(self, interaction: discord.Interaction) -> None:
        self._refresh_buttons()
        embed, file = self.render_current()
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
        if self.index < len(self.mobs) - 1:
            self.index += 1
        await self._send_page(interaction)
