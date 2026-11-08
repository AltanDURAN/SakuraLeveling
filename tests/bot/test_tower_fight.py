"""Tour solo en vidéo (08/11/2026) : un essai se joue comme un combat de zone —
« le combat s'engage », la vidéo, puis le récapitulatif à trois pages, avec
l'étage suivant ; le panneau `/tour` ne dévoile rien avant la fin."""

import asyncio
import random
from types import SimpleNamespace

from PIL import Image

from app.application.use_cases.tower import TowerAttempt, TowerStatus
from app.application.use_cases.tower_tickets import TicketStatus
from app.bot.cogs import tower_cog
from app.bot.embeds.battle_summary_embeds import PAGES
from app.bot.embeds.tower_embeds import build_tower_summary
from app.bot.rendering import tower_fight_video
from app.bot.rendering.fight_animation import MAX_UPLOAD_BYTES, Animation
from app.domain.services import tower_service as ts
from app.domain.services.party_combat_service import PartyCombatService
from app.infrastructure.tower import tower_loader
from app.shared.enums import GOLD_EMOJI
from tests.domain.test_gear_passives_combat import member

HERO = dict(max_hp=5000, attack=400, defense=50, crit_chance=20)
WEAK = dict(max_hp=300, attack=5, defense=0)


def _fight(floor_no: int, **stats):
    floor = tower_loader.get_floor(floor_no)
    random.seed(1)
    hero = member(7, **stats)
    hero["name"] = "Ruinflex"
    return floor, PartyCombatService().fight_party_vs_mobs([hero], ts.enemy_setups(floor["enemies"]))


def _outcome(floor_no: int = 10, victory: bool = True, new_level: int = 0) -> TowerAttempt:
    floor, result = _fight(floor_no, **(HERO if victory else WEAK))
    assert result.victory is victory
    reward = ts.first_clear_reward(floor_no, tower_loader.floor_material(floor_no)) if victory else ts.TowerReward()
    return TowerAttempt(floor=floor_no, floor_data=floor, victory=victory, result=result, reward=reward,
                        ticket_used=not victory, tickets_left=1 if victory else 0,
                        best_floor=floor_no if victory else floor_no - 1, new_level=new_level,
                        stat_points=1 if new_level else 0, skill_points=1 if new_level else 0)


def _pages(summary):
    return [builder(summary) for _, builder in PAGES]


def test_le_recapitulatif_d_une_victoire_a_les_pages_des_zones():
    outcome = _outcome(10, victory=True, new_level=12)
    material = tower_loader.floor_material(10)
    rewards, details, journal = _pages(build_tower_summary(outcome, {material: "Croc de gobelin"}))

    assert rewards.title == "🗼 Étage 10 — Le chef de clan : franchi !"
    assert "Nouveau record : **étage 10**" in rewards.description and "Ticket gardé (1 disponible)" in rewards.description
    hero = rewards.fields[0].value
    assert f"{GOLD_EMOJI} **" in hero and "XP" in hero and "Croc de gobelin" in hero
    assert "🆙 **Niveau 12 !**" in hero
    assert "seul, à PV et mana pleins" in rewards.footer.text

    # Seul : ni graphique de part de victoire, ni pourcentages ; les ennemis, oui.
    names = [f.name for f in details.fields]
    assert "🏅 Part de victoire" not in names and not any("% de la victoire" in n for n in names)
    assert "(100%)" not in details.fields[0].value
    assert "💀 **Gobelin Supérieur** — vaincu" in details.fields[-1].value
    assert journal.description and journal.title.startswith("📜 Journal du combat — Étage 10")


def test_le_recapitulatif_d_une_defaite_dit_ce_qu_il_restait():
    outcome = _outcome(37, victory=False)
    rewards, details, _ = _pages(build_tower_summary(outcome))
    assert rewards.title.endswith(": défaite")
    assert "Ticket perdu — 0 restant" in rewards.description
    assert "Aucune récompense" in rewards.fields[0].value
    assert "❤️ **Ogre démoniaque** —" in details.fields[-1].value and "PV" in details.fields[-1].value


def test_la_video_d_un_etage(tmp_path):
    floor, result = _fight(37, **HERO)
    anim = tower_fight_video.render_tower_video(floor, result, "", tmp_path / "etage.gif")
    assert anim is not None and 0 < anim.size_bytes <= MAX_UPLOAD_BYTES and anim.duration_s > 2
    assert Image.open(anim.path).info.get("loop") is None                 # une seule lecture


def test_la_scene_est_celle_de_l_image_de_l_etage():
    scene = tower_fight_video.floor_scene(tower_loader.get_floor(37))
    assert scene["mob"] is None and len(scene["mobs"]) == 3 and len(scene["formation"]) >= 3
    assert all(m["power_score"] for m in scene["mobs"])                    # comme un combat de zone
    single = tower_fight_video.floor_scene(tower_loader.get_floor(1))
    assert single["mob"]["code"] == "slime" and "mobs" not in single


