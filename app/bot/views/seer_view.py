"""La voyante : on choisit un élément, on paie sa prestation, elle lit le talent.

Remplace le « papier élémentaire » (acheter puis consommer un objet) : une
seule étape, et un personnage qui justifie la règle du prix croissant — plus
on la consulte, plus chaque vision lui coûte. Ouvert par `/voyante` et par le
bouton de `/affinites`. Toujours éphémère : c'est une information personnelle.
"""

from __future__ import annotations

import asyncio

import discord

from app.application.use_cases.reveal_element_talent import (
    RevealElementTalentUseCase,
    RevealResult,
)
from app.bot.rendering.npc_panel import compose_npc_panel, panel_path
from app.infrastructure.artisans import artisan_loader
from app.shared.enums import ELEMENT_EMOJIS, ELEMENT_LABELS
from app.shared.formatters import format_int


def reading_price_label(price: int | None) -> str:
    if price is None:
        return "elle a tout lu"
    return "offerte" if price == 0 else f"{format_int(price)} or"


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


def _vision(talent, element_label: str) -> str:
    """Ce que dit la voyante en sortant de sa transe."""
    if talent.dead:
        return f"Rien… Le {element_label.lower()} se détourne de toi. Je suis désolée."
    if talent.boosts:
        return f"Par les anciens… Le {element_label.lower()} brûle en toi comme rarement. Un don."
    if talent.talent >= 7:
        return f"Le {element_label.lower()} te répond avec force. Tu es fait pour lui."
    if talent.talent >= 4:
        return f"Le {element_label.lower()} t'écoute. Avec de la patience, il te suivra."
    return f"Le {element_label.lower()} murmure à peine. Il faudra beaucoup l'appeler."


def _prices() -> tuple[int, ...]:
    return artisan_loader.get_seer().reading_prices


def load_status(session_factory, player_id: int):
    with session_factory() as session:
        return RevealElementTalentUseCase(session, _prices()).status(player_id)


async def open_seer(interaction: discord.Interaction, session_factory, player_id: int) -> None:
    """Répond (éphémère) avec le salon de la voyante."""
    await interaction.response.defer(ephemeral=True, thinking=True)
    view = SeerView(session_factory, player_id)
    await asyncio.to_thread(view.refresh_data)
    view.build()
    embeds, file = await view.render()
    await interaction.followup.send(embeds=embeds, file=file, view=view, ephemeral=True)


class SeerView(discord.ui.View):
    def __init__(self, session_factory, player_id: int, timeout: float = 300.0):
        super().__init__(timeout=timeout)
        self.definition = artisan_loader.get_seer()
        self._session_factory = session_factory
        self.player_id = player_id
        self.status = None
        self.element: str | None = None
        self.last_reading: RevealResult | None = None

    # ------------------------------------------------------------ données --
    def refresh_data(self) -> None:
        self.status = load_status(self._session_factory, self.player_id)
        if self.element and self.element not in self.status.unrevealed:
            self.element = None

    @property
    def price(self) -> int | None:
        return self.status.next_price if self.status else None

    @property
    def can_read(self) -> bool:
        return (
            self.element is not None and self.price is not None
            and self.status.gold >= self.price
        )

    # -------------------------------------------------------- composition --
    def build(self) -> None:
        self.clear_items()
        if self.status and self.status.unrevealed:
            self.add_item(_ElementSelect(self))
            self.add_item(_ReadButton(self))
        self.add_item(_CloseButton(self))

    def _greeting(self) -> str:
        if self.last_reading is not None and self.last_reading.talent is not None:
            label = ELEMENT_LABELS.get(self.last_reading.element, self.last_reading.element)
            return _vision(self.last_reading.talent, label)
        if self.price is None:
            return "J'ai lu tout ce que ton âme acceptait de montrer. Reviens à la saison prochaine."
        return self.definition.greeting

    def _info_rows(self) -> list[tuple[str, str]]:
        known = 8 - len(self.status.unrevealed)
        rows = [
            ("Son don", "lire ton talent caché dans un élément"),
            ("Talents lus", f"🔮 {known}/8"),
            ("Prochaine lecture", reading_price_label(self.price)),
            ("Ta bourse", f"💰 {format_int(self.status.gold)} or"),
            ("Sa règle", "chaque lecture coûte plus que la précédente"),
        ]
        if self.element:
            rows.insert(0, ("Tu lui demandes", f"{ELEMENT_EMOJIS.get(self.element, '')} "
                                                f"{ELEMENT_LABELS.get(self.element, self.element)}"))
        return rows

    async def render(self) -> tuple[list[discord.Embed], discord.File]:
        path = panel_path(self.definition.code, self.player_id)
        await asyncio.to_thread(
            compose_npc_panel,
            path,
            npc_name=self.definition.name,
            npc_title=self.definition.title,
            image_name=self.definition.image,
            accent=self.definition.accent,
            greeting=self._greeting(),
            info_rows=self._info_rows(),
            seed=self.player_id,
        )
        filename = path.rsplit("/", 1)[-1]
        color = discord.Color.from_rgb(*self.definition.accent)
        panel = discord.Embed(color=color)
        panel.set_image(url=f"attachment://{filename}")
        embeds = [panel]

        reading = self.last_reading
        if reading is not None and reading.talent is not None:
            label = f"{ELEMENT_EMOJIS.get(reading.element, '')} {ELEMENT_LABELS.get(reading.element, reading.element)}"
            talent = reading.talent
            result = discord.Embed(
                title=f"🔮 Ton talent — {label}",
                description=describe_talent(talent),
                color=(
                    discord.Color.dark_grey() if talent.dead
                    else discord.Color.gold() if talent.boosts else color
                ),
            )
            paid = "offerte" if reading.price == 0 else f"{format_int(reading.price)} or"
            result.set_footer(text=f"Lecture {paid} · tes talents sont aussi dans /affinites")
            embeds.append(result)
        elif self.price is not None:
            embeds.append(discord.Embed(
                description=(
                    "Chacun naît avec un **talent caché** par élément : il décide à "
                    "quelle vitesse tes essences tombent. Certains éléments te sont "
                    "peut-être fermés… d'autres plus généreux que tu ne l'imagines.\n\n"
                    f"*« {self.definition.price_story} »*\n"
                    f"Prochaine lecture : **{reading_price_label(self.price)}** — "
                    "chaque lecture coûte plus cher que la précédente."
                ),
                color=color,
            ))
        return embeds, discord.File(path, filename=filename)

    async def refresh(self, interaction: discord.Interaction) -> None:
        await asyncio.to_thread(self.refresh_data)
        self.build()
        embeds, file = await self.render()
        await interaction.response.edit_message(embeds=embeds, attachments=[file], view=self)


