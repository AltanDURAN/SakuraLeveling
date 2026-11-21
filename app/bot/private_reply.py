"""Répondre en privé, même après un `defer()` public.

Après `interaction.response.defer()` (public), le PREMIER `followup.send`
remplace le message « réfléchit… » et Discord ignore `ephemeral=True` : un
refus (« pas encore de profil », catégorie inconnue…) s'affichait donc à tout
le salon. On efface d'abord la réponse en attente ; le suivi devient alors un
nouveau message, qui peut être privé (revue de novembre 2026).
"""

from __future__ import annotations

import discord


async def send_private(interaction: discord.Interaction, content: str, **kwargs) -> None:
    if not interaction.response.is_done():
        await interaction.response.send_message(content, ephemeral=True, **kwargs)
        return
    try:
        await interaction.delete_original_response()
    except discord.HTTPException:
        pass
    await interaction.followup.send(content, ephemeral=True, **kwargs)
