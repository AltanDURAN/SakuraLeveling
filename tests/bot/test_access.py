"""Parcours d'arrivée sur Discord (08/11/2026) : le règlement accepté donne
le Rang F, le tutoriel fini ou passé donne Aventurier, qui revient retrouve
ses rôles, et rien n'est jamais retiré ; les salons suivent le plan."""

import asyncio
from types import SimpleNamespace

import discord
import pytest

from app.application.use_cases.member_access import MemberAccess
from app.bot import access, rank_roles, rules_gate
from app.bot import access_plan as ap
from app.bot.cogs import onboarding_cog, tutorial_cog
from app.infrastructure.config.settings import Settings, settings

GUILD = 1000
RANKS = {"F": 10, "E": 11, "D": 12}
ADV = 99
DEFAULT_ROLE = 7
ZONES = [{"name": "Clairière sinistre", "channel_id": 31, "rank": "F"},
         {"name": "Cimetière", "channel_id": 32, "rank": "E"}]


class Role:
    def __init__(self, role_id, name=""):
        self.id, self.name = role_id, name or f"r{role_id}"


class Guild:
    def __init__(self, members=()):
        self.id = GUILD
        self.members = list(members)
        self.member_count = len(self.members)
        self.roles = {i: Role(i) for i in [GUILD, *RANKS.values(), ADV, DEFAULT_ROLE]}

    def get_role(self, role_id):
        return self.roles.get(role_id)

    def get_member(self, member_id):
        return next((m for m in self.members if m.id == member_id), None)

    def get_channel(self, channel_id):
        return None


class Member:
    bot = False

    def __init__(self, member_id=5, role_ids=(), guild=None):
        self.id = member_id
        self.name = self.display_name = f"m{member_id}"
        self.mention = f"<@{member_id}>"
        self.guild = guild or Guild()
        self.roles = [Role(r) for r in role_ids]
        self.sent = []

    @property
    def role_ids(self):
        return [r.id for r in self.roles]

    async def add_roles(self, *roles, reason=""):
        self.roles.extend(roles)

    async def remove_roles(self, *roles, reason=""):
        gone = {r.id for r in roles}
        self.roles = [r for r in self.roles if r.id not in gone]

    async def send(self, **kwargs):
        self.sent.append(kwargs)


@pytest.fixture()
def states(monkeypatch):
    """La base remplacée : discord_id → où il en est du parcours."""
    known: dict[int, MemberAccess] = {}
    monkeypatch.setattr(Settings, "rank_roles", property(lambda self: RANKS))
    monkeypatch.setattr(settings, "adventurer_role_id", ADV)
    monkeypatch.setattr(settings, "discord_guild_id", GUILD)
    monkeypatch.setattr(access, "_state", lambda discord_id: known.get(discord_id, MemberAccess()))
    monkeypatch.setattr(access, "_states", lambda: dict(known))
    monkeypatch.setattr(access, "list_zones", lambda: ZONES)
    monkeypatch.setattr(rank_roles, "_earned_rank", lambda discord_id: "F")
    monkeypatch.setattr(rank_roles, "_save_earned_rank", lambda discord_id, rank: None)
    return known


def test_sans_reglement_aucun_role(states):
    member = Member()
    states[5] = MemberAccess(accepted=False, adventurer=True)
    asyncio.run(access.restore(member))
    assert member.role_ids == []


def test_le_reglement_donne_le_rang_f_puis_le_tutoriel_aventurier(states):
    member = Member()
    states[5] = MemberAccess(accepted=True)
    asyncio.run(access.restore(member))
    assert member.role_ids == [RANKS["F"]]
    states[5] = MemberAccess(accepted=True, adventurer=True)
    asyncio.run(access.restore(member))
    assert member.role_ids == [RANKS["F"], ADV]


def test_rien_n_est_jamais_retire(states):
    member = Member(role_ids=[RANKS["D"], 555])               # un rang gagné, un rôle hors parcours
    states[5] = MemberAccess(accepted=True, adventurer=True)
    asyncio.run(access.restore(member))
    assert member.role_ids == [RANKS["D"], 555, ADV]


