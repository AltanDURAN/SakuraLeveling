"""Le ciel de Paris, calculé (30/10/2026, événements lunaires de l'auteur).

Aucune dépendance : les formules de Jean Meeus (« Astronomical Algorithms »)
en précision réduite — Soleil (ch. 25, ~0,01°), Lune (ch. 47, les 60 plus
gros termes, ~0,01-0,02°), parallaxe topocentrique (ch. 40) — suffisent pour
dater une pleine lune à la minute, un lever ou un coucher de soleil à une
minute près, et dire si une éclipse est visible DE PARIS :

  • éclipse de LUNE : la Lune entre dans l'ombre de la Terre (rayon d'ombre
    de Danjon, ×1,02) pendant qu'elle est au-dessus de l'horizon de Paris ;
  • éclipse de SOLEIL : vus de Paris (parallaxe comprise), les disques du
    Soleil et de la Lune se chevauchent pendant que le Soleil est levé.

Vérifié contre les éphémérides publiées (cf. `tests/domain/test_astronomy.py`).
Temps en UTC ; ΔT (TT − UT) pris à 69 s.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache

PARIS_LAT = 48.8566
PARIS_LON = 2.3522           # est
DELTA_T_SECONDS = 69.0
SYNODIC_MONTH = 29.530588853
#: Hauteur du centre du Soleil au lever / coucher (réfraction + demi-disque).
SUN_HORIZON = -0.833
#: Nouvelle lune de référence (k = 0 de Meeus), en jours juliens.
_K0_JDE = 2451550.09766

_RAD = math.pi / 180


def _sin(deg: float) -> float:
    return math.sin(deg * _RAD)


def _cos(deg: float) -> float:
    return math.cos(deg * _RAD)


def julian_day(when: datetime) -> float:
    when = when.astimezone(UTC)
    return when.timestamp() / 86400.0 + 2440587.5


def from_julian_day(jd: float) -> datetime:
    return datetime.fromtimestamp((jd - 2440587.5) * 86400.0, tz=UTC)


def _centuries(jd_ut: float) -> float:
    return (jd_ut + DELTA_T_SECONDS / 86400.0 - 2451545.0) / 36525.0


# ------------------------------------------------------------------ Soleil
def sun_position(jd: float) -> tuple[float, float, float]:
    """(longitude apparente °, latitude °, distance en UA)."""
    t = _centuries(jd)
    l0 = 280.46646 + 36000.76983 * t + 0.0003032 * t * t
    m = 357.52911 + 35999.05029 * t - 0.0001537 * t * t
    e = 0.016708634 - 0.000042037 * t
    c = ((1.914602 - 0.004817 * t - 0.000014 * t * t) * _sin(m)
         + (0.019993 - 0.000101 * t) * _sin(2 * m) + 0.000289 * _sin(3 * m))
    nu = m + c
    r = 1.000001018 * (1 - e * e) / (1 + e * _cos(nu))
    omega = 125.04 - 1934.136 * t
    lam = l0 + c - 0.00569 - 0.00478 * _sin(omega)
    return lam % 360, 0.0, r


# -------------------------------------------------------------------- Lune
# (D, M, M', F, Σl en 1e-6°, Σr en 1e-3 km) — Meeus, table 47.A.
_LR = (
    (0, 0, 1, 0, 6288774, -20905355), (2, 0, -1, 0, 1274027, -3699111),
    (2, 0, 0, 0, 658314, -2955968), (0, 0, 2, 0, 213618, -569925),
    (0, 1, 0, 0, -185116, 48888), (0, 0, 0, 2, -114332, -3149),
    (2, 0, -2, 0, 58793, 246158), (2, -1, -1, 0, 57066, -152138),
    (2, 0, 1, 0, 53322, -170733), (2, -1, 0, 0, 45758, -204586),
    (0, 1, -1, 0, -40923, -129620), (1, 0, 0, 0, -34720, 108743),
    (0, 1, 1, 0, -30383, 104755), (2, 0, 0, -2, 15327, 10321),
    (0, 0, 1, 2, -12528, 0), (0, 0, 1, -2, 10980, 79661),
    (4, 0, -1, 0, 10675, -34782), (0, 0, 3, 0, 10034, -23210),
    (4, 0, -2, 0, 8548, -21636), (2, 1, -1, 0, -7888, 24208),
    (2, 1, 0, 0, -6766, 30824), (1, 0, -1, 0, -5163, -8379),
    (1, 1, 0, 0, 4987, -16675), (2, -1, 1, 0, 4036, -12831),
    (2, 0, 2, 0, 3994, -10445), (4, 0, 0, 0, 3861, -11650),
    (2, 0, -3, 0, 3665, 14403), (0, 1, -2, 0, -2689, -7003),
    (2, 0, -1, 2, -2602, 0), (2, -1, -2, 0, 2390, 10056),
    (1, 0, 1, 0, -2348, 6322), (2, -2, 0, 0, 2236, -9884),
    (0, 1, 2, 0, -2120, 5751), (0, 2, 0, 0, -2069, 0),
    (2, -2, -1, 0, 2048, -4950), (2, 0, 1, -2, -1773, 4130),
    (2, 0, 0, 2, -1595, 0), (4, -1, -1, 0, 1215, -3958),
    (0, 0, 2, 2, -1110, 0), (3, 0, -1, 0, -892, 3258),
    (2, 1, 1, 0, -810, 2616), (4, -1, -2, 0, 759, -1897),
    (0, 2, -1, 0, -713, -2117), (2, 2, -1, 0, -700, 2354),
    (2, 1, -2, 0, 691, 0), (2, -1, 0, -2, 596, 0),
    (4, 0, 1, 0, 549, -1423), (0, 0, 4, 0, 537, -1117),
    (4, -1, 0, 0, 520, -1571), (1, 0, -2, 0, -487, -1739),
    (2, 1, 0, -2, -399, 0), (0, 0, 2, -2, -381, -4421),
    (1, 1, 1, 0, 351, 0), (3, 0, -2, 0, -340, 0),
    (4, 0, -3, 0, 330, 0), (2, -1, 2, 0, 327, 0),
    (0, 2, 1, 0, -323, 1165), (1, 1, -1, 0, 299, 0),
    (2, 0, 3, 0, 294, 0), (2, 0, -1, -2, 0, 8752),
)
# (D, M, M', F, Σb en 1e-6°) — Meeus, table 47.B.
_B = (
    (0, 0, 0, 1, 5128122), (0, 0, 1, 1, 280602), (0, 0, 1, -1, 277693),
    (2, 0, 0, -1, 173237), (2, 0, -1, 1, 55413), (2, 0, -1, -1, 46271),
    (2, 0, 0, 1, 32573), (0, 0, 2, 1, 17198), (2, 0, 1, -1, 9266),
    (0, 0, 2, -1, 8822), (2, -1, 0, -1, 8216), (2, 0, -2, -1, 4324),
    (2, 0, 1, 1, 4200), (2, 1, 0, -1, -3359), (2, -1, -1, 1, 2463),
    (2, -1, 0, 1, 2211), (2, -1, -1, -1, 2065), (0, 1, -1, -1, -1870),
    (4, 0, -1, -1, 1828), (0, 1, 0, 1, -1794), (0, 0, 0, 3, -1749),
    (0, 1, -1, 1, -1565), (1, 0, 0, 1, -1491), (0, 1, 1, 1, -1475),
    (0, 1, 1, -1, -1410), (0, 1, 0, -1, -1344), (1, 0, 0, -1, -1335),
    (0, 0, 3, 1, 1107), (4, 0, 0, -1, 1021), (4, 0, -1, 1, 833),
)


def moon_position(jd: float) -> tuple[float, float, float]:
    """(longitude apparente °, latitude °, distance au centre de la Terre km)."""
    t = _centuries(jd)
    lp = 218.3164477 + 481267.88123421 * t - 0.0015786 * t * t
    d = 297.8501921 + 445267.1114034 * t - 0.0018819 * t * t
    m = 357.5291092 + 35999.0502909 * t - 0.0001536 * t * t
    mp = 134.9633964 + 477198.8675055 * t + 0.0087414 * t * t
    f = 93.2720950 + 483202.0175233 * t - 0.0036539 * t * t
    a1 = 119.75 + 131.849 * t
    a2 = 53.09 + 479264.290 * t
    a3 = 313.45 + 481266.484 * t
    e = 1 - 0.002516 * t - 0.0000074 * t * t
    sl = sr = sb = 0.0
    for cd, cm, cmp_, cf, l_, r_ in _LR:
        arg = cd * d + cm * m + cmp_ * mp + cf * f
        k = e ** abs(cm)
        sl += l_ * k * _sin(arg)
        sr += r_ * k * _cos(arg)
    for cd, cm, cmp_, cf, b_ in _B:
        sb += b_ * e ** abs(cm) * _sin(cd * d + cm * m + cmp_ * mp + cf * f)
    sl += 3958 * _sin(a1) + 1962 * _sin(lp - f) + 318 * _sin(a2)
    sb += (-2235 * _sin(lp) + 382 * _sin(a3) + 175 * _sin(a1 - f) + 175 * _sin(a1 + f)
           + 127 * _sin(lp - mp) - 115 * _sin(lp + mp))
    omega = 125.04452 - 1934.136261 * t
    nutation = -0.004778 * _sin(omega)
    return (lp + sl / 1e6 + nutation) % 360, sb / 1e6, 385000.56 + sr / 1000


# ---------------------------------------------------- coordonnées locales
def _obliquity(jd: float) -> float:
    t = _centuries(jd)
    return 23.4392911 - 0.0130042 * t + 0.00256 * _cos(125.04 - 1934.136 * t)


def _equatorial(lam: float, beta: float, eps: float) -> tuple[float, float]:
    ra = math.atan2(_sin(lam) * _cos(eps) - math.tan(beta * _RAD) * _sin(eps), _cos(lam)) / _RAD
    dec = math.asin(_sin(beta) * _cos(eps) + _cos(beta) * _sin(eps) * _sin(lam)) / _RAD
    return ra % 360, dec


def _sidereal(jd: float) -> float:
    return (280.46061837 + 360.98564736629 * (jd - 2451545.0)) % 360


def _topocentric(ra: float, dec: float, distance_km: float, jd: float,
                 lat: float = PARIS_LAT, lon: float = PARIS_LON) -> tuple[float, float, float]:
    """(ascension droite, déclinaison, hauteur °) vues du lieu (Meeus ch. 40)."""
    u = math.atan(0.99664719 * math.tan(lat * _RAD))
    rho_sin = 0.99664719 * math.sin(u)
    rho_cos = math.cos(u)
    sin_pi = 6378.14 / distance_km
    h = (_sidereal(jd) + lon - ra) % 360
    d_ra = math.atan2(-rho_cos * sin_pi * _sin(h), _cos(dec) - rho_cos * sin_pi * _cos(h))
    dec_t = math.atan2((_sin(dec) - rho_sin * sin_pi) * math.cos(d_ra),
                       _cos(dec) - rho_cos * sin_pi * _cos(h)) / _RAD
    ra_t = ra + d_ra / _RAD
    h_t = h - d_ra / _RAD
    alt = math.asin(_sin(lat) * _sin(dec_t) + _cos(lat) * _cos(dec_t) * _cos(h_t)) / _RAD
    return ra_t % 360, dec_t, alt


def _sun_local(jd: float) -> tuple[float, float, float, float]:
    """Soleil vu de Paris : (ra, dec, hauteur, demi-diamètre °)."""
    lam, beta, r = sun_position(jd)
    ra, dec = _equatorial(lam, beta, _obliquity(jd))
    ra, dec, alt = _topocentric(ra, dec, r * 149597870.7, jd)
    return ra, dec, alt, 0.266563 / r


def _moon_local(jd: float) -> tuple[float, float, float, float]:
    """Lune vue de Paris : (ra, dec, hauteur, demi-diamètre °)."""
    lam, beta, dist = moon_position(jd)
    ra, dec = _equatorial(lam, beta, _obliquity(jd))
    ra, dec, alt = _topocentric(ra, dec, dist, jd)
    return ra, dec, alt, 0.272481 * 6378.14 / (dist - 6378.14 * _sin(max(alt, 0.0))) / _RAD


def sun_altitude(when: datetime) -> float:
    return _sun_local(julian_day(when))[2]


def moon_altitude(when: datetime) -> float:
    return _moon_local(julian_day(when))[2]


def _separation(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    c = _sin(dec1) * _sin(dec2) + _cos(dec1) * _cos(dec2) * _cos(ra1 - ra2)
    return math.acos(max(-1.0, min(1.0, c))) / _RAD


# --------------------------------------------------------------- phases
def _elongation(jd: float) -> float:
    """Longitude de la Lune moins celle du Soleil, dans [-180, 180[."""
    return (moon_position(jd)[0] - sun_position(jd)[0] + 180) % 360 - 180


def _phase_time(k: int, target: float) -> float:
    """Instant (JD) de la phase `target` (0 = nouvelle, 180 = pleine) de la
    lunaison k, par dichotomie autour de l'estimation moyenne."""
    guess = _K0_JDE + (k + target / 360) * SYNODIC_MONTH

    def off(jd: float) -> float:
        return (_elongation(jd) - target + 180) % 360 - 180

    lo, hi = guess - 2.0, guess + 2.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if off(mid) > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def lunation(when: datetime) -> int:
    """Numéro de la lunaison en cours (k de Meeus : 0 = janvier 2000)."""
    return math.floor((julian_day(when) - _K0_JDE) / SYNODIC_MONTH)


@lru_cache(maxsize=512)
def full_moon(k: int) -> datetime:
    return from_julian_day(_phase_time(k, 180.0))


@lru_cache(maxsize=512)
def new_moon(k: int) -> datetime:
    return from_julian_day(_phase_time(k, 0.0))


def phase_fraction(when: datetime) -> float:
    """Âge de la lune en fraction de lunaison (0 = nouvelle, 0,5 = pleine)."""
    return ((_elongation(julian_day(when)) % 360) / 360)


def illumination(when: datetime) -> float:
    """Part éclairée du disque (0 à 1)."""
    return (1 - _cos(_elongation(julian_day(when)))) / 2


# ------------------------------------------------------- jour et nuit
def _crossing(f, lo: float, hi: float) -> float:
    """Instant (JD) où f change de signe entre lo et hi."""
    flo = f(lo)
    for _ in range(40):
        mid = (lo + hi) / 2
        if (f(mid) > 0) == (flo > 0):
            lo, flo = mid, f(mid)
        else:
            hi = mid
    return (lo + hi) / 2


def _sun_events(start_jd: float, end_jd: float, step: float = 1 / 48) -> list[tuple[float, bool]]:
    """(instant, True = lever) des levers / couchers du Soleil entre deux dates."""
    def f(jd: float) -> float:
        return _sun_local(jd)[2] - SUN_HORIZON

    out = []
    jd, prev = start_jd, f(start_jd)
    while jd < end_jd:
        nxt_jd = jd + step
        nxt = f(nxt_jd)
        if (prev > 0) != (nxt > 0):
            out.append((_crossing(f, jd, nxt_jd), nxt > 0))
        jd, prev = nxt_jd, nxt
    return out


def night_around(when: datetime) -> tuple[datetime, datetime]:
    """La nuit de Paris (coucher → lever du Soleil) qui contient `when` ou,
    s'il fait jour, la plus proche de `when`."""
    jd = julian_day(when)
    events = _sun_events(jd - 1.5, jd + 1.5)
    nights = []
    for (t1, rise1), (t2, rise2) in zip(events, events[1:]):
        if not rise1 and rise2:
            nights.append((t1, t2))
    best = min(nights, key=lambda n: 0 if n[0] <= jd <= n[1] else min(abs(jd - n[0]), abs(jd - n[1])))
    return from_julian_day(best[0]), from_julian_day(best[1])


def sun_times(day_noon: datetime) -> tuple[datetime | None, datetime | None]:
    """(lever, coucher) du Soleil à Paris le jour de `day_noon` (midi local)."""
    jd = julian_day(day_noon)
    rise = sets = None
    for t, is_rise in _sun_events(jd - 0.5, jd + 0.5):
        if is_rise and rise is None:
            rise = from_julian_day(t)
        if not is_rise:
            sets = from_julian_day(t)
    return rise, sets


# --------------------------------------------------------------- éclipses
@dataclass(frozen=True)
class Eclipse:
    kind: str                # "lune" ou "soleil"
    start: datetime          # début de la partie VISIBLE de Paris
    end: datetime
    peak: datetime
    magnitude: float         # éclipse de Lune : part du diamètre lunaire dans l'ombre ;
                             # de Soleil : part du diamètre solaire couverte
    total: bool


_SCAN_MINUTES = 4


def _umbral_magnitude(jd: float) -> float:
    """Grandeur de l'éclipse de Lune par l'OMBRE (négative = hors de l'ombre)."""
    lam_s, _, r = sun_position(jd)
    lam_m, beta_m, dist = moon_position(jd)
    sep = math.acos(max(-1.0, min(1.0, _cos(beta_m) * _cos(lam_m - lam_s - 180)))) / _RAD
    parallax_moon = math.asin(6378.14 / dist) / _RAD
    sun_radius = 0.266563 / r
    umbra = 1.02 * (0.998340 * parallax_moon - sun_radius + 0.002443 / r)
    moon_radius = 0.272481 * parallax_moon
    return (umbra + moon_radius - sep) / (2 * moon_radius)


@lru_cache(maxsize=256)
def lunar_eclipse(k: int) -> Eclipse | None:
    """L'éclipse de Lune (par l'ombre) de la pleine lune k, si elle est
    visible de Paris (Lune au-dessus de l'horizon pendant l'éclipse)."""
    center = julian_day(full_moon(k))
    if _umbral_magnitude(center) < -0.6:          # loin de l'ombre : rien
        return None
    step = _SCAN_MINUTES / 1440
    visible = []
    peak_mag, peak_jd = -9.0, center
    jd = center - 0.25
    while jd <= center + 0.25:
        mag = _umbral_magnitude(jd)
        if mag > 0 and _moon_local(jd)[2] > 0 and _sun_local(jd)[2] < 0:
            visible.append(jd)
            if mag > peak_mag:
                peak_mag, peak_jd = mag, jd
        jd += step
    if not visible:
        return None
    return Eclipse("lune", from_julian_day(visible[0]), from_julian_day(visible[-1]),
                   from_julian_day(peak_jd), round(peak_mag, 3), peak_mag >= 1)


def _solar_magnitude(jd: float) -> tuple[float, float]:
    """(grandeur vue de Paris, hauteur du Soleil)."""
    ra_s, dec_s, alt_s, r_s = _sun_local(jd)
    ra_m, dec_m, _, r_m = _moon_local(jd)
    sep = _separation(ra_s, dec_s, ra_m, dec_m)
    return (r_s + r_m - sep) / (2 * r_s), alt_s


@lru_cache(maxsize=256)
def solar_eclipse(k: int) -> Eclipse | None:
    """L'éclipse de Soleil de la nouvelle lune k, si elle est visible de
    Paris (disques qui se chevauchent, Soleil levé)."""
    center = julian_day(new_moon(k))
    if abs(moon_position(center)[1]) > 1.6:        # trop loin du nœud : aucune éclipse
        return None
    step = _SCAN_MINUTES / 1440
    visible = []
    peak_mag, peak_jd = -9.0, center
    jd = center - 0.3
    while jd <= center + 0.3:
        mag, alt = _solar_magnitude(jd)
        if mag > 0 and alt > SUN_HORIZON:
            visible.append(jd)
            if mag > peak_mag:
                peak_mag, peak_jd = mag, jd
        jd += step
    if not visible:
        return None
    return Eclipse("soleil", from_julian_day(visible[0]), from_julian_day(visible[-1]),
                   from_julian_day(peak_jd), round(peak_mag, 3), peak_mag >= 1)

