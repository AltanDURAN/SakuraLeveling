"""Cog des cartes à collectionner (09/11/2026, demande de l'auteur) : les
boosters de Sorn s'ouvrent EN PUBLIC dans le salon des cartes (« gambling
addict »), l'album se consulte partout où les commandes sont permises.

  • `/booster [nombre]` (salon des cartes) et les boutons du guide épinglé ou
    de chaque ouverture : achète et ouvre — le premier booster est offert ;
  • l'ouverture se joue en GIF (les cartes se retournent, la plus rare en
    dernier), puis le message garde l'image fixe du résultat ;
  • la mythique est annoncée dans le salon général ;
  • `/album [joueur]` : la collection page par page (silhouettes des cartes
    manquantes), recycler ses doublons, fabriquer une carte.

Règles : `card_service` ; écritures : `use_cases/cards` (atomiques).
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from app.application.use_cases import cards as cards_uc
from app.bot.embeds import card_embeds
from app.bot.rendering import card_render
from app.bot.views.card_views import AlbumView, BoosterButtons, CraftView, file_from
from app.domain.services import card_service as cs
from app.infrastructure.cards import card_loader
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session

_logger = logging.getLogger("sakura.cards")
RESULT_FILE = "booster.png"
ANIMATION_FILE = "ouverture.gif"
#: Rendus d'ouverture en même temps (mémoire du serveur).
RENDERS = 2


class CardsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bot.add_view(BoosterButtons())
        self._locks: dict[int, asyncio.Lock] = {}
        self._renders = asyncio.Semaphore(RENDERS)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        allowed = set(settings.command_channel_ids)
        if settings.gambling_channel_id:
            allowed.add(settings.gambling_channel_id)
        if interaction.channel_id in allowed:
            return True
        where = f"<#{settings.gambling_channel_id}>" if settings.gambling_channel_id else "un salon de commandes"
        await interaction.response.send_message(f"🚧 Pas ici : les cartes, c'est dans {where}.", ephemeral=True)
        return False

    # ------------------------------------------------------------ base --
    def _player_id(self, user) -> int:
        with get_db_session() as session:
            profile = PlayerRepository(session).get_or_create_by_discord_id(
                discord_id=user.id, username=user.name, display_name=user.display_name)
            return profile.player.id

    def load_collection(self, player_id: int) -> cards_uc.Collection:
        with get_db_session() as session:
            return cards_uc.collection(session, player_id)

    def recycle(self, player_id: int) -> cards_uc.RecycleResult:
        with get_db_session() as session:
            return cards_uc.recycle_duplicates(session, player_id)

    def craft(self, player_id: int, code: str) -> cards_uc.CraftResult:
        with get_db_session() as session:
            return cards_uc.craft_card(session, player_id, code)

    def _open_db(self, user, count: int) -> cards_uc.BoosterResult:
        player_id = self._player_id(user)
        with get_db_session() as session:
            return cards_uc.open_boosters(session, player_id, count)

    # -------------------------------------------------------- boosters --
    @app_commands.command(name="booster", description="Ouvre des boosters de cartes chez Sorn (salon des cartes)")
    @app_commands.describe(nombre="Combien de boosters d'un coup (1 à 10)")
    async def booster(self, interaction: discord.Interaction,
                      nombre: app_commands.Range[int, 1, cards_uc.MAX_BOOSTERS] = 1) -> None:
        await self.open_boosters(interaction, nombre)

    async def open_boosters(self, interaction: discord.Interaction, count: int) -> None:
        channel_id = settings.gambling_channel_id
        if channel_id and interaction.channel_id != channel_id:
            await interaction.response.send_message(
                f"🎴 Les boosters s'ouvrent devant tout le monde, dans <#{channel_id}>.", ephemeral=True)
            return
        lock = self._locks.setdefault(interaction.user.id, asyncio.Lock())
        if lock.locked():
            await interaction.response.send_message("⏳ Ton booster précédent s'ouvre encore…", ephemeral=True)
            return
        async with lock:
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                result = await asyncio.to_thread(self._open_db, interaction.user, count)
            except Exception:  # noqa: BLE001
                _logger.exception("ouverture de booster impossible")
                await interaction.edit_original_response(content="❌ Le booster n'a pas pu être ouvert. Réessaie.")
                return
            if not result.ok:
                await interaction.edit_original_response(content=result.message)
                return
            await self._show_opening(interaction, result)

    async def _show_opening(self, interaction: discord.Interaction, result: cards_uc.BoosterResult) -> None:
        name = interaction.user.display_name
        embed = card_embeds.build_result_embed(name, result)
        single = len(result.boosters) == 1
        async with self._renders:
            if single:
                gif = await asyncio.to_thread(card_render.animate_booster, result.cards)
                still = await asyncio.to_thread(card_render.compose_booster_result, result.cards)
            else:
                gif, still = None, await asyncio.to_thread(card_render.compose_many, result.cards)
        best = result.best
        content = None
        if best and best.card.rarity in cs.TOP_RARITIES:
            content = (f"{cs.CARD_RARITY_EMOJIS[best.card.rarity]} **{cs.RARITY_LABELS[best.card.rarity].upper()} !** "
                       f"{interaction.user.mention}")
        channel = interaction.channel
        embed.set_image(url=f"attachment://{ANIMATION_FILE if gif else RESULT_FILE}")
        file = file_from(gif, ANIMATION_FILE) if gif else file_from(still, RESULT_FILE)
        try:
            message = await channel.send(content=content, embed=embed, file=file, view=BoosterButtons(),
                                         allowed_mentions=discord.AllowedMentions(users=False))
        except discord.HTTPException:
            _logger.warning("résultat de booster non posté", exc_info=True)
            await interaction.edit_original_response(
                content="🎴 Tes cartes sont dans ton album (`/album`) : le salon a refusé le message.")
            return
        try:
            await interaction.delete_original_response()
        except discord.HTTPException:
            pass
        if best and best.card.rarity == "mythic":
            await self._announce_mythic(interaction.user, best.card)
        if gif:
            await asyncio.sleep(card_render.animation_seconds(result.cards))
            embed.set_image(url=f"attachment://{RESULT_FILE}")
            try:
                await message.edit(embed=embed, attachments=[file_from(still, RESULT_FILE)])
            except discord.HTTPException:
                pass

    async def _announce_mythic(self, user, card: cs.CardDef) -> None:
        channel_id = settings.rank_announce_channel_id
        channel = self.bot.get_channel(channel_id) if channel_id else None
        if channel is None:
            return
        embed = card_embeds.build_mythic_announcement(user.mention, card, settings.gambling_channel_id)
        embed.set_image(url="attachment://mythique.png")
        png = await asyncio.to_thread(card_render.card_png, card, True)
        try:
            await channel.send(embed=embed, file=file_from(png, "mythique.png"))
        except discord.HTTPException:
            _logger.warning("annonce de la mythique impossible", exc_info=True)

    # ----------------------------------------------------------- album --
    @app_commands.command(name="album", description="Ton album de cartes à collectionner (ou celui d'un joueur)")
    @app_commands.describe(joueur="Voir l'album d'un autre joueur")
    async def album(self, interaction: discord.Interaction, joueur: discord.Member | None = None) -> None:
        await self.show_album(interaction, joueur or interaction.user, ephemeral=False)

    def _album_data(self, user, own: bool):
        with get_db_session() as session:
            players = PlayerRepository(session)
            profile = (players.get_or_create_by_discord_id(discord_id=user.id, username=user.name,
                                                           display_name=user.display_name)
                       if own else players.get_by_discord_id(user.id))
            if profile is None:
                return None, None, []
            titles = cards_uc.refresh_titles(session, profile.player.id) if own else []
            return profile.player.id, cards_uc.collection(session, profile.player.id), titles

    async def show_album(self, interaction: discord.Interaction, user, *, ephemeral: bool) -> None:
        own = user.id == interaction.user.id
        await interaction.response.defer(ephemeral=ephemeral)
        player_id, coll, titles = await asyncio.to_thread(self._album_data, user, own)
        if coll is None:
            await interaction.followup.send(f"❌ {user.display_name} n'a pas encore de profil.", ephemeral=True)
            return
        view = AlbumView(self, viewer_id=interaction.user.id, player_id=player_id,
                         owner=user.display_name, own=own, coll=coll, chapter=self._first_chapter(coll))
        embed, file = await self.album_page(view)
        content = ("🏷️ Nouveau titre : " + ", ".join(titles)) if titles else None
        view.message = await interaction.followup.send(content=content, embed=embed, file=file, view=view,
                                                       ephemeral=ephemeral, wait=True)

    @staticmethod
    def _first_chapter(coll: cards_uc.Collection) -> int:
        """La première page où il manque une carte (sinon la première)."""
        chapters = [c.code for c in card_loader.chapters() if any(card.chapter == c.code for card in coll.cards)]
        for index, code in enumerate(chapters):
            if any(c.chapter == code and not coll.owns(c.code) for c in coll.cards):
                return index
        return 0

    async def album_page(self, view: AlbumView) -> tuple[discord.Embed, discord.File]:
        coll, chapter = view.coll, view.chapter
        cards = view.chapter_cards()
        owned = sum(1 for c in cards if coll.owns(c.code))
        shiny = sum(1 for c in cards if coll.brillante.get(c.code))
        subtitle = f"{owned}/{len(cards)} cartes · {shiny} brillante(s)"
        png = await asyncio.to_thread(card_render.compose_album_page, cards, coll.normal, coll.brillante,
                                      card_loader.get_chapter(chapter).name, subtitle)
        embed = card_embeds.build_album_embed(view.owner, coll, chapter, view.index + 1, len(view.chapters),
                                              own=view.own)
        return embed, file_from(png, card_embeds.ALBUM_FILE)

    async def show_card(self, interaction: discord.Interaction, view: AlbumView, code: str) -> None:
        card = card_loader.get_card(code)
        if card is None:
            await interaction.response.send_message("❌ Carte inconnue.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        coll = view.coll
        animated = card.always_brillante or bool(coll.brillante.get(code))
        if animated:
            data = await asyncio.to_thread(card_render.card_gif, card)
        else:
            data = await asyncio.to_thread(card_render.card_png, card, False)
        embed = card_embeds.build_card_embed(card, coll, own=view.own)
        kwargs = {}
        if view.own and not coll.owns(code) and cs.craftable(card):
            kwargs["view"] = CraftView(view, card)
        await interaction.followup.send(embed=embed, file=file_from(data, "carte." + ("gif" if animated else "png")),
                                        ephemeral=True, **kwargs)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CardsCog(bot))
