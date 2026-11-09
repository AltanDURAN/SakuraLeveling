"""`/admin lancer_saison` : le déroulé complet sur un faux bot — sauvegarde
d'abord (et rien ne bouge si elle échoue), combats et boss arrêtés, joueurs
remis à zéro, retour au règlement pour tous, photo, annonce dans l'accueil —
et les commandes des joueurs fermées pendant le lancement."""

import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.bot import rules_gate, season_launch
from app.bot.views.season_launch_view import SeasonConfirmModal, SeasonLaunchView, build_preview_embed
from app.infrastructure.db.base import Base
from app.infrastructure.db.models.adventurer_model import AdventurerModel
from app.infrastructure.db.models.monitoring_model import GameEventModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel
from app.infrastructure.db.models.rules_model import RulesAcceptanceModel
from app.infrastructure.db.repositories.player_repository import PlayerRepository


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    @contextmanager
    def get_session():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    monkeypatch.setattr(season_launch, "get_db_session", get_session)
    monkeypatch.setattr(season_launch, "DRAIN_SECONDS", 0)
    with get_session() as s:
        repo = PlayerRepository(s)
        pid = repo.get_or_create_by_discord_id(7, "alice", "Alice").player.id
        repo.apply_progression(pid, 12, 0, 11)
        repo.add_gold(pid, 900, source="combat")
        now = datetime.now(UTC).replace(tzinfo=None)
        s.add(RulesAcceptanceModel(discord_id=7, version=1, accepted_at=now))
        s.add(AdventurerModel(discord_id=7, started_at=now, how="passe"))
        s.commit()
    yield SimpleNamespace(session=get_session, pid=pid)
    engine.dispose()


class _Channel:
    def __init__(self):
        self.sent = []
        self.guild = SimpleNamespace(id=1)

    async def send(self, **kwargs):
        self.sent.append(kwargs)
        return SimpleNamespace(jump_url="https://discord.com/channels/1/2/3")


class _Bot:
    def __init__(self, gate_seen):
        self.channel = _Channel()
        self.channel_ids = []
        self.calls = []
        bot = self

        class Encounters:
            active_encounters = {}

            def force_end_encounter(self):
                bot.calls.append("encounters")
                return True, "Encounter(s) actif(s) annulé(s) : **Slime**."

        class Boss:
            async def admin_stop_boss(self):
                bot.calls.append("boss")
                return False, "Aucun world boss actif à arrêter."

        class Bridge:
            async def reset_journey_roles(self):
                bot.calls.append("journey")
                gate_seen.append(season_launch.is_closed())
                return True, "3 membre(s) renvoyé(s) au règlement (rangs et Aventurier retirés), 0 échec(s)."

        class Monitoring:
            async def take_snapshots_now(self):
                bot.calls.append("snapshot")
                return 1

        self.cogs = {"EncounterCog": Encounters(), "WorldBossCog": Boss(),
                     "AdminBridgeCog": Bridge(), "MonitoringCog": Monitoring()}

    def get_cog(self, name):
        return self.cogs.get(name)

    def get_channel(self, channel_id):
        self.channel_ids.append(channel_id)
        return self.channel


def test_lancement_complet(db, monkeypatch):
    monkeypatch.setattr(season_launch, "backup_sqlite", lambda label: Path(f"/srv/lita_v2_{label}.db"))
    monkeypatch.setattr(season_launch.settings, "welcome_channel_id", 21)
    monkeypatch.setattr(season_launch.settings, "rules_channel_id", 22)
    monkeypatch.setattr(season_launch.settings, "tutorial_channel_id", 23)
    monkeypatch.setitem(rules_gate._accepted, 7, 1)
    gate_seen = []
    bot = _Bot(gate_seen)

    result = asyncio.run(season_launch.launch(bot, 1, "everyone"))

    assert all(ok for ok, _ in result.steps), result.steps
    assert result.backup.name == "lita_v2_avant_saison_1.db"
    assert bot.calls == ["encounters", "boss", "journey", "snapshot"]
    assert gate_seen == [True] and not season_launch.is_closed(), "fermé pendant, rouvert après"
    with db.session() as s:
        assert s.get(PlayerProgressionModel, db.pid).level == 1
        assert s.execute(select(GameEventModel.kind)).scalars().all() == ["season"]
        # Tout le monde repart du règlement (décision de l'auteur, 09/11/2026).
        assert s.execute(select(func.count()).select_from(RulesAcceptanceModel)).scalar_one() == 0
        assert s.execute(select(func.count()).select_from(AdventurerModel)).scalar_one() == 0
    assert 7 not in rules_gate._accepted, "le bot oublie les acceptations gardées en mémoire"
    # L'annonce part dans l'accueil : avec le règlement, le seul salon que tous voient encore.
    assert bot.channel_ids == [21]
    post = bot.channel.sent[0]
    assert post["content"] == "@everyone" and post["allowed_mentions"].everyone
    assert post["embed"].title == "🌸 La saison 1 commence !"
    description = post["embed"].description
    assert "dure un an" in description and "<#22>" in description
    assert "<#23>" not in description, "un salon invisible s'afficherait « sans accès »"
    assert post["files"] and post["files"][0].filename == season_launch.SEASON_IMAGE
    assert result.announcement_url