# --------------------------------------------------------------- éléments --
class _ElementSelect(discord.ui.Select):
    def __init__(self, view: SeerView) -> None:
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
        super().__init__(placeholder="Quel élément veux-tu que je lise ?", options=options, row=0)
        self._owner = view

    async def callback(self, interaction: discord.Interaction) -> None:
        self._owner.element = self.values[0]
        self._owner.last_reading = None
        await self._owner.refresh(interaction)


class _ReadButton(discord.ui.Button):
    def __init__(self, view: SeerView) -> None:
        price = view.price
        missing = (price or 0) - view.status.gold
        if view.element is None or price == 0:
            label = f"Consulter ({reading_price_label(price)})"
        elif missing > 0:
            label = f"Il te manque {format_int(missing)} or"
        else:
            label = f"Payer et consulter ({reading_price_label(price)})"
        super().__init__(
            label=label, emoji="🔮", style=discord.ButtonStyle.success,
            disabled=not view.can_read, row=1,
        )
        self._owner = view

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self._owner
        element = view.element
        if element is None:
            await interaction.response.defer()
            return

        def _run() -> RevealResult:
            with view._session_factory() as session:
                return RevealElementTalentUseCase(session, _prices()).execute(
                    view.player_id, element,
                )

        result = await asyncio.to_thread(_run)
        if not result.success:
            await interaction.response.send_message(f"❌ {result.message}", ephemeral=True)
            return
        view.last_reading = result
        view.element = None
        await view.refresh(interaction)


class _CloseButton(discord.ui.Button):
    def __init__(self, view: SeerView) -> None:
        super().__init__(label="Partir", style=discord.ButtonStyle.secondary, row=1)
        self._owner = view

    async def callback(self, interaction: discord.Interaction) -> None:
        for child in self._owner.children:
            child.disabled = True
        await interaction.response.edit_message(view=self._owner)
        self._owner.stop()


class SeerButton(discord.ui.Button):
    """Bouton « 🔮 La voyante » à poser dans une autre vue (ex. /affinites)."""

    def __init__(self, session_factory, player_id: int, price: int | None,
                 owner_discord_id: int, row: int | None = None):
        super().__init__(
            label=f"La voyante — lecture {reading_price_label(price)}",
            emoji="🔮", style=discord.ButtonStyle.primary,
            disabled=price is None, row=row,
        )
        self._session_factory = session_factory
        self._player_id = player_id
        self._owner_id = owner_discord_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self._owner_id:
            await interaction.response.send_message(
                "🔮 Ysaline ne lit que l'âme de celui qui s'assoit en face d'elle : "
                "tape `/voyante`.", ephemeral=True,
            )
            return
        await open_seer(interaction, self._session_factory, self._player_id)
