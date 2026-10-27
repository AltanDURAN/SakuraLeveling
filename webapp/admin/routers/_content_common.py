"""Outils partagés des pages admin du contenu JSON (titres, quêtes, world
boss) : lecture, analyse des champs de formulaire, filtres, rendu des
listes, suppression. Issu du découpage de `content_router.py` (26/10/2026).

⚠️ Les loaders de contenu du bot cachent le JSON au démarrage : un changement
demande un redémarrage du bot. Le site, lui, relit à chaque requête.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from webapp.admin import git_sync
from webapp.admin._shared import get_templates
from webapp.admin.auth import AdminUser
from webapp.admin.json_writer import delete_in_list_by_key

CONTENT_DIR = Path(__file__).resolve().parents[3] / "app" / "infrastructure" / "content"


def _load_json(filename: str):
    path = CONTENT_DIR / filename
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _parse_int(raw, default=0):
    if raw is None:
        return default
    raw = str(raw).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _parse_kv_pairs(raw: str) -> dict[str, int]:
    """Parse 'max_hp=20, attack=3' → {'max_hp': 20, 'attack': 3}."""
    out: dict[str, int] = {}
    if not raw:
        return out
    for chunk in raw.replace(";", ",").split(","):
        if "=" not in chunk:
            continue
        k, v = chunk.split("=", 1)
        k = k.strip()
        try:
            out[k] = int(v.strip())
        except ValueError:
            try:
                out[k] = float(v.strip())
            except ValueError:
                continue
    return out


def _parse_reward_items(raw: str) -> list[list]:
    """Parse 'potion_soin_i:1, gold_coin:5' → [['potion_soin_i', 1], ['gold_coin', 5]]."""
    out = []
    if not raw:
        return out
    for chunk in raw.replace(";", ",").split(","):
        if ":" not in chunk:
            continue
        code, qty = chunk.split(":", 1)
        try:
            out.append([code.strip(), int(qty.strip())])
        except ValueError:
            continue
    return out


def _filter_rows(rows: list[dict], q: str | None, extra_filters: dict | None = None) -> list[dict]:
    """Filtre client : q matche en sous-chaîne dans toutes les valeurs string ;
    extra_filters[k] doit matcher exactement row[k] si défini."""
    out = rows
    if q:
        ql = q.lower()
        out = [
            r for r in out
            if any(ql in str(v).lower() for v in r.values() if v is not None)
        ]
    for k, v in (extra_filters or {}).items():
        if v:
            out = [r for r in out if str(r.get(k, "")) == str(v)]
    return out


def _render(request: Request, user: AdminUser, **ctx) -> HTMLResponse:
    return get_templates().TemplateResponse(
        request, "admin/_generic_list.html",
        context={"user": user, **ctx},
    )


def _fmt_kv_pairs(d: dict | None) -> str:
    """{max_hp: 20, attack: 3} → 'max_hp=20, attack=3'"""
    if not d:
        return ""
    return ", ".join(f"{k}={v}" for k, v in d.items())


def _fmt_reward_items(lst: list | None) -> str:
    """[['potion_soin_i', 1]] → 'potion_soin_i:1'"""
    if not lst:
        return ""
    return ", ".join(f"{c}:{q}" for c, q in lst)


def _fmt_title_effects(effects: list | None) -> str:
    """[{type, target?, value}] → 'type:target:value, type::value'"""
    out = []
    for e in (effects or []):
        type_ = e.get("type", "")
        target = e.get("target") or ""
        val = e.get("value", "")
        out.append(f"{type_}:{target}:{val}")
    return ", ".join(out)


def _delete_from_list(filename: str, code: str, label: str, redirect: str):
    try:
        delete_in_list_by_key(filename, code)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} `{code}` introuvable.")
    git_sync.push_content([f"app/infrastructure/content/{filename}"],
                          f"admin: {label} {code} supprimé(e)")
    return RedirectResponse(redirect, status_code=303)
