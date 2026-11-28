"""Harnais : chaque commande slash du bot, lancée avec une fausse interaction
sur une base en mémoire remplie du vrai contenu (audit du 28/11/2026).

Les cogs sont chargés comme au démarrage (même liste que `app.bot.main`, lue
dans le fichier sans l'importer — l'importer lancerait le bot). Ce qui n'est
pas décrit explicitement ici est un `Anything` : un objet qui accepte tout
(attribut, appel, `await`), pour que seul NOTRE code puisse planter.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import pkgutil
import re
import typing
from datetime import UTC, datetime
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

ROOT = Path(__file__).resolve().parents[2]


class Anything:
    """Accepte tout : attribut, appel, await, itération (vide), contexte."""

    def __init__(self, name="x"):
        self._name = name

    def __getattr__(self, item):
        if item.startswith("__"):
            raise AttributeError(item)
        return Anything(f"{self._name}.{item}")

    def __call__(self, *a, **k):
        return Anything(f"{self._name}()")

    def __await__(self):
        if False:
            yield
        return Anything(f"await {self._name}")

    def __iter__(self):
        return iter(())

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration

    def __bool__(self):
        return False

    def __len__(self):
        return 0

    def __str__(self):
        return ""

    def __int__(self):
        return 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Sent:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def note(self, kind, args, kwargs):
        if args and isinstance(args[0], str):
            kwargs = {**kwargs, "content": args[0]}
        for embed in ([kwargs.get("embed")] if kwargs.get("embed") else []) + list(kwargs.get("embeds") or []):
            assert isinstance(embed, discord.Embed)
            assert len(embed) <= 6000, f"embed trop long ({len(embed)})"
            embed.to_dict()
            for field in embed.fields:
                assert len(field.value) <= 1024 and len(field.name) <= 256, "champ trop long"
            assert len(embed.description or "") <= 4096, "description trop longue"
        if kwargs.get("content"):
            assert len(kwargs["content"]) <= 2000, "message trop long"
        view = kwargs.get("view")
        if view is not None:
            assert len(view.children) <= 25, "trop de composants"
        self.calls.append((kind, kwargs))


class FakeMessage(Anything):
    def __init__(self, sent: Sent):
        super().__init__("message")
        self.id = 999
        self._sent = sent
        self.embeds = []
        self.attachments = []
        self.jump_url = "https://discord.com/channels/1/2/999"

    async def edit(self, *args, **kwargs):
        self._sent.note("edit", args, kwargs)
        return self

    async def delete(self, *a, **k):
        return None


class FakeResponse:
    def __init__(self, sent: Sent):
        self._sent = sent
        self._done = False
        self.type = None

    def is_done(self):
        return self._done

    async def send_message(self, *args, **kwargs):
        assert not self._done, "deux réponses primaires"
        self._done = True
        self._sent.note("send", args, kwargs)

    async def defer(self, *args, **kwargs):
        assert not self._done, "defer après une réponse"
        self._done = True
        self._sent.note("defer", args, kwargs)

    async def edit_message(self, *args, **kwargs):
        self._done = True
        self._sent.note("edit", args, kwargs)

    async def send_modal(self, modal):
        assert not self._done
        self._done = True
        self._sent.note("modal", (), {"modal": modal})

    async def autocomplete(self, choices):
        self._done = True


class FakeFollowup:
    def __init__(self, sent: Sent):
        self._sent = sent

    async def send(self, *args, **kwargs):
        self._sent.note("followup", args, kwargs)
        return FakeMessage(self._sent)


class FakeRole(Anything):
    def __init__(self, id, name):
        super().__init__("role")
        self.id, self.name, self.mention = id, name, f"<@&{id}>"
        self.position = 1
        self.members = []


class FakeMember(Anything):
    def __init__(self, uid, guild, name="Testeur"):
        super().__init__("member")
        self.id = uid
        self.name = self.display_name = self.global_name = name
        self.mention = f"<@{uid}>"
        self.bot = False
        self.guild = guild
        self.roles = []
        self.display_avatar = Anything("avatar")
        self.display_avatar.url = ""
        self.avatar = None
        self.created_at = self.joined_at = datetime(2026, 1, 1, tzinfo=UTC)
        self.guild_permissions = discord.Permissions.all()

    async def add_roles(self, *a, **k):
        return None

    async def remove_roles(self, *a, **k):
        return None

    async def send(self, *args, **kwargs):
        return FakeMessage(Sent())

    def __str__(self):
        return self.name

    def __eq__(self, other):
        return getattr(other, "id", None) == self.id

    def __hash__(self):
        return hash(self.id)


class FakeChannel(Anything):
    def __init__(self, cid, guild, sent):
        super().__init__("channel")
        self.id = cid
        self.guild = guild
        self.name = "salon"
        self.mention = f"<#{cid}>"
        self.jump_url = f"https://discord.com/channels/1/{cid}"
        self._sent = sent

    async def send(self, *args, **kwargs):
        self._sent.note("channel", args, kwargs)
        return FakeMessage(self._sent)

    def get_partial_message(self, mid):
        return FakeMessage(self._sent)

    async def fetch_message(self, mid):
        return FakeMessage(self._sent)

    def permissions_for(self, who):
        return discord.Permissions.all()


class FakeGuild(Anything):
    def __init__(self, sent):
        super().__init__("guild")
        self.id = 1
        self.name = "Sakura"
        self.members: list = []
        self.roles: list = []
        self.channels: list = []
        self.text_channels: list = []
        self.categories: list = []
        self.default_role = FakeRole(1, "@everyone")
        self.me = None
        self._sent = sent
        self.member_count = 1

    def get_member(self, uid):
        return next((m for m in self.members if m.id == uid), None)

    async def fetch_member(self, uid):
        return self.get_member(uid)

    def get_role(self, rid):
        return next((r for r in self.roles if r.id == rid), None)

    def get_channel(self, cid):
        return FakeChannel(cid, self, self._sent)

    get_channel_or_thread = get_channel


def fake_interaction(bot, command_name: str, channel_id: int, user_id: int = 424242):
    sent = Sent()
    guild = FakeGuild(sent)
    user = FakeMember(user_id, guild)
    guild.members = [user]
    guild.me = FakeMember(1, guild, "Sakura Leveling")
    channel = FakeChannel(channel_id, guild, sent)
    inter = Anything("interaction")
    inter.__dict__.update(
        user=user, guild=guild, guild_id=1, channel=channel, channel_id=channel_id,
        client=bot, response=FakeResponse(sent), followup=FakeFollowup(sent),
        created_at=datetime.now(UTC), locale=discord.Locale.french, id=12345,
        data={"name": command_name}, extras={}, message=None, type=discord.InteractionType.application_command,
        command=Anything("command"), _sent=sent,
    )

    async def original_response():
        return FakeMessage(sent)

    async def edit_original_response(*args, **kwargs):
        sent.note("edit_original", args, kwargs)
        return FakeMessage(sent)

    async def delete_original_response():
        return None

    inter.original_response = original_response
    inter.edit_original_response = edit_original_response
    inter.delete_original_response = delete_original_response
    return inter


def cog_modules() -> list[str]:
    text = (ROOT / "app" / "bot" / "main.py").read_text(encoding="utf-8")
    return re.findall(r'"(app\.bot\.cogs\.[a-z_]+)"', text)


def install_database():
    """Base en mémoire, schéma complet, contenu réel seedé, un joueur."""
    import app.infrastructure.db.models as models_pkg
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from app.infrastructure.db import session as db_session
    from app.infrastructure.db.base import Base

    for mod in pkgutil.iter_modules(models_pkg.__path__):
        importlib.import_module(f"{models_pkg.__name__}.{mod.name}")
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    old = db_session.SessionLocal.kw.get("bind")
    db_session.SessionLocal.configure(bind=engine)
    from app.infrastructure.db.seeders import seed_content
    seed_content.main()
    _populate()
    return old


def _populate():
    """Deux joueurs ; le premier a de l'or, des pièces (dont deux copies pour
    la fusion), des potions, des matériaux et des cartes."""
    from app.infrastructure.db.session import get_db_session
    from app.infrastructure.db.repositories.player_repository import PlayerRepository
    from app.infrastructure.db.repositories.gear_repository import GearRepository
    from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
    from app.infrastructure.db.repositories.item_repository import ItemRepository

    with get_db_session() as s:
        players = PlayerRepository(s)
        pid = players.get_or_create_by_discord_id(424242, "t", "Testeur").player.id
        players.get_or_create_by_discord_id(OTHER_ID, "p", "Partenaire")
        players.add_gold(pid, 500_000, source="admin")
        items = ItemRepository(s)
        gear = GearRepository(s)
        for code in ("surin_dentele", "surin_dentele", "epee_de_l_ossuaire"):
            gear.add(pid, items.get_by_code(code).id)
        inv = InventoryRepository(s)
        for code in ("potion_soin", "gel_e", "dent_de_gobelin", "booster_offert"):
            inv.add_item(pid, items.get_by_code(code).id, 10)


OTHER_ID = 434343   # un second joueur, cible des commandes qui en demandent un


def value_for(param: app_commands.Parameter, guild_member):
    """Une valeur plausible pour un paramètre de commande."""
    if param.choices:
        choice = param.choices[0]
        # Annoté `app_commands.Choice[...]` : le code lit `.value` / `.name`.
        if param.is_choice_annotation():
            return choice
        return choice.value
    t = param.type
    if t is discord.AppCommandOptionType.user:
        other = FakeMember(OTHER_ID, guild_member.guild, "Partenaire")
        guild_member.guild.members.append(other)
        return other
    if t is discord.AppCommandOptionType.integer:
        return max(1, int(param.min_value or 1))
    if t is discord.AppCommandOptionType.number:
        return float(param.min_value or 1)
    if t is discord.AppCommandOptionType.boolean:
        return False
    if t is discord.AppCommandOptionType.string:
        return "test"
    return None


def make_bot():
    """Un bot discord.py non connecté, « prêt », dont les salons sont des faux."""
    bot = commands.Bot(command_prefix=commands.when_mentioned, intents=discord.Intents.default())
    bot._ready = asyncio.Event()
    sent = Sent()
    guild = FakeGuild(sent)

    async def fetch_channel(cid):
        return FakeChannel(cid, guild, sent)

    async def fetch_user(uid):
        return FakeMember(uid, guild)

    bot.fetch_channel = fetch_channel
    bot.fetch_user = fetch_user
    bot.get_channel = lambda cid: FakeChannel(cid, guild, sent)
    bot.get_guild = lambda gid: guild
    bot.get_user = lambda uid: FakeMember(uid, guild)
    return bot


async def load_cogs(bot):
    from unittest import mock
    from discord.ext import tasks

    failed = []
    with mock.patch.object(tasks.Loop, "start", lambda self, *a, **k: None):
        for module in cog_modules():
            try:
                await bot.load_extension(module)
            except Exception as exc:  # pragma: no cover - remonté par le test
                failed.append((module, repr(exc)))
    bot._ready.set()
    return failed


async def autocomplete_value(command, name, param, inter):
    callback = param.autocomplete
    if not callable(callback):
        return None
    if command.binding is not None and getattr(callback, "__self__", None) is None:
        choices = await callback(command.binding, inter, "")
    else:
        choices = await callback(inter, "")
    return choices[0].value if choices else None


async def call_command(bot, command, user_id, channel_id, full=False):
    """Lance une commande. Renvoie (interaction, kwargs)."""
    inter = fake_interaction(bot, command.name, channel_id, user_id)
    kwargs = {}
    for name, param in command._params.items():
        if not param.required and not full:
            continue
        value = value_for(param, inter.user)
        if param.autocomplete:
            value = await autocomplete_value(command, name, param, inter) or value
        kwargs[name] = value
    if command.binding is not None:
        await command.callback(command.binding, inter, **kwargs)
    else:
        await command.callback(inter, **kwargs)
    return inter, kwargs


def sent_views(inter) -> list[discord.ui.View]:
    views = []
    for _kind, kwargs in inter._sent.calls:
        view = kwargs.get("view")
        if isinstance(view, discord.ui.View) and view not in views:
            views.append(view)
    return views


async def click_everything(bot, view, user_id, channel_id, errors: list):
    """Clique chaque bouton / choisit la 1re option de chaque menu, par le
    VRAI chemin de discord.py (`_scheduled_task` : checks puis callback)."""
    for item in list(view.children):
        if getattr(item, "disabled", False) or getattr(item, "url", None):
            continue
        if not isinstance(item, (discord.ui.Button, discord.ui.Select)):
            continue
        inter = fake_interaction(bot, "clic", channel_id, user_id)
        inter.message = FakeMessage(inter._sent)
        if isinstance(item, discord.ui.Select):
            options = getattr(item, "options", None) or []
            values = [options[0].value] if options else []
            if not values:
                continue
            inter.data = {"values": values, "component_type": item.type.value, "custom_id": item.custom_id}
            item._refresh_state(inter, inter.data)
        else:
            inter.data = {"component_type": 2, "custom_id": item.custom_id}

        async def on_error(interaction, error, it, _label=getattr(item, "label", None) or item.custom_id):
            errors.append((type(view).__name__, _label, error))

        view.on_error = on_error
        try:
            await asyncio.wait_for(view._scheduled_task(item, inter), 30)
        except Exception as exc:
            errors.append((type(view).__name__, getattr(item, "label", None), exc))