def test_sans_sauvegarde_rien_ne_bouge(db, monkeypatch):
    def broken(label):
        raise season_launch.BackupError("Base SQLite introuvable.")

    monkeypatch.setattr(season_launch, "backup_sqlite", broken)
    bot = _Bot([])
    with pytest.raises(season_launch.LaunchError):
        asyncio.run(season_launch.launch(bot, 1, "off"))
    assert bot.calls == [] and not season_launch.is_closed()
    with db.session() as s:
        assert s.get(PlayerProgressionModel, db.pid).level == 12
        assert s.execute(select(func.count()).select_from(GameEventModel)
                         .where(GameEventModel.kind == "season")).scalar_one() == 0
    assert bot.channel.sent == []


def test_les_commandes_des_joueurs_sont_fermees_pendant_le_lancement(monkeypatch):
    sent = []

    class _Response:
        def is_done(self):
            return False

        async def send_message(self, content, ephemeral=False):
            sent.append((content, ephemeral))

    def interaction(user_id, kind=discord.InteractionType.application_command):
        return SimpleNamespace(user=SimpleNamespace(id=user_id), type=kind, response=_Response())

    monkeypatch.setattr(season_launch.settings, "admin_discord_ids", "99")
    assert asyncio.run(season_launch.allow(interaction(5)))
    monkeypatch.setitem(season_launch._state, "closed", True)
    assert not asyncio.run(season_launch.allow(interaction(5)))
    assert sent == [(season_launch.CLOSED_MESSAGE, True)]
    assert not asyncio.run(season_launch.allow(interaction(5, discord.InteractionType.autocomplete)))
    assert len(sent) == 1, "pas de réponse à une autocomplétion"
    assert asyncio.run(season_launch.allow(interaction(99))), "l'admin passe"


def test_l_apercu_et_la_confirmation(db):
    preview = season_launch.preview(_Bot([]))
    assert preview.report.players == 1 and preview.report.gold_total == 900 and preview.report.max_level == 12
    assert preview.report.cleared["rules_acceptances"] == 1 and preview.report.cleared["adventurers"] == 1
    embed = build_preview_embed(preview, 2, "here")
    assert "SAISON 2" in embed.description and len(embed) < 6000
    assert any("avec @here" in f.value and "accueil" in f.value for f in embed.fields)
    journey = next(f for f in embed.fields if "règlement" in f.name)
    assert "1 règlement(s) accepté(s)" in journey.value and "admins compris" in journey.value

    async def build():
        origin = SimpleNamespace(user=SimpleNamespace(id=7))
        view = SeasonLaunchView(origin, 2, "here")
        return view, SeasonConfirmModal(view)

    view, modal = asyncio.run(build())
    assert view.launch_button.label == "Lancer la saison 2"
    assert modal.answer.placeholder == "SAISON 2" and modal.title == "Lancer la saison 2"


def test_la_carte_de_la_saison():
    from io import BytesIO

    from PIL import Image

    from app.bot.rendering.welcome_card import HEIGHT, WIDTH, compose_season_card

    img = Image.open(BytesIO(compose_season_card(1)))
    assert img.size == (WIDTH, HEIGHT)
