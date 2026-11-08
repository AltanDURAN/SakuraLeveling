"""Cog `/tour` : la tour solo (27/10/2026, décisions de l'auteur).

100 étages, les mêmes pour tous, 1 à 4 monstres par étage, un boss tous les
10. Seul, à PV et mana pleins, sans potion ni élixir. Une victoire garde le
ticket et fait avancer le record ; une défaite coûte le ticket, jamais un
étage. Règles : `tower_service` ; persistance : `use_cases/tower`.

Un essai se joue comme un combat de zone (08/11/2026, demande de l'auteur) :
un message « le combat s'engage », la VIDÉO du combat (`tower_fight_video`,
même file d'attente que les zones), puis le récapitulatif à trois pages
(`BattleSummaryView`) avec, s'il reste un ticket, le bouton de l'étage
suivant. Le panneau `/tour` n'est rafraîchi qu'après la vidéo (il dévoilerait
le résultat) ; un seul combat à la fois par joueur.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

import discord
from discord import app_commands
from discord.ext import commands

from app.application.use_cases import tower
from app.bot.cogs._mixins import BetaChannelOnlyMixin
from app.bot.embeds.tower_embeds import (
    build_daily_embed,
    build_status_embed,
    build_tower_summary,
    floor_title,
)
from app.bot.rendering.render_queue import video_slot
from app.bot.views.battle_summary_view import BattleSummaryView
from app.domain.services import tower_service as ts
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.tower import tower_loader
from app.shared.paths import GENERATED_ENCOUNTERS_DIR

_logger = logging.getLogger("sakura.tower")

BUSY = "⚔️ Ton combat se joue encore : regarde-le jusqu'au bout."


def _floor_image(floor_data: dict | None) -> discord.File | None:
    """Image de l'étage (la scène de sa vidéo : `tower_fight_video.floor_scene`),
    rendue une fois par étage puis gardée : elle est la même pour tous."""
    if not floor_data:
        return None
    from app.bot.rendering.fight_scene import compose_players_banner, has_mob_image
    from app.bot.rendering.tower_fight_video import floor_scene

    if not any(has_mob_image(e.get("image_name")) for e in floor_data["enemies"]):
        return None     # monstres sans image (zones récentes) : l'embed suffit
    name = f"tour_{floor_data['floor']}.png"
    path = GENERATED_ENCOUNTERS_DIR / name
    try:
        if not path.exists():
            compose_players_banner(players=[], output_path=str(path), **floor_scene(floor_data))
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


async def _reply(interaction: discord.Interaction, text: str) -> None:
    """Réponse privée, que l'interaction ait déjà été accusée ou non."""
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True)
    else:
        await interaction.response.send_message(text, ephemeral=True)


