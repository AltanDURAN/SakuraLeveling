"""Événements saisonniers — règles PURES (décembre 2026, demande de l'auteur).

Trois événements pour le lancement de la saison 1, bâtis sur des briques
RÉUTILISABLES (« il y aura souvent des boutiques d'événement ») :

  • CALENDRIER DE L'AVENT : une case par jour, à ouvrir LE jour même, une
    petite récompense — c'est le début de l'aventure, rien qui change la
    partie ;
  • NOËL : un cadeau à ouvrir à partir du 25, selon la GENTILLESSE = le
    ratio d'aide à la petite fille (`kindness`) : moins de 50 % d'aide,
    50 % du cadeau ; au moins 50 %, 100 % ; toujours aidée, 150 % ;
  • OBJETS D'ÉVÉNEMENT (`EventDrop`) : pendant une période, chaque monstre
    de zone vaincu donne un objet à chaque survivant (les sucres d'orge, du
    18 au 24 décembre) ;
  • BOUTIQUES D'ÉVÉNEMENT (`EventShop`) : une monnaie (un objet), une
    période d'ouverture, des articles avec un prix et une limite par joueur
    (l'atelier des lutins, du 25 au 31 décembre) ;
  • NOUVEL AN : toutes les divinités de l'offrande bénissent le serveur
    pendant les premières heures de l'année, annoncé à minuit.

Tout vient de `seasonal_events.json` (réglable sur le site). Les dates sont
des jours de PARIS, bornes comprises.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")

# ---------------------------------------------------------------- récompenses
GOLD = "gold"                       # or fixe
GOLD_PER_LEVEL = "gold_per_level"   # or × niveau du joueur
ITEM = "item"                       # un objet (code de items.json) × quantité
REWARD_KINDS = (GOLD, GOLD_PER_LEVEL, ITEM)


@dataclass(frozen=True)
class Reward:
    kind: str
    amount: int = 0     # or (fixe, ou par niveau)
    item: str = ""      # code de l'objet
    qty: int = 0

    def gold(self, level: int) -> int:
        if self.kind == GOLD:
            return self.amount
        if self.kind == GOLD_PER_LEVEL:
            return self.amount * max(1, int(level))
        return 0


def _scaled(value: int, pct: int) -> int:
    """`value` × `pct` %, arrondi au plus proche, jamais moins de 1 (0 si
    pct = 0 : un réglage à 0 retire la ligne)."""
    if pct <= 0 or value <= 0:
        return 0
    return max(1, math.floor(value * pct / 100 + 0.5))


def scale(reward: Reward, pct: int) -> Reward:
    if reward.kind == ITEM:
        return Reward(ITEM, item=reward.item, qty=_scaled(reward.qty, pct))
    return Reward(reward.kind, amount=_scaled(reward.amount, pct))


def scale_all(rewards, pct: int) -> tuple[Reward, ...]:
    return tuple(r for r in (scale(r, pct) for r in rewards) if r.amount or r.qty)


def parse_reward(raw: dict) -> Reward:
    kind = str(raw.get("kind", "")).strip()
    if kind == ITEM:
        return Reward(ITEM, item=str(raw.get("item", "")).strip(), qty=int(raw.get("qty", 1) or 0))
    return Reward(kind, amount=int(raw.get("amount", 0) or 0))


def reward_to_dict(reward: Reward) -> dict:
    if reward.kind == ITEM:
        return {"kind": ITEM, "item": reward.item, "qty": reward.qty}
    return {"kind": reward.kind, "amount": reward.amount}


def _reward_problems(raw, where: str, item_codes: set[str] | None) -> list[str]:
    problems = []
    if not isinstance(raw, dict):
        return [f"{where} : récompense illisible"]
    kind = raw.get("kind")
    if kind not in REWARD_KINDS:
        return [f"{where} : type de récompense inconnu ({kind!r})"]
    try:
        reward = parse_reward(raw)
    except (TypeError, ValueError):
        return [f"{where} : nombre illisible"]
    if kind == ITEM:
        if not reward.item:
            problems.append(f"{where} : objet manquant")
        elif item_codes is not None and reward.item not in item_codes:
            problems.append(f"{where} : objet inconnu « {reward.item} »")
        if reward.qty < 1:
            problems.append(f"{where} : quantité ≥ 1")
    elif reward.amount < 1:
        problems.append(f"{where} : montant d'or ≥ 1")
    return problems


# ---------------------------------------------------------------------- dates
def paris_day(now: datetime | None = None) -> date:
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(PARIS).date()


def day_start(day: date) -> datetime:
    """Minuit de Paris ce jour-là, en UTC (aware)."""
    return datetime.combine(day, time(0, 0), tzinfo=PARIS).astimezone(UTC)


def _date(raw, where: str) -> date:
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{where} : date illisible ({raw!r}, attendu AAAA-MM-JJ)") from exc


# -------------------------------------------------------------- l'Avent
OPENED, TODAY, MISSED, LOCKED = "opened", "today", "missed", "locked"


@dataclass(frozen=True)
class Advent:
    enabled: bool
    name: str
    start: date
    days: tuple[tuple[Reward, ...], ...]     # la case 1 = days[0]

    @property
    def size(self) -> int:
        return len(self.days)

    @property
    def end(self) -> date:
        return self.start + timedelta(days=max(0, self.size - 1))

    def day_of(self, today: date) -> int | None:
        """Numéro de la case du jour (1…N), None hors du calendrier."""
        if not self.enabled or not self.size:
            return None
        n = (today - self.start).days + 1
        return n if 1 <= n <= self.size else None

    def rewards(self, day: int) -> tuple[Reward, ...]:
        return self.days[day - 1] if 1 <= day <= self.size else ()


def door_states(advent: Advent, today: date, opened: set[int]) -> list[str]:
    """État de chaque case : ouverte, à ouvrir aujourd'hui, manquée (on
    n'ouvre que la case du jour) ou pas encore."""
    current = (today - advent.start).days + 1
    states = []
    for n in range(1, advent.size + 1):
        if n in opened:
            states.append(OPENED)
        elif n == current:
            states.append(TODAY)
        elif n < current:
            states.append(MISSED)
        else:
            states.append(LOCKED)
    return states


