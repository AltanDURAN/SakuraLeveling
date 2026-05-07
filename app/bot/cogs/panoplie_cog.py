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
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.sets.set_loader import (
    get_definition as get_set_definition,
    list_definitions as list_set_definitions,
)


_BONUS_LABELS = {
    "defense_flat":         "défense",
    "dodge_flat":           "% esquive",
    "crit_chance_flat":     "% chance critique",
    "crit_damage_flat":     "% dégâts critiques",
    "hp_regeneration_flat": "régénération PV / min",
    "attack_flat":          "attaque",
    "speed_flat":           "vitesse",
    "max_hp_flat":          "PV max",
}

_SLOT_ICONS: dict[str, str] = {
    "casque":         "⛑️",
    "plastron":       "👕",
    "jambieres":      "👖",
    "bottes":         "🥾",
    "main_droite":    "🗡️",
    "main_gauche":    "🛡️",
    "collier":        "📿",
    "bracelet":       "⛓️",
    "bague":          "💍",
    "ceinture":       "🎗️",
    "cape":           "🧣",
    "boucle_oreille": "👂",
}

_SLOT_LABELS: dict[str, str] = {
    "casque":         "Casque",
    "plastron":       "Plastron",
    "jambieres":      "Jambières",
    "bottes":         "Bottes",
    "main_droite":    "Main droite",
    "main_gauche":    "Main gauche",
    "collier":        "Collier",
    "bracelet":       "Bracelet",
    "bague":          "Bague",
    "ceinture":       "Ceinture",
    "cape":           "Cape",
    "boucle_oreille": "Boucle d'oreille",
}

# Ordre canonique des slots (principaux puis secondaires)
_SLOT_ORDER = [
    "casque", "plastron", "jambieres", "bottes",
    "main_droite", "main_gauche",
    "collier", "bracelet", "bague",
    "ceinture", "cape", "boucle_oreille",
]


def _format_bonus(bonus_type: str, value: int) -> str:
    label = _BONUS_LABELS.get(bonus_type, bonus_type)
    return f"+{value} {label}"


def _format_stat_bonuses_short(stat_bonuses: dict | None) -> str:
    if not stat_bonuses:
        return ""
    short_labels = {
        "max_hp": "PV", "attack": "Atk", "defense": "Def",
        "speed": "Vit", "crit_chance": "Crit", "crit_damage": "CDmg",
        "dodge": "Esq", "hp_regeneration": "Régen",
    }
    parts = [
        f"+{v} {short_labels.get(k, k)}"
        for k, v in stat_bonuses.items() if v
    ]
    return "  ·  ".join(parts)


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

        with get_db_session() as session:
            all_items = ItemRepository(session).list_all()

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
            for slot in _SLOT_ORDER:
                items = by_slot.get(slot)
                slot_label = (
                    f"{_SLOT_ICONS.get(slot, '•')} **{_SLOT_LABELS.get(slot, slot)}**"
                )
                if not items:
                    piece_lines.append(f"{slot_label} : —")
                    continue
                # Plusieurs items dans le même slot → une ligne par item
                for it in items:
                    bonuses = _format_stat_bonuses_short(it.stat_bonuses)
                    suffix = f"  ·  {bonuses}" if bonuses else ""
                    piece_lines.append(f"{slot_label} : {it.name}{suffix}")

            # Découpe en plusieurs fields si > 1000 chars (limite 1024)
            buf = ""
            field_count = 1
            base_name = (
                f"🧩 Pièces de la panoplie ({len(items_in_family)}/12)"
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
                name="🧩 Pièces de la panoplie (0/12)",
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
