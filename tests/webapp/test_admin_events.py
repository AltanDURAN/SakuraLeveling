"""Admin web : Monde › Événements (11/11/2026, page refaite à la demande de
l'auteur) — aperçus construits par le code du bot, réglages enregistrés sans
recharger, historique réel, apparition immédiate. Sur une copie du contenu.
Le salon de chaque événement : les petits dans le général, le salon des
événements pour les gros (décision de l'auteur, 10/11/2026)."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from app.bot.embeds import event_embeds
from app.infrastructure.events import event_config_loader as cfg
from tests.webapp.test_admin_content_crud import _same_origin, content  # noqa: F401  (fixtures)
from tests.webapp.test_admin_pages_smoke import client  # noqa: F401  (fixture)

FORGE = {"enabled": "on", "cadence_times": "1", "cadence_per_days": "3", "max_level": "10",
         "window_minutes": "5"}


@pytest.fixture
def events_copy(content, monkeypatch):
    monkeypatch.setattr(cfg, "CONTENT_PATH", content / "events.json")
    cfg.clear_cache()
    yield content / "events.json"
    cfg.clear_cache()


def _page_data(text: str) -> dict:
    return json.loads(text.split('id="ev-data">')[1].split("</script>")[0])


def _saved(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_la_page_montre_les_trois_evenements(client, events_copy):
    r = client.get("/admin/events")
    assert r.status_code == 200
    data = _page_data(r.text)
    assert [e["type"] for e in data["events"]] == list(cfg.EVENT_TYPES)
    assert data["channels"] == cfg.CHANNELS
    chest = data["events"][0]
    assert chest["config"]["loot"] and chest["image_url"].startswith("/assets/events/chest.png")
    assert {s["code"] for s in chest["states"]} == {"spawn", "opened", "expired"}
    # Le coffre ne donne que ce qui va dans l'inventaire : ni pièce d'équipement, ni carte.
    categories = {i["category"] for i in data["items"]}
    assert "carte" not in categories and "arme" not in categories and "potion_soin" in {i["code"] for i in data["items"]}
    assert set(data["history"]) >= set(cfg.EVENT_TYPES)
    # L'ancienne fiche mène à la page, sur le bon événement.
    old = client.get("/admin/events/sacred_forge/edit", follow_redirects=False)
    assert old.status_code == 303 and old.headers["location"] == "/admin/events#sacred_forge"


def test_enregistrer_sans_recharger(client, events_copy):
    config = _page_data(client.get("/admin/events").text)["events"][0]["config"]
    config.update(enabled=False, channel="events", expire_after_minutes=360,
                  loot=[{"kind": "item", "item_code": "potion_soin", "quantity": 2, "weight": 3},
                        {"kind": "gold", "gold_amount": 250, "weight": 1},
                        {"kind": "nothing", "weight": 0}])               # poids 0 : ignorée
    r = client.post("/admin/events/save", json={"type": "chest", "config": config})
    assert r.status_code == 200 and r.json()["ok"], r.text
    saved = _saved(events_copy)["chest"]
    assert saved["enabled"] is False and saved["channel"] == "events" and len(saved["loot"]) == 2
    assert cfg.chest_lifetime_minutes() == 360 and cfg.channel_of("chest") == cfg.CHANNEL_EVENTS
    # Bornes : ramenées dans les bornes ; erreurs de structure : refusées.
    r = client.post("/admin/events/save", json={"type": "sacred_forge", "config": {
        "enabled": True, "cadence": {"times": 99, "per_days": 0}, "max_level": 50, "window_minutes": 0}})
    forge = r.json()["config"]
    assert forge["cadence"] == {"times": 24, "per_days": 1} and forge["max_level"] == 10 and forge["window_minutes"] == 1
    bad = client.post("/admin/events/save", json={"type": "chest", "config": {**config, "loot": [
        {"kind": "item", "item_code": "objet_inconnu", "quantity": 1, "weight": 1}]}})
    assert bad.status_code == 400 and "objet_inconnu" in bad.json()["error"]
    assert client.post("/admin/events/save", json={"type": "chest", "config": {**config, "loot": []}}).status_code == 400
    assert client.post("/admin/events/save", json={"type": "dragon", "config": {}}).status_code == 400
    assert _saved(events_copy)["chest"]["channel"] == "events"             # rien d'écrit sur un refus


def test_l_ancien_formulaire_marche_encore(client, events_copy):
    r = client.post("/admin/events/sacred_forge", data={**FORGE, "channel": "events"}, follow_redirects=False)
    assert r.status_code == 303 and cfg.channel_of("sacred_forge") == cfg.CHANNEL_EVENTS
    # Une valeur inconnue, ou pas de champ, ne change rien.
    client.post("/admin/events/sacred_forge", data={**FORGE, "channel": "ailleurs"})
    client.post("/admin/events/sacred_forge", data=FORGE)
    assert cfg.channel_of("sacred_forge") == cfg.CHANNEL_EVENTS and cfg.channel_of("chest") == cfg.CHANNEL_GENERAL
    form = {"enabled": "on", "cadence_times": "1", "cadence_per_days": "1", "level_scaling_pct": "2",
            "expire_after_minutes": "0", "loot_kind": "gold", "loot_gold": "100", "loot_weight": "10",
            "loot_item_code": "", "loot_quantity": "1"}
    client.post("/admin/events/chest", data=form)
    assert cfg.chest_lifetime_minutes() == 5                     # plancher : jamais « tout de suite »


def test_les_apercus_sont_ceux_du_bot(client, events_copy):
    def preview(event_type, state, **extra):
        config = _page_data(client.get("/admin/events").text)["events"][list(cfg.EVENT_TYPES).index(event_type)]["config"]
        config.update(extra.pop("config", {}))
        r = client.post("/admin/events/preview", json={"type": event_type, "state": state, "config": config, **extra})
        assert r.status_code == 200, r.text
        return r.json()

    spawn = preview("chest", "spawn")
    assert spawn["embeds"][0]["title"] == event_embeds.chest_spawn_embed().title and spawn["image_in_embed"]
    assert [b["label"] for b in spawn["buttons"]] == ["Ouvrir le coffre"]
    # Coffre ouvert : la récompense choisie, grossie au niveau du gagnant (2 %/niveau au niveau 50 = ×2).
    opened = preview("chest", "opened", level=50, row=0, config={
        "level_scaling_pct": 2, "loot": [{"kind": "gold", "gold_amount": 100, "weight": 1}]})
    assert "200 or" in opened["embeds"][0]["description"] and not opened["buttons"] and not opened["image_in_embed"]
    # Réglages en cours d'édition, pas encore enregistrés : la petite fille attend 9 minutes.
    girl = preview("little_girl", "spawn", config={"resolve_after_minutes": 9})
    assert "**9 minutes**" in girl["embeds"][0]["description"] and len(girl["buttons"]) == 2
    trap = preview("little_girl", "trap", level=30, config={"gold_loss_per_level": 10})
    lines = trap["embeds"][0]["fields"][0]["value"]
    assert trap["embeds"][0]["title"].startswith("😈") and "−300 or" in lines and "@Kaori" in lines
    assert "Noël" not in json.dumps(trap) and "petite fille" not in lines   # secret : rien sur le cadeau
    assert preview("sacred_forge", "closed")["embeds"][0]["title"].startswith("🔥")
    assert "niveau 7" in preview("sacred_forge", "spawn", config={"max_level": 7})["embeds"][0]["description"]


def test_les_boutons_de_l_apercu_sont_ceux_des_vues_du_bot():
    from app.bot.cogs.event_cog import ChestView, ForgeView, LittleGirlView

    async def labels(view_cls):
        view = view_cls()
        return [(str(b.emoji), b.label, b.style.name) for b in view.children]

    for event_type, view_cls in (("chest", ChestView), ("little_girl", LittleGirlView), ("sacred_forge", ForgeView)):
        assert asyncio.run(labels(view_cls)) == list(event_embeds.BUTTONS[event_type]), event_type


def test_faire_apparaitre_maintenant(client, events_copy):
    from app.infrastructure.db.repositories.admin_command_repository import AdminCommandRepository
    from app.infrastructure.db.repositories.event_repository import EventRepository
    from app.infrastructure.db.session import get_db_session

    r = client.post("/admin/events/little_girl/spawn")
    assert r.status_code == 200 and r.json()["ok"]
    with get_db_session() as session:
        last = AdminCommandRepository(session).list_recent(1)[0]
        assert last.action == "spawn_event" and '"little_girl"' in last.payload_json
        EventRepository(session).create("chest", 1)
        session.commit()
    # Déjà un coffre en cours : on ne double pas.
    assert client.post("/admin/events/chest/spawn").status_code == 409


def test_l_historique_raconte_ce_qui_s_est_passe(client, events_copy):
    from app.infrastructure.db.repositories.event_repository import EventRepository
    from app.infrastructure.db.session import get_db_session
    from webapp.admin.routers.events_router import history

    with get_db_session() as session:
        repo = EventRepository(session)
        girl = repo.create("little_girl", 1, expires_at=datetime.now(UTC) + timedelta(minutes=5))
        repo.upsert_participation(girl.id, 1, choice="aider")
        repo.set_status(girl.id, "resolved")
        repo.set_payload(girl.id, {"trap": True, "help": 1, "ignore": 0})
        lonely = repo.create("little_girl", 1)
        repo.set_status(lonely.id, "resolved")
        forge = repo.create("sacred_forge", 1)
        repo.set_status(forge.id, "resolved")
        chest = repo.create("chest", 1)
        repo.claim_chest_winner(chest.id, 1)
        session.commit()
        h = history(session)
    assert h["little_girl"]["month"] == 2 and h["little_girl"]["help"] == 1 and h["little_girl"]["alone"] == 1
    assert h["little_girl"]["trap"] == 1 and h["little_girl"]["real"] == 0
    assert h["sacred_forge"]["uses"] == 0 and h["sacred_forge"]["empty"] == 1
    assert h["chest"]["opened"] == 1 and h["chest"]["winners"][0]["count"] == 1 and h["chest"]["active"] is None


def test_deposer_l_image_d_un_evenement(client, events_copy, tmp_path, monkeypatch):
    import io

    from PIL import Image

    from webapp.admin.routers import events_router

    monkeypatch.setattr(events_router, "EVENTS_ASSETS_DIR", tmp_path)
    buf = io.BytesIO()
    Image.new("RGB", (1200, 600), (120, 40, 160)).save(buf, "PNG")
    r = client.post("/admin/events/sacred_forge/image", files={"image": ("forge.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert (tmp_path / r.json()["image"]).is_file() and _saved(events_copy)["sacred_forge"]["image"] == r.json()["image"]
    bad = client.post("/admin/events/sacred_forge/image", files={"image": ("notes.txt", b"pas une image", "text/plain")})
    assert bad.status_code == 400
