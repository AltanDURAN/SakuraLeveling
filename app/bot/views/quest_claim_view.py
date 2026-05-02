"""Vue partagée daily/weekly avec un bouton 'Récupérer ma/mes récompense(s)'."""

from __future__ import annotations

from typing import Callable, Awaitable

import discord


class QuestClaimView(discord.ui.View):
    """Single-button view qui exécute un callable de claim au click.

    Le label du bouton est calculé selon le nombre de récompenses dispo :
        - 0 : bouton absent (la view a 0 enfant)
        - 1 : "Récupérer ma récompense"
        - N : "Récupérer mes récompenses (N)"

    Le callable doit prendre l'interaction Discord et l'utiliser pour répondre
    + (idéalement) re-render le message d'origine pour cacher le bouton.
    """

    def __init__(
        self,
        author_id: int,
        claimable_count: int,
        on_claim: Callable[[discord.Interaction], Awaitable[None]],
        timeout: float = 600.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self._on_claim = on_claim

        if claimable_count <= 0:
            return  # pas de bouton
        if claimable_count == 1:
            label = "Récupérer ma récompense"
        else:
            label = f"Récupérer mes récompenses ({claimable_count})"

        button = discord.ui.Button(
            label=label, style=discord.ButtonStyle.success, emoji="🎁",
        )

        async def _cb(interaction: discord.Interaction) -> None:
            if interaction.user.id != self.author_id:
                await interaction.response.send_message(
                    "❌ Cette interaction ne vous est pas destinée.", ephemeral=True,
                )
                return
            await self._on_claim(interaction)

        button.callback = _cb
        self.add_item(button)
