"""Papier élémentaire : choisir un élément, lire son talent caché.

Ouvert depuis `/marchand` (Sorn le vend) et depuis `/affinites`. Toujours en
message éphémère : c'est une information personnelle, et le prix monte à
chaque papier — on demande donc une confirmation explicite avant de payer.
"""

from __future__ import annotations

import asyncio

import discord

from app.application.use_cases.reveal_element_talent import (
    RevealElementTalentUseCase,
    RevealResult,
)
from app.infrastructure.artisans import artisan_loader
from app.shared.enums import ELEMENT_EMOJIS, ELEMENT_LABELS
from app.shared.formatters import format_int


def paper_price_label(price: int | None) -> str:
    if price is None:
        return "tous tes talents sont connus"
    return "gratuit" if price == 0 else f"{format_int(price)} or"


def describe_talent(talent) -> str:
    """Texte joueur d'un talent découvert."""
    if talent.dead:
        return (
            "💀 **Élément mort.** Ton corps ne capte rien de cet élément : "
            "aucune essence ne te viendra cette saison, et tu ne pourras pas "
            "l'utiliser en combat."
        )
    text = (
        f"Talent **{talent.talent}** → **+{talent.essence_bonus_pct} %** d'essences "
        f"de cet élément à chaque monstre vaincu."
    )
    if talent.boosts:
        text += (
            f"\n✨ **Don rare !** Ton affinité pourra monter jusqu'à "
            f"**{talent.cap}** au lieu de 100."
        )
    return text


def _prices() -> tuple[int, ...]:
    return artisan_loader.get_merchant().element_paper_prices


def load_status(session_factory, player_id: int):
    with session_factory() as session:
        return RevealElementTalentUseCase(session, _prices()).status(player_id)


async def open_paper_picker(
    interaction: discord.Interaction, session_factory, player_id: int,
) -> None:
    """Répond (éphémère) avec le choix de l'élément à révéler."""
    status = await asyncio.to_thread(load_status, session_factory, player_id)
    if status.next_price is None:
        await interaction.response.send_message(
            "📜 Tu connais déjà tes 8 talents élémentaires.", ephemeral=True,
        )
        return
    view = ElementPaperView(session_factory, player_id, status)
    await interaction.response.send_message(
        embed=view.embed(), view=view, ephemeral=True,
    )


class ElementPaperView(discord.ui.View):
    def __init__(self, session_factory, player_id: int, status, timeout: float = 180.0):
        super().__init__(timeout=timeout)
        self._session_factory = session_factory
        self.player_id = player_id
        self.status = status
        self.element: str | None = None
        self._build()

    def _build(self) -> None:
        self.clear_items()
        self.add_item(_ElementSelect(self))
        self.add_item(_ReadButton(self))

    def embed(self) -> discord.Embed:
        price = self.status.next_price
        known = 8 - len(self.status.unrevealed)
        embed = discord.Embed(
            title="📜 Papier élémentaire",
            description=(
                "Un papier sensible au chakra élémentaire : tiens-le entre tes "
                "doigts et il réagit à ta nature profonde. Il révèle ton "
                "**talent** dans l'élément choisi — la vitesse à laquelle tu en "
                "récoltes les essences. Certains éléments te sont peut-être "
                "fermés… d'autres plus généreux que tu ne l'imagines.\n\n"
                f"Talents découverts : **{known}/8**\n"
                f"Prix de ce papier : **{paper_price_label(price)}** "
                f"(ta bourse : {format_int(self.status.gold)} or)\n"
                "Chaque papier coûte plus cher que le précédent."
            ),
            color=discord.Color.from_rgb(150, 106, 200),
        )
        if self.element:
            embed.add_field(
                name="Élément choisi",
                value=f"{ELEMENT_EMOJIS.get(self.element, '')} "
                      f"{ELEMENT_LABELS.get(self.element, self.element)}",
            )
        return embed

    @property
    def can_read(self) -> bool:
        price = self.status.next_price
        return (
            self.element is not None and price is not None
            and self.status.gold >= price
        )


class _ElementSelect(discord.ui.Select):
    def __init__(self, view: ElementPaperView) -> None:
        options = [
            discord.SelectOption(
                label=ELEMENT_LABELS.get(code, code),
                value=code,
                emoji=ELEMENT_EMOJIS.get(code),
                description="Talent inconnu ❓",
                default=(code == view.element),
            )
            for code in view.status.unrevealed
        ]
        super().__init__(placeholder="Choisis l'élément à révéler", options=options, row=0)
        self._owner = view

    async def callback(self, interaction: discord.Interaction) -> None:
        self._owner.element = self.values[0]
        self._owner._build()
        await interaction.response.edit_message(
            embed=self._owner.embed(), view=self._owner,
        )


class _ReadButton(discord.ui.Button):
    def __init__(self, view: ElementPaperView) -> None:
        price = view.status.next_price
        super().__init__(
            label=f"Lire le papier ({paper_price_label(price)})",
            emoji="📜",
            style=discord.ButtonStyle.success,
            disabled=not view.can_read,
            row=1,
        )
        self._owner = view

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self._owner
        element = parent.element
        if element is None:
            await interaction.response.defer()
            return

        def _run() -> RevealResult:
            with parent._session_factory() as session:
                return RevealElementTalentUseCase(session, _prices()).execute(
                    parent.player_id, element,
                )

        result = await asyncio.to_thread(_run)
        if not result.success:
            await interaction.response.send_message(f"❌ {result.message}", ephemeral=True)
            return

        for child in parent.children:
            child.disabled = True
        parent.stop()
        label = f"{ELEMENT_EMOJIS.get(element, '')} {ELEMENT_LABELS.get(element, element)}"
        talent = result.talent
        reaction = (
            "Le papier reste inerte entre tes doigts." if talent.dead
            else "Le papier s'illumine et réagit violemment !" if talent.boosts
            else "Le papier frémit et réagit à ton contact."
        )
        embed = discord.Embed(
            title=f"📜 Ton talent — {label}",
            description=f"*{reaction}*\n\n{describe_talent(talent)}",
            color=(
                discord.Color.dark_grey() if talent.dead
                else discord.Color.gold() if talent.boosts
                else discord.Color.purple()
            ),
        )
        paid = "offert" if result.price == 0 else f"{format_int(result.price)} or"
        embed.set_footer(text=f"Papier {paid} · retrouve tes talents dans /affinites")
        await interaction.response.edit_message(embed=embed, view=parent)


class PaperButton(discord.ui.Button):
    """Bouton « 📜 Papier élémentaire » à poser dans une autre vue."""

    def __init__(
        self, session_factory, player_id: int, price: int | None,
        owner_discord_id: int, row: int | None = None,
    ):
        super().__init__(
            label=f"Papier élémentaire ({paper_price_label(price)})",
            emoji="📜",
            style=discord.ButtonStyle.primary,
            disabled=price is None,
            row=row,
        )
        self._session_factory = session_factory
        self._player_id = player_id
        self._owner_id = owner_discord_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self._owner_id:
            await interaction.response.send_message(
                "📜 Ce papier n'est pas pour toi : tape `/affinites` ou `/marchand`.",
                ephemeral=True,
            )
            return
        await open_paper_picker(interaction, self._session_factory, self._player_id)
