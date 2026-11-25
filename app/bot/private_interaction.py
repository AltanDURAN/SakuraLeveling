"""Lancer une commande depuis un bouton, en privé (25/11/2026).

Le salon du tutoriel est en lecture seule : on n'y tape plus `/daily` ni
`/stats`. Les étapes de Hana ont donc un bouton qui lance LA MÊME commande
(même code, même vérification « C'est fait »), mais tout ce qu'elle répond
reste privé : rien ne s'affiche dans le salon, le panneau reste seul.

`PrivateInteraction` enveloppe l'interaction du bouton : `response.defer`,
`response.send_message` et `followup.send` deviennent éphémères ; tout le
reste passe tel quel.
"""

from __future__ import annotations

from typing import Any

import discord


class _PrivateResponse:
    def __init__(self, response: Any) -> None:
        self._response = response

    def __getattr__(self, name: str) -> Any:
        return getattr(self._response, name)

    async def defer(self, **_: Any) -> Any:
        # « réfléchit… » dans un NOUVEAU message privé : l'écran du tutoriel ne bouge pas.
        return await self._response.defer(ephemeral=True, thinking=True)

    async def send_message(self, *args: Any, **kwargs: Any) -> Any:
        kwargs["ephemeral"] = True
        return await self._response.send_message(*args, **kwargs)


class _PrivateFollowup:
    def __init__(self, followup: Any) -> None:
        self._followup = followup

    def __getattr__(self, name: str) -> Any:
        return getattr(self._followup, name)

    async def send(self, *args: Any, **kwargs: Any) -> Any:
        kwargs["ephemeral"] = True
        return await self._followup.send(*args, **kwargs)


class PrivateInteraction:
    """L'interaction d'un bouton, dont toutes les réponses sont privées."""

    def __init__(self, interaction: discord.Interaction) -> None:
        self._interaction = interaction
        self.response = _PrivateResponse(interaction.response)
        self.followup = _PrivateFollowup(interaction.followup)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._interaction, name)


async def run_command(interaction: discord.Interaction, name: str) -> bool:
    """Lance la commande `/name` (sans option) pour l'auteur du clic, en privé.

    False si elle n'existe pas (la réponse reste alors à faire par l'appelant)."""
    client = getattr(interaction, "client", None)
    tree = getattr(client, "tree", None)
    command = tree.get_command(name) if tree is not None else None
    if not isinstance(command, discord.app_commands.Command):
        return False
    private = PrivateInteraction(interaction)
    if command.binding is not None:
        await command.callback(command.binding, private)
    else:
        await command.callback(private)
    return True
