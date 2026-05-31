"""Tests sécuritaires du coeur d'authentification de la webapp admin.

Couvre les invariants critiques exposés par `webapp/admin/auth.py` :
    - une route protégée (Depends(require_admin)) sans cookie → redirige (307) vers /admin/login
    - un cookie correctement signé mais portant un discord_id non admin → 403
    - un cookie signé avec un secret DIFFÉRENT (forgé) → traité comme non connecté → 307
    - le callback OAuth refuse un state qui ne match pas le cookie state → 400

NOTE setup : les variables d'env DOIVENT être posées AVANT l'import de
`webapp.main`, car `app.infrastructure.config.settings.settings` est instancié
au module load. On les pose donc ici (top du module) avant tout import lourd.
"""

from __future__ import annotations

import os


# --- env setup AVANT toute import de webapp/app -----------------------------
# admin_session_secret : doit être != "dev-secret-change-in-prod" sinon
# le startup event de webapp.main lève RuntimeError au premier request.
os.environ.setdefault(
    "ADMIN_SESSION_SECRET",
    "test-secret-for-pytest-only-32chars-min-aaaaa",
)
os.environ.setdefault("DISCORD_TOKEN", "x")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("BETA_CHANNEL_ID", "1")
os.environ.setdefault("ENCOUNTER_CHANNEL_ID", "1")
# Pas d'admin déclaré → admin_ids == [] → forge d'un cookie quelconque = non admin
os.environ.setdefault("ADMIN_DISCORD_IDS", "")


# --- imports différés (après env setup) -------------------------------------
import pytest
from fastapi.testclient import TestClient
from itsdangerous import URLSafeSerializer


@pytest.fixture(scope="module")
def client() -> TestClient:
    """TestClient FastAPI partagé pour tout le module.

    L'instanciation déclenche les startup events (dont
    settings.assert_safe_admin_secret), ce qui valide implicitement que
    notre setup d'env est bien pris en compte.
    """
    # Import retardé pour garantir l'ordre env-vars → settings → app.
    from webapp.main import app

    with TestClient(app) as c:
        yield c


# ----------------------------------------------------------------------------
# 1. Anonyme sur route admin protégée → 307 vers /admin/login
# ----------------------------------------------------------------------------
def test_admin_route_redirects_to_login_when_anonymous(client: TestClient) -> None:
    """Sans cookie de session, /admin/items doit renvoyer un 307 vers /admin/login.

    require_admin lève HTTPException(307, headers={"Location": "/admin/login"}).
    On désactive follow_redirects pour observer la réponse brute.
    """
    response = client.get("/admin/items", follow_redirects=False)

    assert response.status_code == 307, (
        f"Attendu 307, reçu {response.status_code} (body={response.text!r})"
    )
    assert "/admin/login" in response.headers.get("location", "")


# ----------------------------------------------------------------------------
# 2. Cookie valide mais discord_id non admin → 403
# ----------------------------------------------------------------------------
def test_admin_route_403_for_non_admin(client: TestClient) -> None:
    """Cookie signé avec le bon secret, mais discord_id absent de settings.admin_ids."""
    from webapp.admin.auth import _serializer

    payload = {
        "discord_id": 999_999_999,  # absent de ADMIN_DISCORD_IDS (vide ici)
        "username": "intrus",
        "display_name": "Intrus",
    }
    token = _serializer().dumps(payload)
    client.cookies.set("sakura_admin_session", token)

    try:
        response = client.get("/admin/items", follow_redirects=False)
    finally:
        client.cookies.delete("sakura_admin_session")

    assert response.status_code == 403, (
        f"Attendu 403 (non admin), reçu {response.status_code} "
        f"(body={response.text!r})"
    )


# ----------------------------------------------------------------------------
# 3. Cookie signé avec un MAUVAIS secret → BadSignature → non connecté → 307
# ----------------------------------------------------------------------------
def test_admin_route_403_for_forged_cookie_with_wrong_secret(
    client: TestClient,
) -> None:
    """Cookie forgé avec un secret différent de admin_session_secret.

    Le serializer du serveur lève BadSignature → current_user retourne None
    → require_admin redirige vers /admin/login (307).

    C'est l'invariant fondamental : sans connaître admin_session_secret, on ne
    peut pas se faire passer pour quiconque (même pas un non-admin).
    """
    bad_serializer = URLSafeSerializer(
        "totally-different-secret-not-the-real-one",
        salt="sakura-admin-v1",
    )
    forged_token = bad_serializer.dumps(
        {"discord_id": 1, "username": "hacker", "display_name": "Hacker"}
    )
    client.cookies.set("sakura_admin_session", forged_token)

    try:
        response = client.get("/admin/items", follow_redirects=False)
    finally:
        client.cookies.delete("sakura_admin_session")

    # current_user() retourne None → require_admin redirige (307)
    assert response.status_code == 307, (
        f"Cookie forgé devrait être traité comme anonyme (307), "
        f"reçu {response.status_code} (body={response.text!r})"
    )
    assert "/admin/login" in response.headers.get("location", "")


# ----------------------------------------------------------------------------
# 4. Callback OAuth refuse un state qui ne match pas le cookie state
# ----------------------------------------------------------------------------
def test_oauth_callback_rejects_state_mismatch(client: TestClient) -> None:
    """GET /admin/auth/callback?code=x&state=mismatch sans state stocké
    → l'auth_router lève HTTPException(400, 'OAuth state invalide').

    Anti-CSRF de base : impossible de finir un flow OAuth si on n'a pas
    initialement obtenu (et conservé en cookie) le state attendu.
    """
    # On s'assure de ne pas avoir de cookie d'état préalable.
    client.cookies.delete("sakura_oauth_state")

    response = client.get(
        "/admin/auth/callback",
        params={"code": "fake-code", "state": "mismatch-state"},
        follow_redirects=False,
    )

    assert response.status_code == 400, (
        f"Attendu 400 (state invalide), reçu {response.status_code} "
        f"(body={response.text!r})"
    )
    # Le message d'erreur ne doit pas exposer d'info sensible mais doit pointer
    # le motif "state".
    assert "state" in response.text.lower()


# ----------------------------------------------------------------------------
# 5. Callback OAuth refuse aussi quand code/state sont totalement absents
# ----------------------------------------------------------------------------
def test_oauth_callback_rejects_missing_code(client: TestClient) -> None:
    """GET /admin/auth/callback sans code/state → 400.

    Test bonus : verrouille l'autre branche de garde de oauth_callback,
    qui refuse code=None ou state=None.
    """
    response = client.get(
        "/admin/auth/callback",
        follow_redirects=False,
    )

    assert response.status_code == 400, (
        f"Attendu 400 (paramètres manquants), reçu {response.status_code}"
    )