# ----------------------------------------------------------------- le bot --
class Message:
    def __init__(self, message_id):
        self.id = message_id
        self.edits = []

    async def edit(self, **kwargs):
        view = kwargs.get("view")
        buttons = [(c.label, c.disabled) for c in view.children] if view is not None else None
        self.edits.append({**kwargs, "buttons": buttons})
        return self


class Channel:
    def __init__(self):
        self.messages = {}

    def get_partial_message(self, message_id):
        return self.messages.setdefault(message_id, Message(message_id))


class Response:
    def __init__(self):
        self.done, self.sent = False, []

    def is_done(self):
        return self.done

    async def defer(self):
        self.done = True

    async def send_message(self, text, ephemeral=False):
        self.done = True
        self.sent.append(text)


class Followup:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, *, embed=None, wait=False, ephemeral=False, **_):
        self.sent.append(SimpleNamespace(content=content, embed=embed, ephemeral=ephemeral))
        return SimpleNamespace(id=100 + len(self.sent))


def _interaction(channel):
    avatar = SimpleNamespace(replace=lambda size: SimpleNamespace(url="https://cdn.example/a.png"))
    user = SimpleNamespace(id=7, name="ruin", display_name="Ruinflex", display_avatar=avatar)
    return SimpleNamespace(user=user, response=Response(), followup=Followup(), channel=channel, message=None)


def _state(best: int, tickets: int = 1) -> TowerStatus:
    return TowerStatus(best_floor=best, next_floor=best + 1, floor=tower_loader.get_floor(best + 1),
                       tickets=TicketStatus(available=tickets, allowance=1, has_bonus=False),
                       daily_claimed=False, daily=ts.TowerReward())


def _cog():
    cog = object.__new__(tower_cog.TowerCog)
    cog.bot, cog.climbing = None, set()
    return cog


def test_un_essai_se_joue_en_video_puis_recapitulatif(monkeypatch, tmp_path):
    outcome = _outcome(10, victory=True)
    gif = tmp_path / "combat.gif"
    gif.write_bytes(b"GIF89a")
    rendered = []

    def fake_render(floor, result, avatar_url, out):
        rendered.append(avatar_url)
        return Animation(path=gif, duration_s=0.0, frames=1, size_bytes=6)

    monkeypatch.setattr(tower_cog, "_attempt", lambda user: (outcome, None, {}))
    monkeypatch.setattr(tower_cog, "_status", lambda user: (_state(outcome.best_floor), "Ruinflex", {}))
    monkeypatch.setattr(tower_cog, "_floor_image", lambda floor: None)
    monkeypatch.setattr(tower_cog, "GENERATED_ENCOUNTERS_DIR", tmp_path)
    monkeypatch.setattr(tower_fight_video, "render_tower_video", fake_render)

    async def scenario():
        channel, cog = Channel(), _cog()
        interaction = _interaction(channel)
        panel = tower_cog.TowerView(cog, 7, _state(9))
        panel.message = Message(1)
        await cog.climb(interaction, panel)
        return interaction, channel, cog, panel

    interaction, channel, cog, panel = asyncio.run(scenario())
    assert interaction.followup.sent[0].embed.title == "⚔️ Étage 10 — Le chef de clan — le combat s'engage"
    video, recap = channel.messages[101].edits
    assert video["embed"].image.url == "attachment://combat.gif" and len(video["attachments"]) == 1
    assert rendered == ["https://cdn.example/a.png"]                       # l'avatar du joueur
    assert not gif.exists()                                                # Discord garde sa copie
    assert isinstance(recap["view"], tower_cog.TowerSummaryView) and recap["attachments"] == []
    assert recap["embed"].title == "🗼 Étage 10 — Le chef de clan : franchi !"
    assert ("Tenter l'étage 11", False) in recap["buttons"]               # on enchaîne d'ici
    # Le panneau : verrouillé pendant le combat, à jour seulement après la vidéo.
    busy, refreshed = panel.message.edits
    assert ("Combat en cours…", True) in busy["buttons"] and "embed" not in busy
    assert ("Tenter l'étage 11", False) in refreshed["buttons"]
    assert cog.climbing == set()


def test_sans_ticket_pas_de_bouton_pour_l_etage_suivant():
    async def views():
        cog = _cog()
        summary = build_tower_summary(_outcome(37, victory=False))
        keep = tower_cog.TowerSummaryView(cog, summary, 7, 37, 1, None)
        none = tower_cog.TowerSummaryView(cog, summary, 7, 37, 0, None)
        return [c.label for c in keep.children], [c.label for c in none.children]

    keep, none = asyncio.run(views())
    assert "Tenter l'étage 37" in keep and not any(str(label).startswith("Tenter") for label in none)


def test_un_seul_combat_a_la_fois(monkeypatch):
    monkeypatch.setattr(tower_cog, "_attempt", lambda user: (_ for _ in ()).throw(AssertionError("pas d'essai")))

    async def scenario():
        cog = _cog()
        cog.climbing.add(7)
        interaction = _interaction(Channel())
        await cog.climb(interaction, None)
        return interaction

    assert asyncio.run(scenario()).response.sent == [tower_cog.BUSY]
