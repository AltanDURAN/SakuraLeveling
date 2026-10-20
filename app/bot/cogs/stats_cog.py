"""Cog `/stats` : la feuille de personnage et l'investissement des points.

SAISON 1. Chaque niveau donne UN point de stats, que le joueur place lui-même
dans l'une des trois stats de base. C'est le seul moteur de puissance brute du
jeu : l'équipement et l'arbre ne font que multiplier ce socle.

Un point placé ne se reprend pas — le choix engage, c'est ce qui lui donne du
poids. La commande le dit avant de valider.
"""

from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from app.application.services.player_stats_resolver import resolve_player_stats
from app.bot.cogs._mixins import BetaChannelOnlyMixin
from app.domain.services.combat_passives import TACTICS, normalize_tactic
from app.domain.services.progression_service import LEVEL_CAP, ProgressionService
from app.domain.services.stats_service import StatsService
from app.domain.value_objects.base_stats import STAT_POINT_GAIN, STAT_POINT_TARGETS
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session
from app.shared.formatters import format_int

_ICONS = {"attack": "⚔️", "defense": "🛡️", "max_hp": "❤️"}


def _load(discord_id: int, username: str, display_name: str) -> dict:
    """Tout ce qu'il faut afficher, lu en une seule session."""
    with get_db_session() as session:
        profile = PlayerRepository(session).get_or_create_by_discord_id(
            discord_id=discord_id, username=username, display_name=display_name,
        )
        worn = EquipmentRepository(session).list_by_player_id(profile.player.id)
        final = resolve_player_stats(session, profile, worn)
        base = StatsService.base_stats_for(profile)
        progression = profile.progression
        return {
            "player_id": profile.player.id,
            "display_name": profile.player.display_name,
            "level": progression.level,
            "xp": progression.xp,
            "xp_required": ProgressionService().xp_required_for_next_level(
                progression.level,
            ),
            "stat_points": progression.stat_points,
            "points": {
                "attack": progression.points_attack,
                "defense": progression.points_defense,
                "max_hp": progression.points_max_hp,
            },
            "base": {
                "attack": base.attack,
                "defense": base.defense,
                "max_hp": base.max_hp,
            },
            "final": {
                "attack": final.attack,
                "defense": final.defense,
                "max_hp": final.max_hp,
            },
        }


def _build_embed(data: dict) -> discord.Embed:
    points = data["stat_points"]
    embed = discord.Embed(
        title=f"📊 Feuille de {data['display_name']}",
        description=(
            f"**{points} point(s) de stats** à placer."
            if points
            else "Aucun point à placer — monte d'un niveau pour en gagner."
        ),
        color=discord.Color.blurple() if points else discord.Color.dark_grey(),
    )

    for key, label in STAT_POINT_TARGETS.items():
        base = data["base"][key]
        final = data["final"][key]
        invested = data["points"][key]
        # On montre le socle ET le total : le joueur doit voir que son
        # équipement multiplie ce qu'il a investi, pas qu'il s'y ajoute.
        bonus = f"  (+{format_int(final - base)} d'équipement)" if final > base else ""
        embed.add_field(
            name=f"{_ICONS[key]} {label}",
            value=(
                f"**{format_int(final)}**{bonus}\n"
                f"socle {format_int(base)} · {invested} point(s) investi(s)"
            ),
            inline=False,
        )

    if data["level"] >= LEVEL_CAP:
        embed.set_footer(text=f"Niveau {LEVEL_CAP} — palier maximum de la saison")
    else:
        embed.set_footer(
            text=(
                f"Niveau {data['level']} · "
                f"{format_int(data['xp'])}/{format_int(data['xp_required'])} XP"
            )
        )
    return embed


class _AllocateButton(discord.ui.Button):
    def __init__(self, view: "StatsView", target: str) -> None:
        gain = STAT_POINT_GAIN[target]
        super().__init__(
            label=f"+{gain} {STAT_POINT_TARGETS[target]}",
            emoji=_ICONS[target],
            style=discord.ButtonStyle.success,
            disabled=view.data["stat_points"] <= 0,
        )
        self._parent = view
        self._target = target

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self._parent
        if interaction.user.id != parent.owner_id:
            await interaction.response.send_message(
                "❌ Ce n'est pas ta feuille.", ephemeral=True,
            )
            return

        def _invest() -> bool:
            with get_db_session() as session:
                return PlayerRepository(session).allocate_stat_point(
                    parent.data["player_id"], self._target, 1,
                )

        placed = await asyncio.to_thread(_invest)
        if not placed:
            await interaction.response.send_message(
                "❌ Plus aucun point disponible.", ephemeral=True,
            )
            return
        await parent.refresh(interaction)


class StatsView(discord.ui.View):
    def __init__(self, data: dict, owner_id: int, timeout: float = 180.0) -> None:
        super().__init__(timeout=timeout)
        self.data = data
        self.owner_id = owner_id
        self._build()

    def _build(self) -> None:
        self.clear_items()
        for target in STAT_POINT_TARGETS:
            self.add_item(_AllocateButton(self, target))

    async def refresh(self, interaction: discord.Interaction) -> None:
        self.data = await asyncio.to_thread(
            _load, interaction.user.id, interaction.user.name,
            interaction.user.display_name,
        )
        self._build()
        await interaction.response.edit_message(
            embed=_build_embed(self.data), view=self,
        )


class StatsCog(BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="stats",
        description="Ta feuille de personnage — place tes points de stats",
    )
    async def stats(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        data = await asyncio.to_thread(
            _load, interaction.user.id, interaction.user.name,
            interaction.user.display_name,
        )
        view = StatsView(data, owner_id=interaction.user.id)
        await interaction.followup.send(embed=_build_embed(data), view=view)


    @app_commands.command(
        name="tactique",
        description="Ta tactique de combat (cible de tes soins) — figée pendant un combat",
    )
    @app_commands.describe(choix="Laisse vide pour voir ta tactique actuelle")
    @app_commands.choices(choix=[
        app_commands.Choice(name=label, value=code) for code, (label, _) in TACTICS.items()
    ])
    async def tactique(
        self, interaction: discord.Interaction,
        choix: app_commands.Choice[str] | None = None,
    ) -> None:
        def _run() -> str:
            with get_db_session() as session:
                repo = PlayerRepository(session)
                profile = repo.get_or_create_by_discord_id(
                    discord_id=interaction.user.id, username=interaction.user.name,
                    display_name=interaction.user.display_name,
                )
                if choix is not None:
                    repo.set_combat_tactic(profile.player.id, choix.value)
                    return normalize_tactic(choix.value)
                return normalize_tactic(profile.player.combat_tactic)

        current = await asyncio.to_thread(_run)
        label, text = TACTICS[current]
        others = "\n".join(
            f"• **{lbl}** — {txt}" for code, (lbl, txt) in TACTICS.items() if code != current
        )
        embed = discord.Embed(
            title=f"🎯 Tactique : {label}",
            description=(
                f"{text}\n\n"
                + ("✅ Enregistrée. Elle s'appliquera dès ton prochain combat.\n\n"
                   if choix is not None else "")
                + f"**Autres tactiques**\n{others}\n\n"
                "Elle décide aujourd'hui de la cible du sort de soin (classe Soigneur). "
                "Elle ne change pas pendant un combat."
            ),
            color=discord.Color.teal(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StatsCog(bot))
