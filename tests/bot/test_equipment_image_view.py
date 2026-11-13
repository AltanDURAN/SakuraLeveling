"""`/equipement` : changer de page ne fige pas le bot (revue du 13/11/2026)."""

import asyncio
import threading

from app.bot.views.equipment_image_view import EquipmentImageView


def test_le_changement_de_page_rend_l_image_dans_un_thread():
    calls = []

    class Response:
        async def defer(self):
            calls.append("defer")

    class Interaction:
        response = Response()

        async def edit_original_response(self, **kwargs):
            calls.append(("edit", kwargs["embed"], kwargs["attachments"]))

    class View:
        def render_current_page(self):
            calls.append(("render", threading.current_thread() is threading.main_thread()))
            return "embed", "file"

    asyncio.run(EquipmentImageView._switch(View(), Interaction()))
    # Accusé de réception d'abord (limite de 3 s), rendu HORS du thread de la
    # boucle, puis le message est mis à jour.
    assert calls == ["defer", ("render", False), ("edit", "embed", ["file"])]