# --------------------------------------------------------------- gentillesse
UNKNOWN, NAUGHTY, NICE, ANGEL = "unknown", "naughty", "nice", "angel"


@dataclass(frozen=True)
class KindnessRules:
    #: Au moins ce % d'aide à la petite fille : « gentil ».
    nice_from_pct: int = 50
    #: Part du cadeau (en %) selon la gentillesse.
    naughty_pct: int = 50
    nice_pct: int = 100
    angel_pct: int = 150
    #: Jamais croisé la petite fille : ni gentil ni méchant.
    unknown_pct: int = 100


@dataclass(frozen=True)
class Kindness:
    helps: int
    ignores: int
    tier: str
    pct: int

    @property
    def total(self) -> int:
        return self.helps + self.ignores

    @property
    def ratio(self) -> float | None:
        return self.helps / self.total if self.total else None


def kindness(helps: int, ignores: int, rules: KindnessRules = KindnessRules()) -> Kindness:
    helps, ignores = max(0, int(helps)), max(0, int(ignores))
    total = helps + ignores
    if not total:
        return Kindness(helps, ignores, UNKNOWN, rules.unknown_pct)
    if helps == total:
        return Kindness(helps, ignores, ANGEL, rules.angel_pct)
    if helps * 100 >= rules.nice_from_pct * total:
        return Kindness(helps, ignores, NICE, rules.nice_pct)
    return Kindness(helps, ignores, NAUGHTY, rules.naughty_pct)


# --------------------------------------------------------------------- Noël
@dataclass(frozen=True)
class Christmas:
    enabled: bool
    name: str
    gift_day: date
    claim_until: date
    rewards: tuple[Reward, ...]
    kindness: KindnessRules = KindnessRules()

    def gift_open(self, today: date) -> bool:
        return self.enabled and self.gift_day <= today <= self.claim_until

    def gift_for(self, k: Kindness) -> tuple[Reward, ...]:
        return scale_all(self.rewards, k.pct)


# ----------------------------------------------------- objets d'événement
@dataclass(frozen=True)
class EventDrop:
    code: str
    name: str
    enabled: bool
    item: str
    per_kill: int
    start: date
    end: date
    announce: str = ""

    def active(self, today: date) -> bool:
        return self.enabled and self.per_kill > 0 and self.start <= today <= self.end


def active_drops(drops, today: date) -> list[EventDrop]:
    return [d for d in drops if d.active(today)]


# --------------------------------------------------- boutiques d'événement
@dataclass(frozen=True)
class ShopOffer:
    item: str
    price: int
    limit: int = 0       # par joueur ; 0 = sans limite


