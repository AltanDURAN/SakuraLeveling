"""Qui voit quel salon : le plan d'accès du serveur (08/11/2026, demande de
l'auteur).

Le parcours d'arrivée :
  • en arrivant, on ne voit que l'accueil et le règlement, en lecture seule ;
  • accepter le règlement donne le Rang F : le tutoriel, la tour et la
    première zone s'ouvrent ;
  • finir ou passer le tutoriel donne le rôle Aventurier : tout le reste du
    serveur s'ouvre (général, annonces, raid, événements, records, vocal…) ;
  • chaque rang gagné à l'épreuve ouvre sa zone ; un rang voit aussi les
    zones en dessous.

Règles PURES, sans Discord : à partir des permissions actuelles d'un salon, ce
qu'elles doivent devenir. Seuls @everyone, les rôles de rang et Aventurier sont
gérés, et seulement le droit de VOIR (plus celui d'écrire dans un salon en
lecture seule) : les autres rôles et réglages restent tels quels. Un salon que
ni @everyone ni ces rôles ne voient (un salon d'équipe) n'est jamais touché.
Les rôles des membres, eux, ne font que s'AJOUTER (`roles_to_add`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Bits de permission de Discord.
ADD_REACTIONS = 1 << 6
VIEW_CHANNEL = 1 << 10
SEND_MESSAGES = 1 << 11
CREATE_PUBLIC_THREADS = 1 << 35
CREATE_PRIVATE_THREADS = 1 << 36
SEND_MESSAGES_IN_THREADS = 1 << 38
#: Ce qu'interdit un salon en lecture seule.
WRITE = SEND_MESSAGES | CREATE_PUBLIC_THREADS | CREATE_PRIVATE_THREADS | SEND_MESSAGES_IN_THREADS

#: Miroir de `app.bot.rank_roles.RANK_ORDER`.
RANK_ORDER: tuple[str, ...] = ("F", "E", "D", "C", "B", "A", "S", "SS", "SSS")

#: Permissions d'une cible dans un salon : (autorisé, refusé).
Overwrite = tuple[int, int]
EMPTY: Overwrite = (0, 0)


@dataclass(frozen=True)
class Audience:
    """Qui doit voir un salon."""

    kind: str                 # "public" (lecture seule), "rank" ou "adventurer"
    min_rank: str = "F"       # "rank" : ce rang et les suivants
    reactions: bool = True    # "public" : réactions permises

    @property
    def label(self) -> str:
        if self.kind == "public":
            return "tout le monde, lecture seule"
        if self.kind == "adventurer":
            return "aventuriers"
        return f"Rang {self.min_rank} et plus"


PUBLIC = Audience("public")
PUBLIC_NO_REACTIONS = Audience("public", reactions=False)
ADVENTURERS = Audience("adventurer")


def rank_audience(rank: str) -> Audience:
    return Audience("rank", min_rank=rank if rank in RANK_ORDER else "F")


@dataclass(frozen=True)
class Roles:
    """Les rôles du parcours sur le serveur."""

    everyone: int             # @everyone : son identifiant est celui du serveur
    ranks: dict[str, int]     # F → SSS
    adventurer: int

    @property
    def managed(self) -> tuple[int, ...]:
        """Les rôles dont le plan décide (pas @everyone)."""
        ranks = tuple(self.ranks[r] for r in RANK_ORDER if r in self.ranks)
        return ranks + ((self.adventurer,) if self.adventurer else ())

    def allowed(self, audience: Audience) -> set[int]:
        if audience.kind == "adventurer":
            return {self.adventurer} if self.adventurer else set()
        if audience.kind == "rank":
            start = RANK_ORDER.index(audience.min_rank)
            return {self.ranks[r] for r in RANK_ORDER[start:] if r in self.ranks}
        return set()


def channel_audiences(*, welcome: int, rules: int, tutorial: int, tower: int,
                      zones: list[tuple[int, str]]) -> dict[int, Audience]:
    """Les salons au rôle particulier ; tous les autres sont aux aventuriers.

    `zones` : (salon, rang requis) des zones de farm OUVERTES."""
    out: dict[int, Audience] = {}
    for channel_id, rank in zones:
        if channel_id:
            out[channel_id] = rank_audience(rank)
    for channel_id in (tutorial, tower):            # le tutoriel s'y joue
        if channel_id:
            out[channel_id] = rank_audience("F")
    if welcome:
        out[welcome] = PUBLIC                       # on y accueille d'une réaction
    if rules:
        out[rules] = PUBLIC_NO_REACTIONS            # on y accepte d'un bouton
    return out


def _set(current: Overwrite, *, allow: int = 0, deny: int = 0, clear: int = 0) -> Overwrite:
    allowed, denied = current
    return ((allowed | allow) & ~deny & ~clear, (denied | deny) & ~allow & ~clear)


def wanted(audience: Audience, roles: Roles, current: dict[int, Overwrite]) -> dict[int, Overwrite]:
    """Les permissions voulues pour @everyone et les rôles du parcours, les
    autres bits gardés."""
    def now(target: int) -> Overwrite:
        return current.get(target, EMPTY)

    out: dict[int, Overwrite] = {}
    if audience.kind == "public":
        everyone = _set(now(roles.everyone), allow=VIEW_CHANNEL, deny=WRITE)
        out[roles.everyone] = (_set(everyone, clear=ADD_REACTIONS) if audience.reactions
                               else _set(everyone, deny=ADD_REACTIONS))
        for role in roles.managed:                  # aucun rôle ne rouvre l'écriture
            out[role] = _set(now(role), clear=VIEW_CHANNEL | WRITE | ADD_REACTIONS)
        return out
    out[roles.everyone] = _set(now(roles.everyone), deny=VIEW_CHANNEL)
    allowed = roles.allowed(audience)
    for role in roles.managed:
        out[role] = (_set(now(role), allow=VIEW_CHANNEL) if role in allowed
                     else _set(now(role), clear=VIEW_CHANNEL))
    return out


def is_private(current: dict[int, Overwrite], roles: Roles) -> bool:
    """Ni @everyone ni les rôles du parcours ne voient ce salon : un salon
    d'équipe, que le plan laisse tel quel."""
    if not current.get(roles.everyone, EMPTY)[1] & VIEW_CHANNEL:
        return False
    return not any(current.get(role, EMPTY)[0] & VIEW_CHANNEL for role in roles.managed)


