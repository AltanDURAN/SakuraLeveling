"""Vues des événements saisonniers (décembre 2026) : les boutons du panneau
épinglé (persistants), le calendrier de l'Avent, le cadeau de Noël et les
boutiques d'événement (écrans privés)."""

from __future__ import annotations

import discord

from app.bot.rules_gate import GatedView
from app.shared.formatters import format_int

ADVENT_ID = "seasonal:advent"
GIFT_ID = "seasonal:gift"
SHOP_ID = "seasonal:shop"


def _cog(interaction: discord.Interaction):
    return interaction.client.get_cog("SeasonalCog")


async def _unavailable(interaction: discord.Interaction) -> None:
    await interaction.response.send_message("⏳ Les événements redémarrent, réessaie dans un instant.",
                                            ephemeral=True)


class SeasonalPanelView(GatedView):
    """Boutons du panneau épinglé et des annonces (persistants : ils marchent
    après un redémarrage). `buttons` : ceux à montrer (tous par défaut —
    c'est la vue enregistrée au démarrage)."""

    def __init__(self, buttons: tuple[str, ...] = ("advent", "gift", "shop"), shop_label: str = "Boutique") -> None:
        super().__init__(timeout=None)
        wanted = set(buttons)
        if "advent" not in wanted:
            self.remove_item(self.advent)
        if "gift" not in wanted:
            self.remove_item(self.gift)
        if "shop" not in wanted:
            self.remove_item(self.shop)
        else:
            self.shop.label = shop_label[:80]

    @discord.ui.button(label="Calendrier de l'Avent", emoji="🎄", style=discord.ButtonStyle.danger,
                       custom_id=ADVENT_ID)
    async def advent(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cog = _cog(interaction)
        await (cog.show_advent(interaction) if cog else _unavailable(interaction))

    @discord.ui.button(label="Mon cadeau de Noël", emoji="🎅", style=discord.ButtonStyle.success,
                       custom_id=GIFT_ID)
    async def gift(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cog = _cog(interaction)
        await (cog.show_gift(interaction) if cog else _unavailable(interaction))

    @discord.ui.button(label="Boutique", emoji="🎁", style=discord.ButtonStyle.primary, custom_id=SHOP_ID)
    async def shop(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cog = _cog(interaction)
        await (cog.show_shop(interaction) if cog else _unavailable(interaction))


class _OwnedView(discord.ui.View):
    """Écran privé : seul celui qui l'a ouvert s'en sert."""

    def __init__(self, cog, user_id: int, timeout: float = 300) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Cet écran ne t'est pas destiné.", ephemeral=True)
            return False
        return True


class AdventView(_OwnedView):
    def __init__(self, cog, user_id: int, status) -> None:
        super().__init__(cog, user_id)
        day = status.today_day
        if status.can_open:
            self.open_door.label = f"Ouvrir la case {day}"
        else:
            self.remove_item(self.open_door)

    @discord.ui.button(label="Ouvrir la case", emoji="🎁", style=discord.ButtonStyle.success)
    async def open_door(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.open_advent(interaction)


class GiftView(_OwnedView):
    def __init__(self, cog, user_id: int, status) -> None:
        super().__init__(cog, user_id)
        if not (status.open and not status.claimed):
            self.remove_item(self.open_gift)

    @discord.ui.button(label="Ouvrir mon cadeau", emoji="🎁", style=discord.ButtonStyle.success)
    async def open_gift(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.open_gift(interaction)


class ShopView(_OwnedView):
    """Choisir un article, puis ×1 / ×5 / le maximum."""

    def __init__(self, cog, user_id: int, status, selected: str | None = None) -> None:
        super().__init__(cog, user_id, timeout=600)
        self.status = status
        offers = list(status.shop.offers)
        self.selected = selected if selected in {o.item for o in offers} else (offers[0].item if offers else None)
        if not status.open or not offers:
            for item in (self.pick, self.one, self.five, self.max):
                self.remove_item(item)
            return
        self.pick.options = [
            discord.SelectOption(
                label=status.names.get(o.item, o.item)[:100], value=o.item, default=o.item == self.selected,
                description=(f"{format_int(o.price)} × {status.currency_name}"
                             + (f" · limite {status.bought.get(o.item, 0)}/{o.limit}" if o.limit else ""))[:100])
            for o in offers][:25]
        offer = status.shop.offer(self.selected)
        left = status.left(offer) if offer else 0
        self.one.disabled = left < 1
        self.five.disabled = left < 5
        self.max.disabled = left < 1
        self.max.label = f"Max ({left})" if left else "Max"

    @discord.ui.select(placeholder="Choisis un article…", row=0)
    async def pick(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        await self.cog.show_shop(interaction, self.status.shop.code, selected=select.values[0], edit=True)

    async def _buy(self, interaction: discord.Interaction, quantity: int) -> None:
        await self.cog.buy(interaction, self.status.shop.code, self.selected, quantity)

    @discord.ui.button(label="Acheter ×1", style=discord.ButtonStyle.success, row=1)
    async def one(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._buy(interaction, 1)

    @discord.ui.button(label="×5", style=discord.ButtonStyle.secondary, row=1)
    async def five(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._buy(interaction, 5)

    @discord.ui.button(label="Max", style=discord.ButtonStyle.secondary, row=1)
    async def max(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        offer = self.status.shop.offer(self.selected)
        await self._buy(interaction, self.status.left(offer) if offer else 0)
