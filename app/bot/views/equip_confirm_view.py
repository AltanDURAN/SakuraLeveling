"""Vue de confirmation d'équipement avec preview du diff stats.

Affichée quand le joueur tente d'équiper un item dans un slot déjà occupé.
Permet de visualiser les gains/pertes de stats avant de confirmer le swap.
"""

from __future__ import annotations

from dataclasses import dataclass

import discord

from app.application.use_cases.equip_item import EquipItemUseCase
from app.domain.value_objects.stats import Stats
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session


@dataclass
class StatDiff:
    label: str
    before: int
    after: int

    @property
    def delta(self) -> int:
        return self.after - self.before

    def render(self) -> str:
        if self.delta == 0:
            return f"• {self.label} : **{self.after}**"
        sign = "+" if self.delta > 0 else ""
        emoji = "🟢" if self.delta > 0 else "🔴"
        return f"{emoji} {self.label} : {self.before} → **{self.after}** ({sign}{self.delta})"


def compute_stats_diff(before: Stats, after: Stats) -> list[StatDiff]:
    return [
        StatDiff("PV max", before.max_hp, after.max_hp),
        StatDiff("Attaque", before.attack, after.attack),
        StatDiff("Défense", before.defense, after.defense),
        StatDiff("Vitesse", before.speed, after.speed),
        StatDiff("Crit %", before.crit_chance, after.crit_chance),
        StatDiff("Dégâts crit", before.crit_damage, after.crit_damage),
        StatDiff("Esquive", before.dodge, after.dodge),
        StatDiff("Régén", before.hp_regeneration, after.hp_regeneration),
    ]


def build_equip_confirm_embed(
    item_name: str,
    slot: str,
    replacing_name: str,
    diffs: list[StatDiff],
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🔄 Confirmer l'équipement de {item_name}",
        description=(
            f"Slot : `{slot}` — actuellement équipé : **{replacing_name}**\n"
            "Voici le diff de vos statistiques après le changement :"
        ),
        color=discord.Color.orange(),
    )
    embed.add_field(
        name="Diff de statistiques",
        value="\n".join(d.render() for d in diffs),
        inline=False,
    )
    return embed


class EquipConfirmView(discord.ui.View):
    def __init__(
        self,
        author_id: int,
        discord_id: int,
        username: str,
        display_name: str,
        item_code: str,
        timeout: float = 60.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.discord_id = discord_id
        self.username = username
        self.display_name = display_name
        self.item_code = item_code

    async def _interaction_is_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Cette confirmation ne vous est pas destinée.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await self._interaction_is_owner(interaction):
            return
        with get_db_session() as session:
            use_case = EquipItemUseCase(
                player_repository=PlayerRepository(session),
                inventory_repository=InventoryRepository(session),
                equipment_repository=EquipmentRepository(session),
            )
            result = use_case.execute(
                discord_id=self.discord_id,
                username=self.username,
                display_name=self.display_name,
                item_code=self.item_code,
            )
        for child in self.children:
            child.disabled = True
        msg = result.message
        if result.unequipped_items:
            msg += f"\n_Déséquipé : {', '.join(result.unequipped_items)}._"
        await interaction.response.edit_message(content=msg, embed=None, view=self)
        self.stop()

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary, emoji="🛑")
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await self._interaction_is_owner(interaction):
            return
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="🛑 Équipement annulé.", embed=None, view=self
        )
        self.stop()