def _who(seen: list[int], roles: Roles) -> str:
    parts = []
    configured = [r for r in RANK_ORDER if r in roles.ranks]
    held = [r for r in configured if roles.ranks[r] in seen]
    if held:
        start = configured.index(held[0])
        if held == configured[start:] and len(held) > 1:
            parts.append(f"Rang {held[0]} et plus")
        else:
            parts.append(", ".join(f"Rang {r}" for r in held))
    if roles.adventurer and roles.adventurer in seen:
        parts.append("aventuriers")
    return " + ".join(parts) or "personne"


def visibility(overwrites: dict[int, Overwrite], roles: Roles) -> str:
    """Qui voit le salon, en clair (pour l'aperçu)."""
    everyone = overwrites.get(roles.everyone, EMPTY)
    if not everyone[1] & VIEW_CHANNEL:
        text = "tout le monde"
    else:
        seen = [role for role in roles.managed if overwrites.get(role, EMPTY)[0] & VIEW_CHANNEL]
        others = any(allowed & VIEW_CHANNEL for target, (allowed, _) in overwrites.items()
                     if target != roles.everyone and target not in roles.managed)
        text = _who(seen, roles) + (" + d'autres rôles" if others else "")
    return text + (", lecture seule" if everyone[1] & SEND_MESSAGES else "")


@dataclass(frozen=True)
class Change:
    """Ce qui change dans un salon."""

    channel_id: int
    name: str
    kind: str                                  # "text", "voice" ou "category"
    audience: Audience
    before: str                                # qui le voyait
    after: str                                 # qui le verra
    #: (cible, nouvelles permissions) ; (0, 0) = permissions retirées.
    updates: tuple[tuple[int, Overwrite], ...]

    @property
    def title(self) -> str:
        return {"category": "📁 ", "voice": "🔊 "}.get(self.kind, "#") + self.name

    @property
    def line(self) -> str:
        if self.before == self.after:
            return f"{self.title} : {self.after} (réglage complété)"
        return f"{self.title} : {self.before} → **{self.after}**"


def plan_channel(channel_id: int, name: str, kind: str, current: dict[int, Overwrite],
                 audience: Audience, roles: Roles) -> Change | None:
    """Le changement d'un salon, ou None s'il est déjà comme il faut."""
    after = wanted(audience, roles, current)
    updates = [(target, overwrite) for target, overwrite in after.items()
               if overwrite != current.get(target, EMPTY)]
    if not updates:
        return None
    # Ce qui ouvre d'abord, @everyone en dernier : personne ne perd l'accès en route.
    updates.sort(key=lambda u: (u[0] == roles.everyone, not u[1][0] & VIEW_CHANNEL))
    return Change(channel_id, name, kind, audience, visibility(current, roles),
                  visibility({**current, **after}, roles), tuple(updates))


@dataclass
class Plan:
    changes: list[Change] = field(default_factory=list)
    #: Salons d'équipe laissés tels quels.
    private: list[str] = field(default_factory=list)


def roles_to_add(accepted: bool, adventurer: bool, has_rank: bool, has_adventurer: bool) -> tuple[bool, bool]:
    """(rang à donner, Aventurier à donner) — on n'en retire jamais."""
    return accepted and not has_rank, accepted and adventurer and not has_adventurer
