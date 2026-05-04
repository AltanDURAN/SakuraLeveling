"""Vue paginée du catalogue de commandes (/help).

Page = un groupe de commandes (ex : la racine "joueur" ou un sous-groupe
comme `/boss`). Boutons Précédent / Suivant pour naviguer, ephemeral.
"""

from __future__ import annotations

import discord


class HelpView(discord.ui.View):
    def __init__(
        self,
        author_id: int,
        pages: list[discord.Embed],
        timeout: float = 300.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.pages = pages
        self.index = 0
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        # Désactive les boutons aux extrémités
        self.prev_button.disabled = self.index <= 0
        self.next_button.disabled = self.index >= len(self.pages) - 1
        # Met à jour le label du compteur
        self.counter.label = f"{self.index + 1} / {len(self.pages)}"

    async def _check_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Cette navigation ne vous est pas destinée. Tape `/help` pour la tienne.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="◀ Précédent", style=discord.ButtonStyle.secondary)
    async def prev_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await self._check_owner(interaction):
            return
        if self.index > 0:
            self.index -= 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="1 / 1", style=discord.ButtonStyle.primary, disabled=True)
    async def counter(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        # Bouton compteur, désactivé en permanence (sert juste d'affichage)
        pass

    @discord.ui.button(label="Suivant ▶", style=discord.ButtonStyle.secondary)
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await self._check_owner(interaction):
            return
        if self.index < len(self.pages) - 1:
            self.index += 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)
