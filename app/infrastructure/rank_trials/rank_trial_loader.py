"""Loader des épreuves de rang — cache module-level, comme les autres."""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.services.rank_trial_service import GuardianStats, RankTrial

CONTENT_PATH = (
    Path(__file__).resolve().parents[2]
    / "infrastructure"
    / "content"
    / "rank_trials.json"
)

_cache: dict | None = None


def _raw() -> dict:
    global _cache
    if _cache is None:
        with CONTENT_PATH.open("r", encoding="utf-8") as fh:
            _cache = json.load(fh)
    return _cache


def clear_cache() -> None:
    global _cache
    _cache = None


def list_trials() -> list[RankTrial]:
    out: list[RankTrial] = []
    for entry in _raw().get("trials", []):
        g = entry.get("guardian") or {}
        out.append(
            RankTrial(
                rank=str(entry.get("rank", "")),
                required_power=int(entry.get("required_power", 0)),
                guardian=GuardianStats(
                    name=str(g.get("name", "Gardien")),
                    lore=str(g.get("lore", "")),
                ),
                level=int(entry.get("level", 1)),
                thresholds={str(k): int(v) for k, v in (entry.get("thresholds") or {}).items()},
            )
        )
    return out


def retry_cooldown_hours() -> int:
    return int(_raw().get("retry_cooldown_hours", 6))