class TowerView(discord.ui.View):
    """Le panneau de `/tour`, réservé à celui qui l'a ouvert."""

    def __init__(self, cog: TowerCog, owner_id: int, state: tower.TowerStatus) -> None:
        super().__init__(timeout=1800)
        self.cog = cog
        self.owner_id = owner_id
        #: Le message du panneau, édité par le salon (aucun jeton qui expire).
        self.message: discord.Message | discord.PartialMessage | None = None
        self._sync(state)

    def _sync(self, state: tower.TowerStatus) -> None:
        fighting = self.cog.is_climbing(self.owner_id)
        self.climb.disabled = fighting or state.next_floor is None or state.tickets.available <= 0
        self.climb.label = ("Combat en cours…" if fighting else
                            f"Tenter l'étage {state.next_floor}" if state.next_floor else "Tour terminée")
        self.daily.disabled = fighting or state.daily_claimed or state.daily.is_empty

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Ouvre ta propre tour avec /tour.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        """Après le délai, les boutons ne répondent plus : autant les retirer."""
        await self._edit(view=None)

    async def _edit(self, **kwargs) -> None:
        if self.message is None:
            return
        try:
            await self.message.edit(**kwargs)
        except discord.HTTPException:
            _logger.warning("panneau de /tour non mis à jour", exc_info=True)

    async def busy(self) -> None:
        """Pendant un combat : ni second essai ni récompense (le panneau
        dévoilerait le résultat avant la fin de la vidéo)."""
        if self.is_finished():
            return                  # boutons déjà retirés (délai écoulé)
        self.climb.disabled = self.daily.disabled = True
        self.climb.label = "Combat en cours…"
        await self._edit(view=self)

    async def refresh(self, user) -> None:
        """Record, tickets, étage suivant : le panneau à jour."""
        state, name, names = await asyncio.to_thread(_status, user)
        self._sync(state)
        embed, image = await _status_message(state, name, names)
        await self._edit(embed=embed, attachments=[image] if image else [],
                         view=None if self.is_finished() else self)

    @discord.ui.button(label="Tenter l'étage", emoji="⚔️", style=discord.ButtonStyle.danger)
    async def climb(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.message = interaction.message
        await self.cog.climb(interaction, self)

    @discord.ui.button(label="Récompense du jour", emoji="🎁", style=discord.ButtonStyle.success)
    async def daily(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.message = interaction.message
        await interaction.response.defer()
        reward, error, best, names = await asyncio.to_thread(_claim, interaction.user)
        if error:
            await interaction.followup.send(error, ephemeral=True)
        else:
            await interaction.followup.send(embed=build_daily_embed(reward, best, names))
        await self.refresh(interaction.user)


class TowerSummaryView(BattleSummaryView):
    """Le récapitulatif d'un essai (les pages des combats de zone) et, s'il
    reste un ticket, l'étage suivant — sans remonter jusqu'au panneau."""

    def __init__(self, cog: TowerCog, summary, owner_id: int, next_floor: int | None,
                 tickets_left: int, panel: TowerView | None) -> None:
        super().__init__(summary, timeout=600.0)
        self.cog = cog
        self.owner_id = owner_id
        self.panel = panel
        if next_floor is None or tickets_left <= 0:
            self.remove_item(self.climb)
        else:
            self.climb.label = f"Tenter l'étage {next_floor}"

    @discord.ui.button(label="Tenter l'étage", emoji="⚔️", style=discord.ButtonStyle.danger, row=1)
    async def climb(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Ouvre ta propre tour avec /tour.", ephemeral=True)
            return
        if self.cog.is_climbing(self.owner_id):
            await interaction.response.send_message(BUSY, ephemeral=True)
            return
        button.disabled = True
        await interaction.response.edit_message(view=self)
        await self.cog.climb(interaction, self.panel)


class TowerCog(BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        #: Joueurs dont un combat se joue (vidéo comprise) : un seul à la fois.
        self.climbing: set[int] = set()

    def is_climbing(self, user_id: int) -> bool:
        return user_id in self.climbing

    @app_commands.command(name="tour", description="La tour solo : 100 étages, ton record, ta récompense du jour")
    async def tour(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        state, name, names = await asyncio.to_thread(_status, interaction.user)
        embed, image = await _status_message(state, name, names)
        view = TowerView(self, interaction.user.id, state)
        kwargs = {"file": image} if image else {}
        sent = await interaction.followup.send(embed=embed, view=view, wait=True, **kwargs)
        view.message = self._editable(interaction, sent)

    @staticmethod
    def _editable(interaction: discord.Interaction, sent):
        """Le message à éditer par le salon : le jeton d'une interaction expire
        au bout de 15 minutes, le message du bot, lui, reste à lui."""
        channel = interaction.channel
        return channel.get_partial_message(sent.id) if channel is not None else sent

    async def climb(self, interaction: discord.Interaction, panel: TowerView | None) -> None:
        """Un essai : le combat, sa vidéo, puis son récapitulatif."""
        user = interaction.user
        if user.id in self.climbing:
            await _reply(interaction, BUSY)
            return
        self.climbing.add(user.id)
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
            if panel is not None:
                await panel.busy()
            outcome, error, names = await asyncio.to_thread(_attempt, user)
            if error:
                await interaction.followup.send(error, ephemeral=True)
                return
            await self._play(interaction, outcome, names, panel)
        finally:
            self.climbing.discard(user.id)
            if panel is not None:
                await panel.refresh(user)

    async def _play(self, interaction: discord.Interaction, outcome: tower.TowerAttempt, names: dict,
                    panel: TowerView | None) -> None:
        """Le combat en vidéo puis son récapitulatif, dans un message à lui.
        Les récompenses sont déjà données : sans vidéo, le récapitulatif vient
        tout de suite."""
        title = floor_title(outcome)
        try:
            sent = await interaction.followup.send(embed=discord.Embed(
                title=f"⚔️ {title} — le combat s'engage", description="_Les coups pleuvent…_",
                color=discord.Color.orange()), wait=True)
        except discord.HTTPException:
            _logger.exception("combat de la tour non affiché (étage %s)", outcome.floor)
            return
        message = self._editable(interaction, sent)
        anim = await self._video(interaction.user, outcome)
        if anim is not None:
            embed = discord.Embed(title=f"⚔️ {title}", color=discord.Color.orange())
            embed.set_image(url=f"attachment://{anim.path.name}")
            try:
                await message.edit(embed=embed, attachments=[discord.File(anim.path, filename=anim.path.name)])
                await asyncio.sleep(anim.duration_s + 1.0)
            except discord.HTTPException:
                _logger.warning("vidéo de la tour non envoyée", exc_info=True)
            finally:
                anim.path.unlink(missing_ok=True)   # Discord garde sa copie

        nxt = ts.next_floor(outcome.best_floor)
        view = TowerSummaryView(self, build_tower_summary(outcome, names), interaction.user.id,
                                nxt if nxt and tower_loader.get_floor(nxt) else None,
                                outcome.tickets_left, panel)
        view.message = message
        try:
            await message.edit(embed=view.current_embed, attachments=[], view=view)
        except discord.HTTPException:
            _logger.exception("récapitulatif de la tour refusé par Discord")
            await interaction.followup.send(
                f"🗼 {title} : {'franchi' if outcome.victory else 'défaite'} — le récapitulatif n'a pas pu "
                "s'afficher, mais tout est compté (/tour, /profil).", ephemeral=True)

    @staticmethod
    async def _video(user, outcome: tower.TowerAttempt):
        """Le GIF du combat (même file que les zones), ou None : file trop
        longue, rendu impossible ou trop lourd."""
        from app.bot.rendering import tower_fight_video

        GENERATED_ENCOUNTERS_DIR.mkdir(parents=True, exist_ok=True)
        out = GENERATED_ENCOUNTERS_DIR / f"tour_{user.id}_{outcome.floor}_{uuid.uuid4().hex[:8]}.gif"
        avatar = user.display_avatar.replace(size=128).url
        try:
            async with video_slot() as granted:
                if not granted:
                    _logger.warning("file des vidéos trop longue : étage sans vidéo")
                    return None
                return await asyncio.to_thread(tower_fight_video.render_tower_video,
                                               outcome.floor_data, outcome.result, avatar, out)
        except Exception:
            _logger.exception("vidéo de la tour échouée")
            out.unlink(missing_ok=True)
            return None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TowerCog(bot))