@dataclass(frozen=True)
class EventShop:
    code: str
    name: str
    emoji: str
    enabled: bool
    currency: str        # code de l'objet qui sert de monnaie
    opens: date
    closes: date
    intro: str = ""
    offers: tuple[ShopOffer, ...] = ()

    def is_open(self, today: date) -> bool:
        return self.enabled and self.opens <= today <= self.closes

    def offer(self, item: str) -> ShopOffer | None:
        return next((o for o in self.offers if o.item == item), None)

    @property
    def label(self) -> str:
        return f"{self.emoji} {self.name}".strip()


def max_buyable(offer: ShopOffer, balance: int, bought: int) -> int:
    """Combien on peut encore en acheter : monnaie et limite."""
    by_money = balance // offer.price if offer.price > 0 else 999
    by_limit = max(0, offer.limit - bought) if offer.limit else 999
    return max(0, min(by_money, by_limit))


# ------------------------------------------------------------------ Nouvel An
@dataclass(frozen=True)
class NewYear:
    enabled: bool
    day: date
    hours: int
    title: str
    message: str
    mention_everyone: bool = True

    def window(self) -> tuple[datetime, datetime]:
        start = day_start(self.day)
        return start, start + timedelta(hours=max(1, self.hours))

    def active(self, now: datetime) -> bool:
        if not self.enabled:
            return False
        now = now if now.tzinfo else now.replace(tzinfo=UTC)
        start, end = self.window()
        return start <= now < end


def window_minus(window: tuple[datetime, datetime],
                 other: tuple[datetime, datetime] | None) -> list[tuple[datetime, datetime]]:
    """`window` privée de `other` (0, 1 ou 2 morceaux) : une même divinité ne
    bénit pas deux fois la même minute."""
    start, end = window
    if other is None or other[1] <= start or other[0] >= end:
        return [window]
    parts = []
    if other[0] > start:
        parts.append((start, other[0]))
    if other[1] < end:
        parts.append((other[1], end))
    return parts


# -------------------------------------------------------------- le contenu
@dataclass(frozen=True)
class SeasonalContent:
    advent: Advent | None = None
    christmas: Christmas | None = None
    new_year: NewYear | None = None
    drops: tuple[EventDrop, ...] = ()
    shops: tuple[EventShop, ...] = ()
    problems: tuple[str, ...] = field(default=())

    def shop(self, code: str) -> EventShop | None:
        return next((s for s in self.shops if s.code == code), None)

    def open_shops(self, today: date) -> list[EventShop]:
        return [s for s in self.shops if s.is_open(today)]


def _bool(raw, default: bool = True) -> bool:
    return bool(raw) if raw is not None else default


def parse_content(raw: dict) -> SeasonalContent:
    """Lit `seasonal_events.json`. Une section illisible est ignorée (et
    signalée dans `problems`) : un réglage cassé ne fait pas tomber le bot."""
    raw = raw if isinstance(raw, dict) else {}
    problems: list[str] = []
    advent = christmas = new_year = None
    section = raw.get("advent")
    if isinstance(section, dict):
        try:
            advent = Advent(
                enabled=_bool(section.get("enabled")), name=str(section.get("name") or "Calendrier de l'Avent"),
                start=_date(section.get("start"), "Avent"),
                days=tuple(tuple(parse_reward(r) for r in day) for day in section.get("days") or []))
        except (TypeError, ValueError, AttributeError) as exc:
            problems.append(f"Avent ignoré : {exc}")
    section = raw.get("christmas")
    if isinstance(section, dict):
        try:
            k = section.get("kindness") or {}
            christmas = Christmas(
                enabled=_bool(section.get("enabled")), name=str(section.get("name") or "Noël"),
                gift_day=_date(section.get("gift_day"), "Noël"),
                claim_until=_date(section.get("claim_until"), "Noël (fin)"),
                rewards=tuple(parse_reward(r) for r in section.get("rewards") or []),
                kindness=KindnessRules(**{f: int(k[f]) for f in KindnessRules.__dataclass_fields__ if f in k}))
        except (TypeError, ValueError, AttributeError) as exc:
            problems.append(f"Noël ignoré : {exc}")
    section = raw.get("new_year")
    if isinstance(section, dict):
        try:
            new_year = NewYear(
                enabled=_bool(section.get("enabled")), day=_date(section.get("day"), "Nouvel An"),
                hours=int(section["hours"]) if section.get("hours") is not None else 24,
                title=str(section.get("title") or "Bonne année !"),
                message=str(section.get("message") or ""),
                mention_everyone=_bool(section.get("mention_everyone")))
        except (TypeError, ValueError) as exc:
            problems.append(f"Nouvel An ignoré : {exc}")
    drops = []
    for i, d in enumerate(raw.get("drops") or []):
        try:
            drops.append(EventDrop(
                code=str(d["code"]), name=str(d.get("name") or d["code"]), enabled=_bool(d.get("enabled")),
                item=str(d["item"]), per_kill=int(d.get("per_kill", 1)),
                start=_date(d.get("start"), f"Objet d'événement {i + 1}"),
                end=_date(d.get("end"), f"Objet d'événement {i + 1}"), announce=str(d.get("announce") or "")))
        except (KeyError, TypeError, ValueError) as exc:
            problems.append(f"Objet d'événement {i + 1} ignoré : {exc}")
    shops = []
    for i, s in enumerate(raw.get("shops") or []):
        try:
            shops.append(EventShop(
                code=str(s["code"]), name=str(s.get("name") or s["code"]), emoji=str(s.get("emoji") or "🎁"),
                enabled=_bool(s.get("enabled")), currency=str(s["currency"]),
                opens=_date(s.get("opens"), f"Boutique {i + 1}"), closes=_date(s.get("closes"), f"Boutique {i + 1}"),
                intro=str(s.get("intro") or ""),
                offers=tuple(ShopOffer(str(o["item"]), int(o.get("price", 0)), int(o.get("limit", 0) or 0))
                             for o in s.get("offers") or [])))
        except (KeyError, TypeError, ValueError) as exc:
            problems.append(f"Boutique {i + 1} ignorée : {exc}")
    return SeasonalContent(advent, christmas, new_year, tuple(drops), tuple(shops), tuple(problems))


