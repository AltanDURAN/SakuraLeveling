"""Records du serveur (salon des records, `/records`) — règles pures.

07/11/2026, idée de l'auteur : des records BATTABLES dans plusieurs domaines,
publiés chaque nuit à minuit ; trois titres tournants récompensent ceux qui en
détiennent le plus (+5 / +3 / +1 % d'or en combat de zone).

Règles validées avec l'auteur :
  • battre un record = faire STRICTEMENT mieux ; à égalité, le premier arrivé
    le garde ;
  • chasse par FAMILLE (par monstre, 43 records noieraient les autres) ;
  • exploits en combat de zone seulement, hors événements lunaires (une lune
    de sang triple la force des monstres : record imbattable des mois),
    élixirs compris ; comptes admin exclus de tous les records ;
  • un coup encaissé ne compte que si l'on reste debout, un soin ne compte
    que les PV vraiment rendus à un allié ;
  • titres : le plus de records détenus ; à égalité, celui dont le record le
    plus récent est le plus récent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RecordDef:
    code: str
    category: str
    emoji: str
    label: str
    unit: str = ""
    #: Cumulatif (chasse, boss) : il grossit tous les jours ; seule une
    #: passation est une nouvelle, pas chaque progrès du détenteur.
    cumulative: bool = False


#: (code, titre affiché) dans l'ordre du tableau.
CATEGORIES = (
    ("exploits", "⚔️ Exploits en combat de zone"),
    ("defis", "🎯 Défis de rôle"),
    ("tour", "🗼 Tour solo"),
    ("boss", "👑 World boss"),
    ("chasse", "🐾 Chasse"),
    ("collection", "🎴 Collection"),
)

EXPLOITS = (
    RecordDef("coup", "exploits", "💥", "Plus gros coup", "dégâts"),
    RecordDef("coup_encaisse", "exploits", "🛡️", "Plus gros coup encaissé sans tomber", "dégâts"),
    RecordDef("soin", "exploits", "💚", "Plus gros soin", "PV"),
    RecordDef("degats_combat", "exploits", "⚔️", "Plus de dégâts en un combat", "dégâts"),
    RecordDef("encaisse_combat", "exploits", "🧱", "Plus de dégâts encaissés en un combat", "dégâts"),
    RecordDef("soins_combat", "exploits", "🌿", "Plus de soins en un combat", "PV"),
)
DEFIS = (
    RecordDef("defi_dps", "defis", "⚔️", "Meilleur score au défi DPS", "points"),
    RecordDef("defi_tank", "defis", "🛡️", "Meilleur score au défi Tank", "points"),
    RecordDef("defi_soutien", "defis", "💚", "Meilleur score au défi Soutien", "points"),
)
#: Rôle du défi (table `role_trial_scores`) → record.
DEFI_ROLES = {"dps": "defi_dps", "tank": "defi_tank", "soutien": "defi_soutien"}
TOWER = RecordDef("tour", "tour", "🗼", "Plus haut étage", "étage")
BOSS = RecordDef("boss", "boss", "👑", "Plus de dégâts sur un boss en une semaine", "dégâts", cumulative=True)
#: Cartes à collectionner : le plus de cartes DIFFÉRENTES (09/11/2026).
ALBUM = RecordDef("album", "collection", "🎴", "Album le plus complet", "cartes", cumulative=True)

#: Titres tournants, du 1er au 3e (leur effet est dans `titles.json`).
TITLE_CODES = ("records_1", "records_2", "records_3")


def hunt_record(family: str, plural: str) -> RecordDef:
    """« Chasse aux démons » : le plus de monstres tués de la famille."""
    return RecordDef(f"chasse_{family}", "chasse", "🐾", f"Chasse aux {plural}", "", cumulative=True)


def all_records(families: list[tuple[str, str]]) -> list[RecordDef]:
    """Tous les records, dans l'ordre du tableau. `families` : (code, nom)
    des familles des zones OUVERTES."""
    return [*EXPLOITS, *DEFIS, TOWER, BOSS, *(hunt_record(code, label) for code, label in families), ALBUM]


@dataclass(frozen=True)
class Entry:
    """La meilleure valeur d'un joueur pour un record, et quand il l'a atteinte."""
    player_id: int
    value: int
    at: datetime
    detail: str = ""


def holder(entries: list[Entry]) -> Entry | None:
    """Le meilleur, strictement ; à égalité, le premier arrivé."""
    scored = [e for e in entries if e.value > 0]
    if not scored:
        return None
    return min(scored, key=lambda e: (-e.value, e.at, e.player_id))


def holdings(entries_by_code: dict[str, list[Entry]]) -> dict[str, Entry]:
    """Le détenteur de chaque record (les records sans valeur sont absents)."""
    found = {}
    for code, entries in entries_by_code.items():
        best = holder(entries)
        if best is not None:
            found[code] = best
    return found


@dataclass(frozen=True)
class Standing:
    player_id: int
    count: int
    latest: datetime


def ranking(held: dict[str, Entry]) -> list[Standing]:
    """Les détenteurs, du plus de records au moins ; à égalité, celui dont le
    record le plus récent est le plus récent passe devant."""
    counts: dict[int, int] = {}
    latest: dict[int, datetime] = {}
    for entry in held.values():
        counts[entry.player_id] = counts.get(entry.player_id, 0) + 1
        if entry.player_id not in latest or entry.at > latest[entry.player_id]:
            latest[entry.player_id] = entry.at
    standings = [Standing(pid, counts[pid], latest[pid]) for pid in counts]
    return sorted(standings, key=lambda s: (-s.count, -s.latest.timestamp(), s.player_id))


def title_awards(standings: list[Standing]) -> dict[str, int | None]:
    """Titre → détenteur (None : personne, faute de détenteurs)."""
    return {code: (standings[i].player_id if i < len(standings) else None)
            for i, code in enumerate(TITLE_CODES)}


@dataclass(frozen=True)
class Change:
    record: RecordDef
    new: Entry
    old: Entry | None

    @property
    def taken(self) -> bool:
        """Le record change de main (sinon : le détenteur améliore le sien)."""
        return self.old is None or self.old.player_id != self.new.player_id


def changes(records: list[RecordDef], before: dict[str, Entry], after: dict[str, Entry]) -> list[Change]:
    """Ce qui a bougé depuis la nuit dernière : records pris, et records
    améliorés par leur détenteur (sauf les cumulatifs, qui grossissent tous
    les jours)."""
    out = []
    for record in records:
        new, old = after.get(record.code), before.get(record.code)
        if new is None:
            continue
        if old is None or old.player_id != new.player_id:
            out.append(Change(record, new, old))
        elif new.value > old.value and not record.cumulative:
            out.append(Change(record, new, old))
    return out


# ---------------------------------------------------------------- un combat

def _player(ref) -> int | None:
    """« p12 » → 12 (les ennemis sont « e<n> »)."""
    if isinstance(ref, str) and ref.startswith("p") and ref[1:].isdigit():
        return int(ref[1:])
    return None


def fight_peaks(turn_logs, contributions) -> dict[int, dict[str, int]]:
    """Les exploits d'un combat, par joueur : plus gros coup donné, plus gros
    coup reçu sans tomber, plus gros soin donné à un allié, et les totaux du
    combat. Lu dans les événements du moteur (`PartyBattleTurnLog.events`)."""
    peaks: dict[int, dict[str, int]] = {}

    def keep(player_id: int | None, code: str, value: int) -> None:
        if player_id is None or value <= 0:
            return
        mine = peaks.setdefault(player_id, {})
        mine[code] = max(mine.get(code, 0), int(value))

    for log in turn_logs or ():
        events = getattr(log, "events", None) or []
        fallen = {_player(e.get("target")) for e in events if e.get("kind") == "ko"}
        for event in events:
            kind, amount = event.get("kind"), int(event.get("amount", 0) or 0)
            source, target = event.get("source"), event.get("target")
            if kind in ("hit", "crit"):
                hitter, victim = _player(source), _player(target)
                if hitter is not None and isinstance(target, str) and target.startswith("e"):
                    keep(hitter, "coup", amount)
                elif (victim is not None and _player(source) is None and victim not in fallen
                      and event.get("style") != "reflect"):
                    keep(victim, "coup_encaisse", amount)
            elif kind == "heal":
                healer, patient = _player(source), _player(target)
                if healer is not None and patient is not None and healer != patient:
                    keep(healer, "soin", amount)
    for c in contributions or ():
        keep(c.player_id, "degats_combat", c.damage_dealt)
        keep(c.player_id, "encaisse_combat", c.damage_tanked)
        keep(c.player_id, "soins_combat", c.hp_healed)
    return peaks
