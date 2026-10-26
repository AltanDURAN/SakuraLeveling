"""`/apparence` : choisir les cosmétiques portés sur la bannière `/profil`.

Les cosmétiques s'achètent chez Sorn (`/marchand`, rayon Cosmétique) : un fond,
un cadre d'avatar, une couleur de titre. Aucun effet en jeu. Un menu par
emplacement (cosmétiques possédés + « par défaut ») et un aperçu de l'en-tête
de la bannière, mis à jour à chaque choix. Toujours éphémère.
"""

from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from app.application.services.cosmetic_resolver import (
    SLOT_LABELS,
    owned_cosmetics,
    worn_cosmetics,
)
from app.bot.cogs._mixins import BetaChannelOnlyMixin
from app.infrastructure.db.repositories.player_cosmetic_repository import (
    COSMETIC_SLOTS,
    PlayerCosmeticRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session
from app.shared.paths import GENERATED_PROFILES_DIR

_DEFAULT = "__defaut__"
_RARITY = {"common": "commun", "rare": "rare", "epic": "épique", "legendary": "légendaire"}


class AppearanceView(discord.ui.View):
    def __init__(self, player_id: int, user: discord.abc.User, title: str | None,
                 rank_label: str, timeout: float = 300.0) -> None:
        super().__init__(timeout=timeout)
        self.player_id = player_id
        self.user = user
        self.title = title
        self.rank_label = rank_label
        self.owned: dict[str, list] = {}
        self.worn: dict[str, str] = {}
        self.looks: dict[str, dict] = {}

    def refresh_data(self) -> None:
        with get_db_session() as session:
            self.owned = owned_cosmetics(session, self.player_id)
            self.worn = PlayerCosmeticRepository(session).get(self.player_id)
            self.looks = worn_cosmetics(session, self.player_id)

    def build(self) -> None:
        self.clear_items()
        for row, slot in enumerate(COSMETIC_SLOTS):
            self.add_item(_SlotSelect(self, slot, row))

    async def render(self) -> tuple[discord.Embed, discord.File]:
        from app.bot.rendering.profile_banner import compose_cosmetic_preview

        GENERATED_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        path = GENERATED_PROFILES_DIR / f"apparence_{self.player_id}.png"
        await asyncio.to_thread(
            compose_cosmetic_preview, str(path),
            display_name=self.user.display_name, avatar_url=self.user.display_avatar.url,
            title=self.title, rank_label=self.rank_label, cosmetics=self.looks,
        )
        owned = sum(len(v) for v in self.owned.values())
        embed = discord.Embed(
            title="🎨 Ton apparence",
            description=("Choisis ce que montre ta bannière `/profil`. Aucun effet en jeu."
                         + ("" if owned else "\nTu n'as encore aucun cosmétique : Sorn en vend "
                                             "(`/marchand`, rayon Cosmétique).")),
            color=discord.Color.from_rgb(214, 120, 170),
        )
        embed.set_image(url=f"attachment://{path.name}")
        return embed, discord.File(str(path), filename=path.name)

    async def refresh(self, interaction: discord.Interaction) -> None:
        await asyncio.to_thread(self.refresh_data)
        self.build()
        embed, file = await self.render()
        await interaction.response.edit_message(embed=embed, attachments=[file], view=self)


class _SlotSelect(discord.ui.Select):
    def __init__(self, view: AppearanceView, slot: str, row: int) -> None:
        current = view.worn.get(slot)
        options = [discord.SelectOption(label="Par défaut", value=_DEFAULT, default=not current)]
        for item in view.owned.get(slot, [])[:24]:
            options.append(discord.SelectOption(
                label=item.name[:100], value=item.code,
                description=_RARITY.get(item.rarity, item.rarity)[:100],
                default=item.code == current,
            ))
        super().__init__(placeholder=SLOT_LABELS[slot], options=options, row=row,
                         disabled=len(options) == 1)
        self._owner = view
        self._slot = slot

    async def callback(self, interaction: discord.Interaction) -> None:
        code = None if self.values[0] == _DEFAULT else self.values[0]

        def _save() -> None:
            with get_db_session() as session:
                PlayerCosmeticRepository(session).set(self._owner.player_id, self._slot, code)

        await asyncio.to_thread(_save)
        await self._owner.refresh(interaction)


class CosmeticCog(BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="apparence",
        description="Choisis le fond, le cadre et la couleur du titre de ta bannière /profil",
    )
    async def apparence(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        from app.bot.rank_roles import current_rank
        from app.infrastructure.db.repositories.player_title_repository import PlayerTitleRepository
        from app.infrastructure.titles.title_loader import get_definition as get_title

        with get_db_session() as session:
            profile = PlayerRepository(session).get_or_create_by_discord_id(
                discord_id=interaction.user.id, username=interaction.user.name,
                display_name=interaction.user.display_name,
            )
            code = PlayerTitleRepository(session).get_active_title_code(profile.player.id)
            title_def = get_title(code) if code else None
            title = f"{title_def.icon} {title_def.name}" if title_def else None
            player_id = profile.player.id
        rank = current_rank(interaction.user) if isinstance(interaction.user, discord.Member) else ""
        view = AppearanceView(player_id, interaction.user, title, rank)
        await asyncio.to_thread(view.refresh_data)
        view.build()
        embed, file = await view.render()
        await interaction.followup.send(embed=embed, file=file, view=view, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CosmeticCog(bot))