def test_le_rattrapage_ne_donne_que_ce_qui_manque(states):
    guild = Guild()
    done = Member(1, [RANKS["F"], ADV], guild)
    late = Member(2, [], guild)
    only_rules = Member(3, [], guild)
    stranger = Member(4, [], guild)
    guild.members = [done, late, only_rules, stranger]
    states.update({1: MemberAccess(True, True), 2: MemberAccess(True, True), 3: MemberAccess(True, False)})
    assert asyncio.run(access.reconcile(guild)) == (2, 1)
    assert late.role_ids == [RANKS["F"], ADV] and only_rules.role_ids == [RANKS["F"]]
    assert stranger.role_ids == [] and done.role_ids == [RANKS["F"], ADV]
    assert asyncio.run(access.reconcile(guild)) == (0, 0)


# ------------------------------------------------------------- les clics
class Response:
    def __init__(self):
        self.sent, self.edited = [], []

    def is_done(self):
        return bool(self.sent or self.edited)

    async def send_message(self, content=None, **kwargs):
        self.sent.append((content, kwargs))

    async def edit_message(self, **kwargs):
        self.edited.append(kwargs)


def test_accepter_le_reglement_ouvre_le_tutoriel(states, monkeypatch):
    def write_and_remember(discord_id, version):
        states[discord_id] = MemberAccess(accepted=True)
        return True, rules_gate.rules_uc.Acceptance(version, None)

    monkeypatch.setattr(rules_gate, "_write", write_and_remember)
    member = Member()
    interaction = SimpleNamespace(user=member, client=None, guild_id=GUILD, response=Response(),
                                  message=SimpleNamespace(flags=SimpleNamespace(ephemeral=False)))
    asyncio.run(rules_gate.accept(interaction))
    rules_gate._accepted.clear()
    assert member.role_ids == [RANKS["F"]]
    text, kwargs = interaction.response.sent[0]
    assert "**Rang F**" in text and kwargs["ephemeral"]
    assert [b.url for b in kwargs["view"].children] == [
        f"https://discord.com/channels/{GUILD}/{settings.tutorial_channel_id}"]


def test_une_reponse_part_a_temps_meme_si_discord_traine(states, monkeypatch):
    async def slow(interaction):
        await asyncio.sleep(5)

    monkeypatch.setattr(access, "restore_for", slow)

    async def run():
        loop = asyncio.get_running_loop()
        start = loop.time()
        await access.restore_soon(SimpleNamespace(), wait=0.05)
        return loop.time() - start

    assert asyncio.run(run()) < 1


def test_finir_ou_passer_le_tutoriel_donne_aventurier(states, monkeypatch):
    def skip(*_):
        states[5] = MemberAccess(accepted=True, adventurer=True)    # ce qu'écrit tutorial.skip

    monkeypatch.setattr(tutorial_cog.tutorial, "skip", skip)
    monkeypatch.setattr(tutorial_cog, "get_db_session", lambda: _NullSession())
    member = Member(role_ids=[RANKS["F"]])
    interaction = SimpleNamespace(user=member, client=None, guild_id=GUILD, response=Response())

    async def run():
        view = tutorial_cog.TutorialView(player_id=1)
        await view._skip_all(interaction)

    asyncio.run(run())
    assert member.role_ids == [RANKS["F"], ADV]
    edit = interaction.response.edited[0]
    assert "**Aventurier**" in edit["embed"].description
    urls = [b.url for b in edit["view"].children]
    assert urls == [f"https://discord.com/channels/{GUILD}/{access.general_channel_id()}",
                    f"https://discord.com/channels/{GUILD}/31"]


class _NullSession:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


