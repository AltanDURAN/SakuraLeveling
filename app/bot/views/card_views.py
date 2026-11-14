"""Vues des cartes à collectionner : les boutons d'ouverture (persistants :
sous le guide épinglé et sous chaque ouverture — n'importe qui peut cliquer
« Encore un » sous les cartes d'un autre), l'album page par page et la
fiche d'une carte (fabriquer)."""

from __future__ import annotations

import asyncio
import io

import discord

from app.bot.views._base import ExpiringView

from app.bot.rules_gate import GatedView
from app.domain.services import card_service as cs
from app.infrastructure.cards import card_loader
from app.shared.formatters import format_int

OPEN_PREFIX = "cards:open:"
ALBUM_ID = "cards:album"


def _cog(interaction: discord.Interaction):
    return interaction.client.get_cog("CardsCog")


def _emoji(text: str) -> str | None:
    """L'emoji d'un chapitre (réglé sur le site) seulement s'il en a l'air :
    Discord refuse tout le menu pour un emoji invalide."""
    text = (text or "").strip()
    looks = any(0x1F000 <= ord(ch) <= 0x1FAFF or 0x2600 <= ord(ch) <= 0x27BF or 0x2B00 <= ord(ch) <= 0x2BFF
                for ch in text)
    return text if text and looks and all(ord(ch) > 0x2000 for ch in text) else None


