"""Règlement (07/11/2026) : sans l'avoir accepté, une commande ou un bouton du
jeu répond par le règlement et son bouton ; une fois accepté, tout s'ouvre.
Le panneau du salon est reconnu à son bouton et réécrit si le texte change."""

import asyncio
import io
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import discord
import pytest
from PIL import Image

from app.application.use_cases import rules as rules_uc
from app.bot import rules_gate
from app.bot.cogs import event_cog, offering_cog, rules_cog, tutorial_cog, world_boss_cog
from app.bot.embeds.rules_embeds import BANNER, build_rules_embed
from app.bot.rendering.welcome_card import RULES_HEIGHT, WIDTH, compose_rules_card
from app.bot.views.encounter_view import EncounterView
from app.bot.views.trade_view import TradeResponseView
from app.infrastructure.config.settings import settings
from app.infrastructure.rules.rules_loader import get_rules

COMMAND = discord.InteractionType.application_command
BUTTON = discord.InteractionType.component
WHEN = datetime(2026, 11, 7, 12)


@pytest.fixture(autouse=True)
def store(monkeypatch):
    """La base remplacée par un dictionnaire : discord_id → version acceptée."""
    rules_gate._accepted.clear()
    accepted: dict[int, int] = {}

    def read(discord_id):
        version = accepted.get(discord_id)
        return None if version is None else rules_uc.Acceptance(version, WHEN)

    def write(discord_id, version):
        newly = accepted.get(discord_id, 0) < version
        if newly:
            accepted[discord_id] = version
        return newly, rules_uc.Acceptance(accepted[discord_id], WHEN)

    monkeypatch.setattr(rules_gate, "_read", read)
    monkeypatch.setattr(rules_gate, "_write", write)
    yield accepted
    rules_gate._accepted.clear()


class _Response:
    def __init__(self, done=False):
        self.sent, self.edited, self._done = [], [], done

    def is_done(self):
        return self._done

    async def send_message(self, content=None, **kwargs):
        self.sent.append((content, kwargs))
        self._done = True

    async def edit_message(self, **kwargs):
        self.edited.append(kwargs)
        self._done = True


class _Followup:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))


def _interaction(user_id=5, kind=COMMAND, name="profil", ephemeral_message=None, done=False):
    message = None if ephemeral_message is None else SimpleNamespace(
        flags=SimpleNamespace(ephemeral=ephemeral_message))
    return SimpleNamespace(user=SimpleNamespace(id=user_id), type=kind, data={"name": name},
                           response=_Response(done), followup=_Followup(), message=message)


def _buttons(view):
    return [getattr(child, "custom_id", None) for child in view.children]


def test_sans_avoir_accepte_la_commande_montre_le_reglement():
    async def run():
        interaction = _interaction()
        assert not await rules_gate.allow(interaction)
        content, kwargs = interaction.response.sent[0]
        assert content == rules_gate.ASK_FIRST and kwargs["ephemeral"]
        assert kwargs["embed"].title == get_rules().title
        assert rules_gate.ACCEPT_ID in _buttons(kwargs["view"])
    asyncio.run(run())


def test_une_fois_accepte_tout_passe(store):
    store[5] = get_rules().version
    interaction = _interaction()
    assert asyncio.run(rules_gate.allow(interaction))
    assert interaction.response.sent == []


def test_reglement_admin_et_autocompletion_restent_ouverts():
    for name in ("reglement", "admin", "boss_admin", "event"):
        assert asyncio.run(rules_gate.allow(_interaction(name=name))), name
    assert asyncio.run(rules_gate.allow(_interaction(kind=discord.InteractionType.autocomplete)))


def test_un_bouton_du_jeu_est_garde_aussi_meme_apres_un_defer():
    async def run():
        interaction = _interaction(kind=BUTTON, name="", done=True)
        assert not await rules_gate.allow(interaction)
        assert interaction.followup.sent and interaction.followup.sent[0][1]["ephemeral"]
    asyncio.run(run())


def test_les_vues_publiques_du_jeu_sont_gardees():
    for view in (EncounterView, world_boss_cog.WorldBossView, event_cog.ChestView, event_cog.LittleGirlView,
                 event_cog.ForgeView, tutorial_cog.TutorialPanelView, TradeResponseView, offering_cog.OfferingView):
        assert issubclass(view, rules_gate.GatedView), view.__name__


