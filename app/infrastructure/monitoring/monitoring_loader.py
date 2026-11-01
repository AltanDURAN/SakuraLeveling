"""Réglages de la surveillance (`monitoring.json`) : seuils des alertes,
règles activées, notification des admins.

Cache invalidé par la date de modification : un réglage fait depuis le site
vaut tout de suite, bot compris, sans redémarrage.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.domain.services.monitoring.alerts import (
    RULES,
    SERIOUS,
    SEVERITY_ORDER,
    THRESHOLD_SPECS,
    default_thresholds,
)

CONTENT_PATH = Path(__file__).resolve().parents[1] / "content" / "monitoring.json"


@dataclass(frozen=True)
class MonitoringSettings:
    thresholds: dict[str, float] = field(default_factory=default_thresholds)
    rules: dict[str, bool] = field(default_factory=lambda: {r.code: True for r in RULES})
    #: Message privé aux admins pour une NOUVELLE alerte de cette gravité ou plus.
    notify: bool = True
    notify_min_severity: str = SERIOUS

    def notifies(self, severity: str) -> bool:
        if not self.notify or severity not in SEVERITY_ORDER:
            return False
        return SEVERITY_ORDER.index(severity) <= SEVERITY_ORDER.index(self.notify_min_severity)


def parse(data: dict) -> MonitoringSettings:
    thresholds = default_thresholds()
    for key, value in (data.get("thresholds") or {}).items():
        if key in THRESHOLD_SPECS:
            try:
                thresholds[key] = float(value)
            except (TypeError, ValueError):
                pass
    rules = {r.code: bool((data.get("rules") or {}).get(r.code, True)) for r in RULES}
    notify = data.get("notify") or {}
    severity = notify.get("min_severity", SERIOUS)
    return MonitoringSettings(thresholds=thresholds, rules=rules, notify=bool(notify.get("enabled", True)),
                              notify_min_severity=severity if severity in SEVERITY_ORDER else SERIOUS)


def to_json(settings: MonitoringSettings) -> dict:
    return {
        "thresholds": {k: (int(v) if float(v).is_integer() else v) for k, v in settings.thresholds.items()},
        "rules": dict(settings.rules),
        "notify": {"enabled": settings.notify, "min_severity": settings.notify_min_severity},
    }


_cache: MonitoringSettings | None = None
_cache_mtime: float | None = None


def get_settings() -> MonitoringSettings:
    global _cache, _cache_mtime
    try:
        mtime = CONTENT_PATH.stat().st_mtime
    except OSError:
        mtime = None
    if _cache is None or mtime != _cache_mtime:
        try:
            data = json.loads(CONTENT_PATH.read_text(encoding="utf-8")) if mtime is not None else {}
        except (OSError, ValueError):
            data = {}
        _cache, _cache_mtime = parse(data), mtime
    return _cache


def clear_cache() -> None:
    global _cache, _cache_mtime
    _cache, _cache_mtime = None, None