def validate(raw: dict, item_codes: set[str] | None = None) -> list[str]:
    """Problèmes BLOQUANTS d'un contenu (site admin : rien n'est écrit sinon)."""
    content = parse_content(raw)
    problems = list(content.problems)
    if content.advent is not None:
        if not content.advent.size:
            problems.append("Avent : aucune case")
        for n, day in enumerate((raw.get("advent") or {}).get("days") or [], start=1):
            if not day:
                problems.append(f"Avent, case {n} : vide")
            for r in day:
                problems += _reward_problems(r, f"Avent, case {n}", item_codes)
    if content.christmas is not None:
        c = content.christmas
        if c.claim_until < c.gift_day:
            problems.append("Noël : la fin du cadeau est avant son jour")
        if not c.rewards:
            problems.append("Noël : le cadeau est vide")
        for r in (raw.get("christmas") or {}).get("rewards") or []:
            problems += _reward_problems(r, "Cadeau de Noël", item_codes)
        k = c.kindness
        if not 1 <= k.nice_from_pct <= 100:
            problems.append("Noël : le seuil « gentil » doit être entre 1 et 100 %")
        if min(k.naughty_pct, k.nice_pct, k.angel_pct, k.unknown_pct) < 0:
            problems.append("Noël : une part de cadeau est négative")
    if content.new_year is not None and not 1 <= content.new_year.hours <= 72:
        problems.append("Nouvel An : la durée doit être entre 1 et 72 heures")
    codes = [d.code for d in content.drops] + [s.code for s in content.shops]
    if len(codes) != len(set(codes)):
        problems.append("Deux objets d'événement ou boutiques portent le même code")
    for d in content.drops:
        if d.end < d.start:
            problems.append(f"{d.name} : la fin est avant le début")
        if d.per_kill < 1:
            problems.append(f"{d.name} : au moins 1 objet par monstre")
        if item_codes is not None and d.item not in item_codes:
            problems.append(f"{d.name} : objet inconnu « {d.item} »")
    for s in content.shops:
        if s.closes < s.opens:
            problems.append(f"{s.name} : la fermeture est avant l'ouverture")
        if item_codes is not None and s.currency not in item_codes:
            problems.append(f"{s.name} : monnaie inconnue « {s.currency} »")
        if not s.offers:
            problems.append(f"{s.name} : aucun article")
        seen = set()
        for o in s.offers:
            if o.item in seen:
                problems.append(f"{s.name} : « {o.item} » vendu deux fois")
            seen.add(o.item)
            if item_codes is not None and o.item not in item_codes:
                problems.append(f"{s.name} : objet inconnu « {o.item} »")
            if o.price < 1:
                problems.append(f"{s.name} : prix de « {o.item} » ≥ 1")
            if o.limit < 0:
                problems.append(f"{s.name} : limite de « {o.item} » ≥ 0")
    return problems


