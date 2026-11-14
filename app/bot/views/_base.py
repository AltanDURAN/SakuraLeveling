"""Vues qui s'éteignent proprement (revue du 14/11/2026).

Quand une vue expire, Discord laisse ses boutons affichés : le joueur clique
et lit « Échec de l'interaction ». 48 vues sur 51 étaient dans ce cas.
`ExpiringView` grise ses boutons à l'expiration, sur le message où elle se
trouve.

Pour retrouver ce message sans que chaque écran ait à le donner, la vue retient
la DERNIÈRE interaction qui l'a touchée (un clic) : Discord laisse modifier le
message d'une interaction pendant 15 minutes. Un écran peut aussi poser
`view.message` lui-même (message public envoyé par le bot). Une vue jamais
touchée et sans message connu s'éteint sans rien modifier — on ne prend jamais
le risque de modifier un autre message.
"""

from __future__ import annotations

import functools
import time

import discord

#: Un jeton d'interaction vaut 15 minutes : au-delà, on ne tente rien.
TOKEN_SECONDS = 14 * 60


class ExpiringView(discord.ui.View):
    #: Le message qui porte la vue, quand l'écran le connaît.
    message: discord.Message | None = None
    _touched: discord.Interaction | None = None
    _touched_at: float = 0.0

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        check = cls.__dict__.get("interaction_check")
        if check is not None and not getattr(check, "_remembers", False):
            # Une sous-classe qui redéfinit `interaction_check` n'appelle pas
            # forcément la nôtre : on retient l'interaction avant la sienne.
            @functools.wraps(check)
            async def remembering(self, interaction: discord.Interaction) -> bool:
                self._remember(interaction)
                return await check(self, interaction)

            remembering._remembers = True
            cls.interaction_check = remembering

    def _remember(self, interaction: discord.Interaction) -> None:
        self._touched, self._touched_at = interaction, time.monotonic()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        self._remember(interaction)
        return True

    interaction_check._remembers = True

    def disable_all(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled") and not getattr(child, "url", None):
                child.disabled = True

    async def on_timeout(self) -> None:
        self.disable_all()
        try:
            if self.message is not None:
                await self.message.edit(view=self)
            elif self._touched is not None and time.monotonic() - self._touched_at < TOKEN_SECONDS:
                await self._touched.edit_original_response(view=self)
        except discord.HTTPException:
            pass          # message supprimé, jeton expiré : rien à éteindre
