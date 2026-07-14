"""View de navigation du /profil : boutons vers les sous-cartes + retour.

La carte principale = la bannière PNG (fichier ré-attaché au retour). Les
sous-cartes = embeds. Seul l'auteur de la commande peut naviguer.
"""

from __future__ import annotations

import discord

# (clé, emoji, libellé) — ordre des boutons.
_SECTIONS = [
    ("inventory", "🎒", "Inventaire"),
    ("equipment", "🛡️", "Équipement"),
    ("skills", "🔮", "Compétences"),
    ("titles", "🏷️", "Titres"),
    ("affinities", "✨", "Affinités"),
    ("career", "📈", "Carrière"),
    ("duel", "⚔️", "Duel"),
]


class _SectionButton(discord.ui.Button):
    def __init__(self, key: str, emoji: str, label: str, row: int):
        super().__init__(style=discord.ButtonStyle.secondary, emoji=emoji, label=label, row=row)
        self.key = key

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.view.show_section(interaction, self.key)


class _BackButton(discord.ui.Button):
    def __init__(self):
        super().__init__(style=discord.ButtonStyle.primary, emoji="⬅️", label="Retour au profil")

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.view.show_main(interaction)


class ProfileCardView(discord.ui.View):
    def __init__(
        self,
        *,
        author_id: int,
        banner_path: str,
        banner_filename: str,
        main_embed: discord.Embed,
        subcards: dict[str, discord.Embed],
        timeout: float = 240,
    ):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.banner_path = banner_path
        self.banner_filename = banner_filename
        self.main_embed = main_embed
        self.subcards = subcards
        self._show_main_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "👀 Ce n'est pas ta fiche — fais `/profil` pour voir la tienne.",
                ephemeral=True,
            )
            return False
        return True

    def _show_main_buttons(self) -> None:
        self.clear_items()
        i = 0
        for key, emoji, label in _SECTIONS:
            if key not in self.subcards:
                continue
            self.add_item(_SectionButton(key, emoji, label, row=i // 5))
            i += 1

    def _show_back_button(self) -> None:
        self.clear_items()
        self.add_item(_BackButton())

    async def show_section(self, interaction: discord.Interaction, key: str) -> None:
        self._show_back_button()
        # attachments=[] retire l'image de la bannière pour la sous-carte.
        await interaction.response.edit_message(embed=self.subcards[key], attachments=[], view=self)

    async def show_main(self, interaction: discord.Interaction) -> None:
        self._show_main_buttons()
        file = discord.File(self.banner_path, filename=self.banner_filename)
        await interaction.response.edit_message(embed=self.main_embed, attachments=[file], view=self)