def test_un_changement_important_redemande_l_acceptation(store, monkeypatch):
    store[5] = 1
    newer = replace(get_rules(), version=2)
    monkeypatch.setattr(rules_gate, "get_rules", lambda: newer)

    async def run():
        interaction = _interaction()
        assert not await rules_gate.allow(interaction)
        assert interaction.response.sent[0][0] == rules_gate.ASK_AGAIN
    asyncio.run(run())


def test_une_base_indisponible_ne_ferme_pas_le_jeu(monkeypatch):
    def broken(discord_id):
        raise RuntimeError("base verrouillée")
    monkeypatch.setattr(rules_gate, "_read", broken)
    assert asyncio.run(rules_gate.allow(_interaction()))


def test_accepter_depuis_la_reponse_privee_la_remplace(store):
    async def run():
        interaction = _interaction(kind=BUTTON, ephemeral_message=True)
        await rules_gate.accept(interaction)
        assert interaction.response.edited == [{"content": rules_gate.DONE_IN_PLACE, "embed": None, "view": None}]
        assert await rules_gate.allow(_interaction())
    asyncio.run(run())
    assert store[5] == get_rules().version


def test_accepter_depuis_le_salon_puis_recliquer():
    async def run():
        first = _interaction(kind=BUTTON, ephemeral_message=False)
        await rules_gate.accept(first)
        text, kwargs = first.response.sent[0]
        assert "Merci" in text and kwargs["ephemeral"]
        assert f"<#{settings.tutorial_channel_id}>" in text
        again = _interaction(kind=BUTTON, ephemeral_message=False)
        await rules_gate.accept(again)
        assert "déjà accepté" in again.response.sent[0][0]
    asyncio.run(run())


def test_la_commande_reglement_dit_ou_on_en_est(store):
    async def run(accepted):
        if accepted:
            store[5] = get_rules().version
        interaction = _interaction(name="reglement")
        await rules_cog.RulesCog.reglement.callback(SimpleNamespace(), interaction)
        return interaction.response.sent[0]
    content, kwargs = asyncio.run(run(False))
    assert content == rules_gate.ASK_FIRST and "view" in kwargs and kwargs["ephemeral"]
    content, kwargs = asyncio.run(run(True))
    assert content.startswith("✅ Tu as accepté ce règlement le <t:") and "view" not in kwargs


# ----------------------------------------------------------------- panneau
class _Message:
    def __init__(self, author_id, embeds=(), custom_ids=()):
        self.author = SimpleNamespace(id=author_id)
        self.embeds = list(embeds)
        self.components = [SimpleNamespace(children=[SimpleNamespace(custom_id=c) for c in custom_ids])]
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)


class _Channel:
    id = 1

    def __init__(self, messages):
        self.messages, self.sent = messages, []

    def history(self, limit=50):
        async def walk():
            for message in self.messages[:limit]:
                yield message
        return walk()

    async def send(self, **kwargs):
        self.sent.append(kwargs)


def test_le_panneau_est_reconnu_a_son_bouton():
    assert rules_cog.is_panel(_Message(1, custom_ids=[rules_gate.ACCEPT_ID]), 1)
    assert not rules_cog.is_panel(_Message(2, custom_ids=[rules_gate.ACCEPT_ID]), 1)    # pas le bot
    assert not rules_cog.is_panel(_Message(1, custom_ids=["tutorial:open"]), 1)


def test_le_panneau_est_poste_puis_reecrit_seulement_s_il_change():
    rules = get_rules()

    async def run():
        empty = _Channel([_Message(9)])                     # « Coming soon » d'un humain : intouché
        assert await rules_cog.post_or_update_panel(empty, 1, rules) == "posté"
        sent = empty.sent[0]
        assert sent["file"].filename == BANNER and sent["embed"].image.url == f"attachment://{BANNER}"
        assert rules_gate.ACCEPT_ID in _buttons(sent["view"])

        panel = _Message(1, embeds=[build_rules_embed(rules, banner=True)], custom_ids=[rules_gate.ACCEPT_ID])
        assert await rules_cog.post_or_update_panel(_Channel([panel]), 1, rules) == "inchangé"
        assert panel.edits == []

        changed = replace(rules, intro="Nouvelle introduction.")
        channel = _Channel([_Message(9), panel])
        assert await rules_cog.post_or_update_panel(channel, 1, changed) == "mis à jour"
        assert panel.edits[0]["embed"].description == "Nouvelle introduction." and channel.sent == []
        assert panel.edits[0]["attachments"][0].filename == BANNER
    asyncio.run(run())


def test_le_bandeau_se_dessine():
    assert Image.open(io.BytesIO(compose_rules_card())).size == (WIDTH, RULES_HEIGHT)
