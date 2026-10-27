"""Cog `/tour` : la tour solo (27/10/2026, décisions de l'auteur).

100 étages, les mêmes pour tous, 1 à 4 monstres par étage, un boss tous les
10. Seul, à PV et mana pleins, sans potion ni élixir. Une victoire garde le
ticket et fait avancer le record ; une défaite coûte le ticket, jamais un
étage. Règles : `tower_service` ; persistance : `use_cases/tower`.
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from app.application.use_cases import tower
from app.bot.cogs._mixins import BetaChannelOnlyMixin
from app.bot.embeds.tower_embeds import build_attempt_embed, build_daily_embed, build_status_embed
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.tower import tower_loader

_logger = logging.getLogger("sakura.tower")


def _floor_image(floor_data: dict | None) -> discord.File | None:
    """Image de l'étage (ses monstres dans le décor de la famille du premier),
    rendue une fois par étage puis gardée : elle est la même pour tous."""
    if not floor_data:
        return None
    from app.bot.rendering.fight_scene import compose_players_banner, has_mob_image
    from app.infrastructure.encounters import (
        farm_zone_loader,
        mob_formation_loader,
        mob_placement_loader,
    )
    from app.shared.paths import GENERATED_ENCOUNTERS_DIR, LANDSCAPES_ASSETS_DIR

    if not any(has_mob_image(e.get("image_name")) for e in floor_data["enemies"]):
        return None     # monstres sans image (zones récentes) : l'embed suffit
    name = f"tour_etage_{floor_data['floor']}.png"
    path = GENERATED_ENCOUNTERS_DIR / name
    try:
        if not path.exists():
            enemies = floor_data["enemies"]
            payloads = [{"code": e["code"], "name": e["name"], "image_name": e.get("image_name", ""),
                         "element": e.get("element", ""), "current_hp": e["max_hp"], "max_hp": e["max_hp"],
                         "attack": e["attack"], "defense": e["defense"], "speed": e["speed"]}
                        for e in enemies]
            first = enemies[0]
            channel = farm_zone_loader.get_spawn_channel_for_family(first.get("family"))
            spot = farm_zone_loader.get_spot(channel, first.get("element", "")) if first.get("element") else None
            background = farm_zone_loader.get_background_for_family(first.get("family"))
            placements = [mob_placement_loader.get_placement(e["code"], e.get("element", "")) for e in enemies]
            kwargs = ({"mob": payloads[0], "placement": placements[0]} if len(payloads) == 1 else
                      {"mob": None, "mobs": payloads, "placements": placements,
                       "formation": mob_formation_loader.get_formation(str(channel), len(payloads))})
            compose_players_banner(players=[], output_path=str(path),
                                   background_path=str(LANDSCAPES_ASSETS_DIR / background) if background else None,
                                   spot=spot, **kwargs)
        return discord.File(path, filename=name)
    except Exception:  # noqa: BLE001 — l'image est un plus, jamais un blocage
        _logger.warning("rendu de l'étage %s échoué", floor_data.get("floor"), exc_info=True)
        return None


def _material_names(session) -> dict[str, str]:
    """Noms des matériaux de fusion des étages (pour l'affichage)."""
    codes = {tower_loader.floor_material(f) for f in range(1, tower_loader.floor_count() + 1)}
    items = ItemRepository(session)
    names = {}
    for code in filter(None, codes):
        item = items.get_by_code(code)
        if item is not None:
            names[code] = item.name
    return names


def _profile(session, user):
    return PlayerRepository(session).get_or_create_by_discord_id(
        discord_id=user.id, username=user.name, display_name=user.display_name,
    )


def _status(user):
    with get_db_session() as session:
        profile = _profile(session, user)
        state = tower.status(session, profile)
        return state, profile.player.display_name, _material_names(session)


def _attempt(user):
    with get_db_session() as session:
        profile = _profile(session, user)
        try:
            outcome = tower.attempt(session, profile)
        except tower.TowerError as e:
            return None, str(e), {}
        return outcome, None, _material_names(session)


def _claim(user):
    with get_db_session() as session:
        profile = _profile(session, user)
        try:
            reward = tower.claim_daily(session, profile)
        except tower.TowerError as e:
            return None, str(e), 0, {}
        best = tower.status(session, profile).best_floor
        return reward, None, best, _material_names(session)


async def _status_message(state, name, names) -> tuple[discord.Embed, discord.File | None]:
    embed = build_status_embed(state, name, names)
    image = await asyncio.to_thread(_floor_image, state.floor)
    if image is not None:
        embed.set_image(url=f"attachment://{image.filename}")
    return embed, image


class TowerView(discord.ui.View):
    """Boutons de `/tour`, réservés à celui qui a ouvert la tour."""

    def __init__(self, owner_id: int, state: tower.TowerStatus) -> None:
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self._sync(state)

    def _sync(self, state: tower.TowerStatus) -> None:
        self.climb.disabled = state.next_floor is None or state.tickets.available <= 0
        self.climb.label = (f"Tenter l'étage {state.next_floor}" if state.next_floor else "Tour terminée")
        self.daily.disabled = state.daily_claimed or state.daily.is_empty

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Ouvre ta propre tour avec /tour.", ephemeral=True)
            return False
        return True

    async def _refresh(self, interaction: discord.Interaction) -> None:
        state, name, names = await asyncio.to_thread(_status, interaction.user)
        self._sync(state)
        embed, image = await _status_message(state, name, names)
        try:
            await interaction.message.edit(embed=embed, view=self,
                                           attachments=[image] if image else [])
        except discord.HTTPException:
            _logger.warning("rafraîchissement de /tour échoué", exc_info=True)

    @discord.ui.button(label="Tenter l'étage", emoji="⚔️", style=discord.ButtonStyle.danger)
    async def climb(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        outcome, error, names = await asyncio.to_thread(_attempt, interaction.user)
        if error:
            await interaction.followup.send(error, ephemeral=True)
        else:
            await interaction.followup.send(embed=build_attempt_embed(outcome, names))
        await self._refresh(interaction)

    @discord.ui.button(label="Récompense du jour", emoji="🎁", style=discord.ButtonStyle.success)
    async def daily(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        reward, error, best, names = await asyncio.to_thread(_claim, interaction.user)
        if error:
            await interaction.followup.send(error, ephemeral=True)
        else:
            await interaction.followup.send(embed=build_daily_embed(reward, best, names))
        await self._refresh(interaction)


class TowerCog(BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="tour", description="La tour solo : 100 étages, ton record, ta récompense du jour")
    async def tour(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        state, name, names = await asyncio.to_thread(_status, interaction.user)
        embed, image = await _status_message(state, name, names)
        kwargs = {"file": image} if image else {}
        await interaction.followup.send(embed=embed, view=TowerView(interaction.user.id, state), **kwargs)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TowerCog(bot))
