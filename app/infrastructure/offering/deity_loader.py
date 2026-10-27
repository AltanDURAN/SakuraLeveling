"""Divinités de l'offrande commune (`deities.json`). Cache module-level :
une modification du fichier ⇒ redémarrage du bot."""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.services.offering_service import Deity

_CONTENT = Path(__file__).resolve().parents[1] / "content" / "deities.json"
_cache: list[Deity] | None = None


def list_deities() -> list[Deity]:
    global _cache
    if _cache is None:
        data = json.loads(_CONTENT.read_text(encoding="utf-8")) if _CONTENT.exists() else {}
        _cache = [Deity(code=d["code"], name=d["name"], title=d.get("title", ""), emoji=d.get("emoji", "✨"),
                        effect=d["effect"], value=float(d.get("value", 0)), blessing=d.get("blessing", ""))
                  for d in data.get("deities", [])]
    return _cache


def get_deity(code: str | None) -> Deity | None:
    return next((d for d in list_deities() if d.code == code), None)


def clear_cache() -> None:
    global _cache
    _cache = None
