"""Chaque formulaire de l'admin (POST / PUT / DELETE), envoyé vide puis avec
des valeurs absurdes, ne fait jamais d'erreur serveur (audit du 28/11/2026).

Une erreur 500 laisse l'auteur devant « Erreur interne » sans savoir quoi
corriger. Sur une copie du contenu ; aucun fichier du dépôt n'est supprimé
(les suppressions sous assets/ sont neutralisées) et rien n'est poussé.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

import pytest

from tests.webapp.test_admin_content_crud import _same_origin, content  # noqa: F401  (fixtures)
from tests.webapp.test_admin_pages_smoke import SUBS, client  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[2]

#: Valeurs absurdes pour chaque champ d'un formulaire.
GARBAGE = {"name": "", "code": "../../etc", "price": "-5", "amount": "abc", "quantity": "1e99",
           "level": "-1", "value": "NaN", "json": "{pas du json", "data": "[", "payload": "{",
           "rarity": "inconnue", "element": "plasma", "effect": "rien", "channel_id": "pas-un-id"}


@pytest.fixture
def no_asset_deletion(monkeypatch):
    """Les routes de suppression ne touchent pas aux vraies images."""
    assets = str(ROOT / "assets")
    real_unlink, real_remove, real_rmtree = Path.unlink, os.remove, shutil.rmtree

    def guard(path):
        return str(Path(path).resolve()).startswith(assets)

    monkeypatch.setattr(Path, "unlink", lambda self, missing_ok=False: None if guard(self) else real_unlink(self, missing_ok=missing_ok))
    monkeypatch.setattr(os, "remove", lambda p, *a, **k: None if guard(p) else real_remove(p, *a, **k))
    monkeypatch.setattr(shutil, "rmtree", lambda p, *a, **k: None if guard(p) else real_rmtree(p, *a, **k))
    monkeypatch.setattr("webapp.admin.git_sync.push_content", lambda *a, **k: False, raising=False)


def _routes(client):
    for route in client.app_routes:
        path = getattr(route, "path", "")
        for method in sorted((getattr(route, "methods", None) or set()) - {"GET", "HEAD", "OPTIONS"}):
            if path.startswith("/admin") and not path.startswith(("/admin/auth", "/admin/logout")):
                yield method, path


def _url(path, client):
    def sub(match):
        key = match.group(1).split(":")[0]
        if key in ("discord_id", "player_id"):
            return str(SUBS["discord_id"])
        return str(SUBS.get(key, "gobelin"))
    return re.sub(r"\{([^}]+)\}", sub, path)


def test_aucun_formulaire_admin_ne_fait_d_erreur_serveur(client, content, no_asset_deletion):
    crashes, checked = [], 0
    for method, path in _routes(client):
        url = _url(path, client)
        for body in ({}, GARBAGE):
            response = client.request(method, url, data=body, follow_redirects=False)
            checked += 1
            if response.status_code >= 500:
                crashes.append(f"{method} {url} {'vide' if not body else 'absurde'} → {response.status_code}")
    assert checked > 150, checked
    assert crashes == [], "\n".join(crashes)
