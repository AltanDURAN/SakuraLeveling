"""Cog `/panoplie <famille>` : détail d'une panoplie (set).

Affiche :
  - en-tête : icône + nom + description
  - section Paliers : 2 / 4 / 8 / 12 pièces avec leur bonus respectif
  - section Pièces de la panoplie : tous les items qui appartiennent à
    cette famille, regroupés par slot

L'autocomplete propose toutes les familles définies dans `sets.json`,
filtrées par la sous-chaîne tapée.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.sets.set_loader import (
    get_definition as get_set_definition,
    list_definitions as list_set_definitions,
)
from app.shared.emoji_mappings import (
    bonus_emoji,
    format_stat_bonuses_short,
    item_display_emoji,
)
from app.shared.enums import SLOT_ICONS, SLOT_ORDER


def _format_bonus(bonus_type: str, value: int) -> str:
    """Format compact "+N {emoji}" — l'emoji remplace le label texte."""
    return f"+{value} {bonus_emoji(bonus_type)}"


class PanoplieCog(commands.Cog):
    """Détail d'une panoplie : paliers + items qui la composent."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.channel_id != settings.beta_channel_id:
            message = (
                "🚧 Le bot est actuellement en phase de test.\n"
                "Utilisez le channel beta dédié."
            )
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return False
        return True

    @app_commands.command(
        name="panoplie",
        description="Détail d'une panoplie : paliers, bonus et pièces qui la composent",
    )
    @app_commands.describe(nom="Nom de la panoplie (autocomplete)")
    async def panoplie(
        self, interaction: discord.Interaction, nom: str,
    ) -> None:
        set_def = get_set_definition(nom)
        if set_def is None:
            await interaction.response.send_message(
                f"❌ Panoplie `{nom}` introuvable. Utilise l'autocomplete.",
                ephemeral=True,
            )
            return

        # Récupère aussi inventaire + équipement du viewer pour cocher les
        # pièces déjà possédées (✅ à droite de chaque ligne).
        owned_def_ids: set[int] = set()
        with get_db_session() as session:
            all_items = ItemRepository(session).list_all()
            profile = PlayerRepository(session).get_by_discord_id(
                interaction.user.id,
            )
            if profile is not None:
                inv = InventoryRepository(session).list_by_player_id(
                    profile.player.id,
                )
                eq = EquipmentRepository(session).list_by_player_id(
                    profile.player.id,
                )
                owned_def_ids = (
                    {i.item_definition.id for i in inv}
                    | {e.item_definition.id for e in eq}
                )

        items_in_family = [
            it for it in all_items
            if (it.family or "").strip() == nom and it.equipment_slot
        ]

        embed = discord.Embed(
            title=f"{set_def.get('icon', '✨')}  Panoplie : {set_def.get('name', nom)}",
            description=set_def.get("description", "—"),
            color=discord.Color.from_str(set_def.get("color", "#a07040")),
        )

        # ----- Paliers (compact, sur 4 lignes) -----
        tiers = sorted(
            set_def.get("tiers", []),
            key=lambda t: int(t.get("min_pieces", 0)),
        )
        if tiers:
            lines = []
            for tier in tiers:
                mp = int(tier.get("min_pieces", 0))
                bonus_text = _format_bonus(
                    tier.get("type", ""), int(tier.get("value", 0)),
                )
                lines.append(f"**{mp} pièces** → {bonus_text}")
            embed.add_field(
                name="📊 Paliers de bonus",
                value="\n".join(lines),
                inline=False,
            )

        # ----- Pièces de la panoplie (1 ligne / pièce, ordre canonique) -----
        # Le compteur (X/12) est intégré au titre de la rubrique pour ne
        # pas dupliquer l'info en field séparé.
        if items_in_family:
            by_slot: dict[str, list] = {}
            for it in items_in_family:
                by_slot.setdefault(it.equipment_slot or "?", []).append(it)

            piece_lines: list[str] = []
            for slot in SLOT_ORDER:
                items = by_slot.get(slot)
                slot_icon = SLOT_ICONS.get(slot, "•")
                if not items:
                    # Slot manquant : juste l'icône + tiret. Le label texte
                    # est redondant avec l'emoji, on l'omet.
                    piece_lines.append(f"{slot_icon} —")
                    continue
                for it in items:
                    bonuses = format_stat_bonuses_short(it.stat_bonuses)
                    suffix = f" · {bonuses}" if bonuses else ""
                    owned_marker = " ✅" if it.id in owned_def_ids else ""
                    item_icon = item_display_emoji(it)
                    piece_lines.append(
                        f"{item_icon} **{it.name}**{suffix}{owned_marker}"
                    )

            # Découpe en plusieurs fields si > 1000 chars (limite 1024)
            buf = ""
            field_count = 1
            base_name = (
                f"🧩 Pièces de la panoplie ({len(items_in_family)}/16)"
            )
            for line in piece_lines:
                if len(buf) + len(line) + 1 > 1000 and buf:
                    embed.add_field(
                        name=(base_name if field_count == 1
                              else f"🧩 Pièces (suite {field_count})"),
                        value=buf,
                        inline=False,
                    )
                    buf = ""
                    field_count += 1
                buf += ("\n" if buf else "") + line
            if buf:
                embed.add_field(
                    name=(base_name if field_count == 1
                          else f"🧩 Pièces (suite {field_count})"),
                    value=buf,
                    inline=False,
                )
        else:
            embed.add_field(
                name="🧩 Pièces de la panoplie (0/16)",
                value="_Aucun item ne porte encore cette famille._",
                inline=False,
            )

        await interaction.response.send_message(embed=embed)

    @panoplie.autocomplete("nom")
    async def panoplie_autocomplete(
        self, interaction: discord.Interaction, current: str,
    ) -> list[app_commands.Choice[str]]:
        sets_def = list_set_definitions()
        current_lower = current.lower()
        choices: list[app_commands.Choice[str]] = []
        for code, set_def in sets_def.items():
            name = set_def.get("name", code)
            icon = set_def.get("icon", "✨")
            if (
                current_lower in code.lower()
                or current_lower in name.lower()
            ):
                choices.append(
                    app_commands.Choice(name=f"{icon} {name}", value=code),
                )
            if len(choices) >= 25:
                break
        return choices


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PanoplieCog(bot))
