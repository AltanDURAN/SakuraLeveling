"""Une vue expirée grise ses boutons au lieu de laisser « Échec de
l'interaction » (revue du 14/11/2026 : 48 vues sur 51 les laissaient morts)."""

import asyncio

import discord

from app.bot.views._base import ExpiringView


class Custom(ExpiringView):
    """Une vue qui redéfinit son contrôle, comme la plupart des vues du jeu."""

    async def interaction_check(self, interaction) -> bool:
        return interaction.user == "moi"


class Interaction:
    user = "moi"

    def __init__(self):
        self.edits = []

    async def edit_original_response(self, **kwargs):
        self.edits.append(kwargs)


def _view(cls):
    view = cls(timeout=60)
    view.add_item(discord.ui.Button(label="Agir"))
    view.add_item(discord.ui.Button(label="Site", url="https://example.com"))
    return view


def test_les_boutons_sont_grises_sur_le_message_du_dernier_clic():
    async def run():
        for cls in (ExpiringView, Custom):
            view, click = _view(cls), Interaction()
            assert await view.interaction_check(click)          # un clic : la vue s'en souvient
            await view.on_timeout()
            assert click.edits == [{"view": view}]
            action, link = view.children
            assert action.disabled and not link.disabled        # un lien reste cliquable
        refused = Interaction()
        refused.user = "un autre"
        assert not await _view(Custom).interaction_check(refused)   # le contrôle de la vue vaut toujours

    asyncio.run(run())


def test_sans_message_connu_rien_d_autre_n_est_modifie():
    async def run():
        view = _view(ExpiringView)
        await view.on_timeout()                                   # jamais touchée : ne lève pas
        assert view.children[0].disabled

        class Message:
            edited = None

            async def edit(self, **kwargs):
                Message.edited = kwargs

        public = _view(ExpiringView)
        public.message = Message()
        await public.on_timeout()
        assert Message.edited == {"view": public}                # l'écran a donné son message

    asyncio.run(run())


def test_les_vues_du_jeu_s_eteignent_toutes():
    import importlib
    import pkgutil

    import app.bot.cogs as cogs
    import app.bot.views as views

    for pkg in (views, cogs):
        for module in pkgutil.iter_modules(pkg.__path__):
            importlib.import_module(f"{pkg.__name__}.{module.name}")

    def subclasses(cls):
        for sub in cls.__subclasses__():
            yield sub
            yield from subclasses(sub)

    ours = [c for c in subclasses(discord.ui.View) if c.__module__.startswith("app.bot")]
    assert len(ours) > 40
    forgotten = [c.__qualname__ for c in ours if not issubclass(c, ExpiringView)]
    assert forgotten == []          # toute nouvelle vue hérite d'ExpiringView (ou de GatedView)