def test_un_nouveau_venu_ne_recoit_aucun_rang(states, monkeypatch):
    monkeypatch.setattr(settings, "default_member_role_id", DEFAULT_ROLE)
    monkeypatch.setattr(settings, "welcome_channel_id", 0)
    monkeypatch.setattr(onboarding_cog, "get_db_session", lambda: _NullSession())
    monkeypatch.setattr(onboarding_cog.PlayerRepository, "get_or_create_by_discord_id",
                        lambda self, **kwargs: None)

    def no_card(*args):
        raise RuntimeError("pas de rendu dans ce test")

    monkeypatch.setattr(onboarding_cog, "compose_welcome_card", no_card)
    member = Member()
    member.display_avatar = SimpleNamespace(url="https://cdn.example/a.png")
    cog = object.__new__(onboarding_cog.OnboardingCog)
    asyncio.run(onboarding_cog.OnboardingCog.on_member_join(cog, member))
    assert member.role_ids == [DEFAULT_ROLE]                         # ni rang ni Aventurier
    message = member.sent[0]
    assert "accepte-le" in message["embed"].description
    assert [b.label for b in message["view"].children] == ["Lire le règlement"]

    states[6] = MemberAccess(accepted=True, adventurer=True)           # parti puis revenu
    back = Member(6)
    back.display_avatar = member.display_avatar
    asyncio.run(onboarding_cog.OnboardingCog.on_member_join(cog, back))
    assert back.role_ids == [DEFAULT_ROLE, RANKS["F"], ADV]
    assert "Bon retour" in back.sent[0]["embed"].description


# ------------------------------------------------------------- les salons
class Channel:
    def __init__(self, channel_id, name, overwrites=None, kind=discord.ChannelType.text, position=0,
                 category_id=None):
        self.id, self.name, self.type, self.position, self.category_id = (
            channel_id, name, kind, position, category_id)
        self._overwrites = overwrites or {}
        self.calls = []

    @property
    def overwrites(self):
        return {discord.Object(id=target): discord.PermissionOverwrite.from_pair(
            discord.Permissions(allow), discord.Permissions(deny))
            for target, (allow, deny) in self._overwrites.items()}

    async def set_permissions(self, target, *, overwrite=None, reason=None):
        self.calls.append(target.id)
        if overwrite is None:
            self._overwrites.pop(target.id, None)
        else:
            allow, deny = overwrite.pair()
            self._overwrites[target.id] = (allow.value, deny.value)


def test_le_plan_puis_son_application(states, monkeypatch):
    monkeypatch.setattr(settings, "welcome_channel_id", 21)
    monkeypatch.setattr(settings, "rules_channel_id", 22)
    monkeypatch.setattr(settings, "tutorial_channel_id", 23)
    monkeypatch.setattr(settings, "tower_channel_id", 24)
    view = ap.VIEW_CHANNEL
    channels = [
        Channel(40, "Sakura", kind=discord.ChannelType.category, position=1),
        Channel(25, "général", {GUILD: (0, view), RANKS["E"]: (view, 0)}, position=0, category_id=40),
        Channel(26, "vocal", kind=discord.ChannelType.voice, position=1, category_id=40),
        Channel(27, "staff", {GUILD: (0, view), 555: (view, 0)}, position=2, category_id=40),
        Channel(41, "Accueil", kind=discord.ChannelType.category, position=0),
        Channel(21, "bienvenue", position=0, category_id=41),
        Channel(23, "tutoriel", position=1, category_id=41),
        Channel(32, "cimetière", {GUILD: (0, view), RANKS["E"]: (view, 0), RANKS["D"]: (view, 0)},
                position=3, category_id=40),
    ]
    plan = access.plan(GUILD, channels)
    titles = [change.title for change in plan.changes]
    assert titles == ["📁 Accueil", "#bienvenue", "#tutoriel", "📁 Sakura", "#général", "🔊 vocal"]
    assert plan.private == ["staff"]                                   # jamais touché
    assert [c.after for c in plan.changes][:3] == ["aventuriers", "tout le monde, lecture seule",
                                                   "Rang F et plus"]

    guild = Guild()
    done, failed = asyncio.run(access.apply(guild, channels, plan.changes))
    assert (done, failed) == (len(plan.changes), [])
    assert access.plan(GUILD, channels).changes == []                  # tout est en place
    general = channels[1]
    assert general._overwrites == {GUILD: (0, view), ADV: (view, 0)}
    assert general.calls[0] == ADV                                     # ce qui ouvre d'abord