# ---------------------------------------------------------------- annonces
@dataclass(frozen=True)
class Announcement:
    key: str            # unique, gardé en base une fois posté
    kind: str           # advent | drop | christmas | shop | new_year
    ref: str            # code de l'objet d'événement / de la boutique
    at: datetime        # quand la poster (UTC)
    until: datetime     # trop tard après (le bot était éteint)


def announcements(content: SeasonalContent) -> list[Announcement]:
    """Le moment de chaque annonce : ouverture de l'Avent, début d'un objet
    d'événement, matin de Noël, ouverture d'une boutique (sauf si Noël
    l'annonce déjà), minuit du Nouvel An."""
    found = []
    a = content.advent
    if a is not None and a.enabled and a.size:
        found.append(Announcement(f"advent:{a.start}", "advent", "", day_start(a.start),
                                  day_start(a.end + timedelta(days=1))))
    for d in content.drops:
        if d.enabled:
            found.append(Announcement(f"drop:{d.code}:{d.start}", "drop", d.code, day_start(d.start),
                                      day_start(d.end + timedelta(days=1))))
    c = content.christmas
    if c is not None and c.enabled:
        found.append(Announcement(f"christmas:{c.gift_day}", "christmas", "", day_start(c.gift_day),
                                  day_start(c.claim_until + timedelta(days=1))))
    for s in content.shops:
        if not s.enabled or (c is not None and c.enabled and s.opens == c.gift_day):
            continue        # le matin de Noël présente aussi la boutique
        found.append(Announcement(f"shop:{s.code}:{s.opens}", "shop", s.code, day_start(s.opens),
                                  day_start(s.closes + timedelta(days=1))))
    n = content.new_year
    if n is not None and n.enabled:
        start, end = n.window()
        found.append(Announcement(f"new_year:{n.day}", "new_year", "", start, end))
    return sorted(found, key=lambda x: x.at)


def due(content: SeasonalContent, now: datetime, done: set[str]) -> list[Announcement]:
    """Les annonces à poster maintenant (pas encore faites, encore à temps)."""
    now = now if now.tzinfo else now.replace(tzinfo=UTC)
    return [a for a in announcements(content) if a.key not in done and a.at <= now < a.until]


# ------------------------------------------------------- ce qui se passe
@dataclass(frozen=True)
class Happening:
    advent_day: int | None
    christmas_open: bool
    drops: tuple[EventDrop, ...]
    shops: tuple[EventShop, ...]
    new_year: bool
    #: Prochains débuts : (date, libellé), du plus proche au plus lointain.
    upcoming: tuple[tuple[date, str], ...]

    @property
    def anything(self) -> bool:
        return bool(self.advent_day or self.christmas_open or self.drops or self.shops or self.new_year)

    def signature(self) -> str:
        """Change quand ce qui se passe change (le panneau est alors réécrit)."""
        return "|".join([str(self.advent_day or ""), str(self.christmas_open), ",".join(d.code for d in self.drops),
                         ",".join(s.code for s in self.shops), str(self.new_year),
                         ",".join(f"{d}:{label}" for d, label in self.upcoming)])


def happening(content: SeasonalContent, now: datetime) -> Happening:
    today = paris_day(now)
    upcoming: list[tuple[date, str]] = []
    a, c, n = content.advent, content.christmas, content.new_year
    if a is not None and a.enabled and a.size and today < a.start:
        upcoming.append((a.start, f"🎄 {a.name}"))
    for d in content.drops:
        if d.enabled and today < d.start:
            upcoming.append((d.start, f"🍬 {d.name}"))
    if c is not None and c.enabled and today < c.gift_day:
        upcoming.append((c.gift_day, f"🎅 {c.name}"))
    for s in content.shops:
        if s.enabled and today < s.opens:
            upcoming.append((s.opens, s.label))
    if n is not None and n.enabled and today < n.day:
        upcoming.append((n.day, f"🎆 {n.title}"))
    return Happening(
        advent_day=a.day_of(today) if a is not None else None,
        christmas_open=c is not None and c.gift_open(today),
        drops=tuple(active_drops(content.drops, today)),
        shops=tuple(content.open_shops(today)),
        new_year=n is not None and n.active(now if now.tzinfo else now.replace(tzinfo=UTC)),
        upcoming=tuple(sorted(upcoming)),
    )
