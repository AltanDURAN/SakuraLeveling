"""Purge des anciens messages de fuite : elle ne retire QUE ces messages, par
lots s'ils ont moins de 14 jours, et ne fait rien sans --confirm."""

import asyncio
import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_path = Path(__file__).resolve().parents[2] / "scripts/purge_flee_messages.py"
_spec = importlib.util.spec_from_file_location("purge_flee_messages", _path)
PURGE = importlib.util.module_from_spec(_spec)
sys.modules["purge_flee_messages"] = PURGE
_spec.loader.exec_module(PURGE)
is_flee_message, purge_zone, split_by_age = PURGE.is_flee_message, PURGE.purge_zone, PURGE.split_by_age

BOT = "1"
ZONE = 7
NOW = datetime.now(UTC)


TEXT = "Personne ne s'est présenté pour combattre. Le monstre a disparu dans la nature avec son butin."


def _message(message_id, *, days=30, author=BOT, title="🌫️ Le Slime vert s'est échappé", text=TEXT, **extra):
    return {"id": str(message_id), "author": {"id": author}, "content": "", "components": [], "attachments": [],
            "timestamp": (NOW - timedelta(days=days)).isoformat(),
            "embeds": [{"title": title, "description": text}], **extra}


class FakeApi:
    throttled = 0

    def __init__(self, messages, *, bulk_status=204, delete_status=204):
        self.messages = sorted(messages, key=lambda m: -int(m["id"]))
        self.bulk_status, self.delete_status = bulk_status, delete_status
        self.bulks, self.deletes = [], []

    async def history(self, channel_id, before):
        rest = [m for m in self.messages if before is None or int(m["id"]) < int(before)]
        return rest[:100]

    async def bulk_delete(self, channel_id, ids):
        self.bulks.append(ids)
        if self.bulk_status == 204:
            self.messages = [m for m in self.messages if m["id"] not in ids]
        return self.bulk_status

    async def delete(self, channel_id, message_id):
        self.deletes.append(message_id)
        if self.delete_status == 204:
            self.messages = [m for m in self.messages if m["id"] != message_id]
        return self.delete_status


def _run(api, **kwargs):
    kwargs.setdefault("confirm", True)
    return asyncio.run(purge_zone(api, "Zone", ZONE, BOT, pause=0, **kwargs))


def test_seul_un_message_de_fuite_du_bot_est_reconnu():
    assert is_flee_message(_message(1), BOT)
    assert not is_flee_message(_message(1, author="2"), BOT)
    assert not is_flee_message(_message(1, pinned=True), BOT)
    assert not is_flee_message(_message(1, content="Regardez ça"), BOT)
    assert not is_flee_message(_message(1, components=[{"type": 1}]), BOT)
    assert not is_flee_message(_message(1, attachments=[{"id": "9"}]), BOT)
    assert not is_flee_message(_message(1, text="Le groupe a tenu 12 actions."), BOT)
    assert not is_flee_message(_message(1, title="🏆 Victoire contre Slime vert"), BOT)
    assert not is_flee_message(_message(1, title="🌫️ Le Slime vert rôde"), BOT)
    assert not is_flee_message({**_message(1), "embeds": []}, BOT)
    assert not is_flee_message({**_message(1), "embeds": [_message(1)["embeds"][0], {}]}, BOT)


def test_un_monstre_mort_laisse_par_un_redemarrage_n_est_pas_une_fuite():
    leftover = _message(1, title="", text="⏳ Sans combattant, le monstre s'enfuit <t:1793747027:R>.",
                        components=[{"type": 1}])
    assert not is_flee_message(leftover, BOT)


def test_les_messages_recents_partent_par_lot_les_vieux_un_par_un():
    recent, old = split_by_age([_message(1, days=1), _message(2, days=13), _message(3, days=15)], NOW)
    assert recent == ["1", "2"] and old == ["3"]
    # Le seuil garde une marge : à 14 jours moins 2 h, Discord pourrait déjà refuser le lot.
    assert split_by_age([_message(1, days=1), _message(2, days=13.95)], NOW) == ([], ["1", "2"])


def test_un_seul_message_recent_ne_fait_pas_un_lot():
    assert split_by_age([_message(1, days=1)], NOW) == ([], ["1"])


def test_sans_confirm_rien_n_est_supprime():
    api = FakeApi([_message(i) for i in range(1, 6)])
    report = _run(api, confirm=False)
    assert (report.seen, report.found, report.removed) == (5, 5, 0)
    assert not api.bulks and not api.deletes


def test_les_combats_restent_et_les_fuites_partent():
    fights = [_message(i, title="🏆 Victoire contre Slime") for i in range(1, 4)]
    players = [_message(10 + i, author="2", title="🌫️ Le faux s'est échappé") for i in range(3)]
    flees = [_message(20 + i, days=1) for i in range(3)] + [_message(30 + i, days=20) for i in range(3)]
    api = FakeApi(fights + players + flees)
    report = _run(api)
    assert report.removed == 6
    assert sorted(m["id"] for m in api.messages) == sorted(m["id"] for m in fights + players)
    assert len(api.bulks) == 1 and len(api.deletes) == 3


def test_tout_l_historique_est_parcouru_page_par_page():
    api = FakeApi([_message(i) for i in range(1, 251)])
    report = _run(api)
    assert (report.seen, report.removed) == (250, 250) and not api.messages


def test_la_limite_arrete_la_zone():
    api = FakeApi([_message(i) for i in range(1, 11)])
    report = _run(api, limit=3)
    assert report.removed == 3 and len(api.messages) == 7


def test_un_lot_refuse_repasse_un_par_un():
    api = FakeApi([_message(1, days=1), _message(2, days=1)], bulk_status=400)
    report = _run(api)
    assert report.removed == 2 and len(api.deletes) == 2


def test_une_suppression_refusee_arrete_la_zone():
    api = FakeApi([_message(i) for i in range(1, 6)], delete_status=403)
    report = _run(api)
    assert report.removed == 0 and len(api.deletes) == 1 and "403" in report.error
