"""Rythme du jeu, réglable depuis l'admin (27/10/2026, demande de l'auteur) :
les apparitions de monstres dans les zones et le rendez-vous du raid.

Règles pures ; les valeurs vivent dans `pacing.json` (`pacing_loader`), relu
par le bot sans redémarrage. Les valeurs par défaut sont celles d'avant :
1 min entre deux combats, 5 min pour rejoindre, 10 % de meutes (60 % de 2,
40 % de 3), boss le lundi à 13 h, assaut quotidien à 21 h, inscriptions
fermées 10 min avant.

  • ZONES : après un combat, le monstre suivant arrive au bout d'un délai
    tiré entre `respawn_min_minutes` et `respawn_max_minutes` (un rythme
    moins prévisible quand ils diffèrent) ; après une FUITE (personne n'est
    venu), `flee_respawn_minutes` — plus long, il évite d'inonder un salon
    vide. Pendant les HEURES CALMES (heure de Paris), aucune apparition (un
    cor de chasse ou un spawn forcé par l'admin passe quand même). Une zone
    peut être mise en
    PAUSE ou avoir son propre délai (`ZoneOverride`). Pause et heures calmes
    sont vérifiées à chaque apparition : un réglage vaut tout de suite.
  • RAID : le boss de la semaine arrive le `spawn_weekday` à `spawn_hour`
    (Paris), l'assaut part chaque jour à `fight_hour`:`fight_minute`, les
    inscriptions ferment `registration_close_minutes` avant.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.domain.services.lunar_service import DEFAULT_RULES as DEFAULT_LUNAR_RULES
from app.domain.services.lunar_service import validate as validate_lunar

PARIS = ZoneInfo("Europe/Paris")
WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
#: Un assaut manqué (bot redémarré pile à l'heure) est rattrapé dans ce délai.
FIGHT_CATCH_UP = timedelta(minutes=15)


@dataclass(frozen=True)
class ZonePacing:
    respawn_min_minutes: float = 1.0
    respawn_max_minutes: float = 1.0
    flee_respawn_minutes: float = 1.0
    join_window_minutes: float = 5.0
    quiet_start_hour: int = 0          # heure de Paris ; début = fin ⇒ pas d'heures calmes
    quiet_end_hour: int = 0
    pack_chance_pct: float = 10.0
    pack_of_three_pct: float = 40.0    # part des meutes de 3 (le reste : 2)


@dataclass(frozen=True)
class ZoneOverride:
    """Réglage propre à une zone : en pause, ou un autre délai."""
    paused: bool = False
    respawn_min_minutes: float | None = None
    respawn_max_minutes: float | None = None


@dataclass(frozen=True)
class RaidPacing:
    spawn_weekday: int = 0             # 0 = lundi
    spawn_hour: int = 13               # heure de Paris
    fight_hour: int = 21
    fight_minute: int = 0
    registration_close_minutes: int = 10


@dataclass(frozen=True)
class Pacing:
    zones: ZonePacing = field(default_factory=ZonePacing)
    overrides: dict[int, ZoneOverride] = field(default_factory=dict)
    raid: RaidPacing = field(default_factory=RaidPacing)
    #: Événements lunaires (cf. `lunar_service`) : effet de chacun sur les zones.
    lunar: dict = field(default_factory=lambda: dict(DEFAULT_LUNAR_RULES))

    def override(self, channel_id: int) -> ZoneOverride:
        return self.overrides.get(int(channel_id), ZoneOverride())


DEFAULT = Pacing()


# ------------------------------------------------------------------ zones
def respawn_range(zones: ZonePacing, override: ZoneOverride | None = None) -> tuple[float, float]:
    """(min, max) en minutes entre deux combats dans cette zone."""
    low = zones.respawn_min_minutes
    high = zones.respawn_max_minutes
    if override is not None and override.respawn_min_minutes is not None:
        low = override.respawn_min_minutes
        high = override.respawn_max_minutes if override.respawn_max_minutes is not None else low
    return low, max(low, high)


def in_quiet_hours(zones: ZonePacing, when: datetime) -> bool:
    start, end = zones.quiet_start_hour, zones.quiet_end_hour
    if start == end:
        return False
    hour = when.astimezone(PARIS).hour
    return start <= hour < end if start < end else (hour >= start or hour < end)


def next_spawn_at(zones: ZonePacing, override: ZoneOverride | None, now: datetime, *,
                  fled: bool = False, rate: float = 1.0, rng: random.Random | None = None) -> datetime:
    """Date du prochain monstre : après le délai de fuite, ou un délai tiré
    dans la plage de la zone, divisé par `rate` (lune de sang, éclipse). (Les
    heures calmes et la pause sont vérifiées au moment de l'apparition : un
    changement dans l'admin vaut tout de suite.)"""
    if fled:
        minutes = zones.flee_respawn_minutes
    else:
        low, high = respawn_range(zones, override)
        minutes = (rng or random).uniform(low, high)
    return now + timedelta(minutes=minutes / max(1.0, rate))


def pack_size_weights(zones: ZonePacing) -> dict[int, float]:
    three = max(0.0, min(100.0, zones.pack_of_three_pct))
    return {2: 100.0 - three, 3: three}


def cycle_minutes(zones: ZonePacing, fight_minutes: float = 0.5) -> float:
    """Durée moyenne d'un cycle d'une zone quand personne ne lance le combat
    avant la fin de l'attente : attente + combat + délai moyen."""
    low, high = respawn_range(zones)
    return zones.join_window_minutes + fight_minutes + (low + high) / 2


# ------------------------------------------------------------------- raid
def fight_time(raid: RaidPacing) -> time:
    return time(raid.fight_hour, raid.fight_minute)


def registration_close_time(raid: RaidPacing) -> time:
    total = raid.fight_hour * 60 + raid.fight_minute - raid.registration_close_minutes
    total = max(0, total)
    return time(total // 60, total % 60)


def time_label(value: time) -> str:
    """21 h → « 21h », 20 h 50 → « 20h50 »."""
    return f"{value.hour}h{value.minute:02d}" if value.minute else f"{value.hour}h"


def fight_label(raid: RaidPacing) -> str:
    return time_label(fight_time(raid))


def close_label(raid: RaidPacing) -> str:
    return time_label(registration_close_time(raid))


def registration_closed(raid: RaidPacing, now: datetime) -> bool:
    """Inscriptions fermées de la fermeture jusqu'à minuit (heure de Paris) :
    le combat du jour est parti, on s'inscrit pour celui de demain après
    minuit (la limite d'un combat par jour se remet à zéro à minuit)."""
    return now.astimezone(PARIS).time().replace(tzinfo=None) >= registration_close_time(raid)


def fight_due(raid: RaidPacing, now: datetime, last_fight_day) -> bool:
    """L'assaut du jour est-il à lancer ? (à l'heure, ou dans le délai de
    rattrapage, une seule fois par jour)."""
    local = now.astimezone(PARIS)
    if last_fight_day == local.date():
        return False
    start = datetime.combine(local.date(), fight_time(raid), tzinfo=PARIS)
    return start <= local < start + FIGHT_CATCH_UP


def next_fight_at(raid: RaidPacing, now: datetime) -> datetime:
    local = now.astimezone(PARIS)
    target = datetime.combine(local.date(), fight_time(raid), tzinfo=PARIS)
    return target if local < target else target + timedelta(days=1)


# -------------------------------------------------------------- validation
def validate(pacing: Pacing) -> list[str]:
    """Messages d'erreur (vide = valide)."""
    z, r = pacing.zones, pacing.raid
    errors = []
    if z.respawn_min_minutes < 0.5:
        errors.append("Le délai entre deux combats est d'au moins 30 secondes (0,5 min).")
    if z.respawn_max_minutes < z.respawn_min_minutes:
        errors.append("Le délai maximum ne peut pas être inférieur au minimum.")
    if z.respawn_max_minutes > 24 * 60:
        errors.append("Le délai entre deux combats ne dépasse pas 24 h.")
    if not 0.5 <= z.flee_respawn_minutes <= 24 * 60:
        errors.append("Le délai après une fuite va de 30 secondes à 24 h.")
    if not 1 <= z.join_window_minutes <= 30:
        errors.append("Le temps pour rejoindre va de 1 à 30 minutes.")
    if not (0 <= z.quiet_start_hour <= 23 and 0 <= z.quiet_end_hour <= 23):
        errors.append("Les heures calmes vont de 0 à 23 h.")
    if not 0 <= z.pack_chance_pct <= 100 or not 0 <= z.pack_of_three_pct <= 100:
        errors.append("Les pourcentages de meutes vont de 0 à 100.")
    for channel_id, o in pacing.overrides.items():
        if o.respawn_min_minutes is not None and o.respawn_min_minutes < 0.5:
            errors.append(f"Zone {channel_id} : délai d'au moins 30 secondes.")
        if (o.respawn_min_minutes is not None and o.respawn_max_minutes is not None
                and o.respawn_max_minutes < o.respawn_min_minutes):
            errors.append(f"Zone {channel_id} : le maximum ne peut pas être inférieur au minimum.")
    if not 0 <= r.spawn_weekday <= 6:
        errors.append("Jour d'apparition du boss inconnu.")
    if not (0 <= r.spawn_hour <= 23 and 0 <= r.fight_hour <= 23 and 0 <= r.fight_minute <= 59):
        errors.append("Heure invalide pour le raid.")
    if not 0 <= r.registration_close_minutes <= 120:
        errors.append("Les inscriptions ferment entre 0 et 120 minutes avant l'assaut.")
    elif r.fight_hour * 60 + r.fight_minute < r.registration_close_minutes:
        errors.append("La fermeture des inscriptions doit tomber le même jour que l'assaut.")
    return errors + validate_lunar(pacing.lunar)