class BoosterButtons(GatedView):
    """Ouvrir 1, 5 ou 10 boosters, ou voir son album. Persistants. Le prix
    affiché suit les réglages (relu à chaque message)."""

    def __init__(self) -> None:
        super().__init__(timeout=None)
        try:
            price = card_loader.params().booster_price
        except Exception:  # noqa: BLE001 - un contenu illisible n'empêche pas les boutons
            price = cs.BOOSTER_PRICE
        self.open_one.label = f"Ouvrir un booster · {format_int(price)} or"

    @discord.ui.button(label="Ouvrir un booster", emoji="🎴",
                       style=discord.ButtonStyle.success, custom_id=f"{OPEN_PREFIX}1")
    async def open_one(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _cog(interaction).open_boosters(interaction, 1)

    @discord.ui.button(label="×5", style=discord.ButtonStyle.primary, custom_id=f"{OPEN_PREFIX}5")
    async def open_five(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _cog(interaction).open_boosters(interaction, 5)

    @discord.ui.button(label="×10", style=discord.ButtonStyle.primary, custom_id=f"{OPEN_PREFIX}10")
    async def open_ten(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _cog(interaction).open_boosters(interaction, 10)

    @discord.ui.button(label="Mon album", emoji="📖", style=discord.ButtonStyle.secondary, custom_id=ALBUM_ID)
    async def album(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _cog(interaction).show_album(interaction, interaction.user, ephemeral=True)


class AlbumView(ExpiringView):
    """L'album : une page par chapitre, réservé à celui qui l'a ouvert. Le
    propriétaire peut recycler ses doublons et fabriquer une carte."""

    def __init__(self, cog, *, viewer_id: int, player_id: int, owner: str, own: bool, coll,
                 chapter: int = 0) -> None:
        super().__init__(timeout=600)
        self.cog = cog
        self.viewer_id = viewer_id
        self.player_id = player_id
        self.owner = owner
        self.own = own
        self.coll = coll
        self.chapters = [c.code for c in card_loader.chapters() if any(card.chapter == c.code for card in coll.cards)]
        self.index = max(0, min(chapter, len(self.chapters) - 1))
        self.message: discord.Message | None = None
        self._build()

    @property
    def chapter(self) -> str:
        return self.chapters[self.index]

    def chapter_cards(self) -> list[cs.CardDef]:
        return [c for c in self.coll.cards if c.chapter == self.chapter]

    # -------------------------------------------------------------- vue --
    def _build(self) -> None:
        self.clear_items()
        prev = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary, row=0, disabled=self.index == 0)
        prev.callback = self._prev
        counter = discord.ui.Button(label=f"{self.index + 1} / {len(self.chapters)}", disabled=True, row=0,
                                    style=discord.ButtonStyle.primary)
        nxt = discord.ui.Button(label="▶", style=discord.ButtonStyle.secondary, row=0,
                                disabled=self.index >= len(self.chapters) - 1)
        nxt.callback = self._next
        for item in (prev, counter, nxt):
            self.add_item(item)
        if self.own and self.coll.duplicates:
            recycle = discord.ui.Button(label=f"Recycler ({format_int(self.coll.duplicate_petals)} pétales)",
                                        emoji="♻️", style=discord.ButtonStyle.secondary, row=0)
            recycle.callback = self._recycle
            self.add_item(recycle)
        chapters = discord.ui.Select(placeholder="Aller au chapitre…", row=1, options=[
            discord.SelectOption(label=card_loader.get_chapter(code).name[:100], value=str(i),
                                 emoji=_emoji(card_loader.get_chapter(code).emoji), default=i == self.index)
            for i, code in enumerate(self.chapters)][:25])
        chapters.callback = self._goto
        self.add_item(chapters)
        cards = discord.ui.Select(placeholder="Voir une carte…", row=2, options=[
            discord.SelectOption(
                label=f"#{c.number:02d} {c.name}"[:100], value=c.code,
                emoji=cs.CARD_RARITY_EMOJIS.get(c.rarity),
                description=(cs.RARITY_LABELS.get(c.rarity, "") + (" · à toi" if self.coll.owns(c.code) else ""))[:100])
            for c in self.chapter_cards()][:25])
        cards.callback = self._show_card
        self.add_item(cards)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.viewer_id:
            await interaction.response.send_message("❌ Cet album ne t'est pas destiné : tape `/album`.",
                                                    ephemeral=True)
            return False
        return True

    async def render(self) -> tuple[discord.Embed, discord.File]:
        return await self.cog.album_page(self)

    async def _refresh(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        self._build()
        embed, file = await self.render()
        await interaction.edit_original_response(embed=embed, attachments=[file], view=self)

    async def _prev(self, interaction: discord.Interaction) -> None:
        self.index = max(0, self.index - 1)
        await self._refresh(interaction)

    async def _next(self, interaction: discord.Interaction) -> None:
        self.index = min(len(self.chapters) - 1, self.index + 1)
        await self._refresh(interaction)

    async def _goto(self, interaction: discord.Interaction) -> None:
        self.index = int(interaction.data["values"][0])
        await self._refresh(interaction)

    async def _show_card(self, interaction: discord.Interaction) -> None:
        await self.cog.show_card(interaction, self, interaction.data["values"][0])

    async def _recycle(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            f"♻️ Recycler **{self.coll.duplicates}** doublon(s) contre **{format_int(self.coll.duplicate_petals)}** "
            "pétales ? Tu gardes un exemplaire de chaque carte (et de chaque brillante). Pense à garder ceux "
            "que tu veux échanger.",
            view=ConfirmRecycle(self), ephemeral=True)

    async def reload(self) -> None:
        """Relit la collection et redessine le message de l'album."""
        self.coll = await asyncio.to_thread(self.cog.load_collection, self.player_id)
        self._build()
        if self.message is not None:
            embed, file = await self.render()
            try:
                await self.message.edit(embed=embed, attachments=[file], view=self)
            except discord.HTTPException:
                pass


class ConfirmRecycle(ExpiringView):
    def __init__(self, album: AlbumView) -> None:
        super().__init__(timeout=120)
        self.album = album

    @discord.ui.button(label="Recycler", emoji="♻️", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        result = await asyncio.to_thread(self.album.cog.recycle, self.album.player_id)
        text = (f"♻️ **{result.cards}** carte(s) recyclée(s) : +**{format_int(result.petals)}** pétales "
                f"(tu en as {format_int(result.petals_total)})." if result.cards else "Aucun doublon à recycler.")
        await interaction.response.edit_message(content=text, view=None)
        await self.album.reload()

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Rien n'a été recyclé.", view=None)


class CraftView(ExpiringView):
    """« Fabriquer » sous la fiche d'une carte qui manque."""

    def __init__(self, album: AlbumView, card: cs.CardDef) -> None:
        super().__init__(timeout=300)
        self.album = album
        self.card = card
        cost = cs.craft_cost(card.rarity, album.coll.params)
        self.craft.label = f"Fabriquer · {format_int(cost)} pétales"
        self.craft.disabled = album.coll.petals < cost

    @discord.ui.button(label="Fabriquer", emoji="🌸", style=discord.ButtonStyle.success)
    async def craft(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        result = await asyncio.to_thread(self.album.cog.craft, self.album.player_id, self.card.code)
        text = result.message
        if result.titles:
            text += "\n🏷️ Nouveau titre : " + ", ".join(result.titles)
        await interaction.response.edit_message(content=text, view=None)
        if result.ok:
            await self.album.reload()


def file_from(data: bytes, filename: str) -> discord.File:
    return discord.File(io.BytesIO(data), filename=filename)
