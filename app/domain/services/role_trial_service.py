"""Épreuves de rôle quotidiennes (`/defi`) — elles REMPLACENT les duels JcJ.

Décidé avec l'auteur le 25/10/2026 (étape 2 de la refonte des rôles) :

  • trois épreuves, une par rôle, contre le MÊME adversaire pour tout le monde
    (celui d'un joueur de niveau `TRIAL_LEVEL`) : le score est BRUT, les plus
    forts sont en haut ;
      ⚔️ DPS     — le Mannequin ne riposte pas : dégâts infligés en 40 s
                   (`DPS_TICKS`, la vitesse compte) ;
      🛡️ Tank    — le Bourreau frappe fort et s'énerve (escalade) jusqu'à ton
                   K.O. : dégâts encaissés. PAS de sort de soin (sinon le
                   Soigneur, qui se soigne seul, gagnait l'épreuve tank) ;
      💚 Soutien — le Bourreau ne frappe qu'une RECRUE (escorte) ; l'épreuve
                   s'arrête quand elle tombe : PV soignés et boucliers donnés ;
  • une VARIANTE par rôle et par jour, tirée de la date : la même pour tous ;
  • essais illimités mais DÉTERMINISTES (`attempt_seed`) : un même build
    donne le même score toute la journée — réessayer n'a de sens qu'après
    avoir changé d'équipement, d'arbre, de points ou de tactique ;
  • on garde le MEILLEUR score du jour ; la semaine (lundi → dimanche) =
    somme des `BEST_DAYS` meilleurs jours, par rôle ;
  • classement GÉNÉRAL = moyenne des trois rôles, chacun ramené à 100 = le
    meilleur de la semaine (les scores bruts des rôles n'ont pas la même
    échelle : ~20 000 de dégâts contre ~5 000 de soins) ;
  • résultats le dimanche à `RESULTS_HOUR` h (Paris) : titres exclusifs de la
    semaine et or pour le podium (`REWARD_GOLD_PER_LEVEL` × niveau).

Mesuré avec les builds de rôle (`scripts/reference_roles.py`) : chaque
spécialiste gagne SON épreuve, dans chaque variante, aux niveaux 30 / 60 / 100
(`tests/content/test_role_trial_balance.py`).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.domain.entities.mob_definition import MobDefinition
from app.domain.services.reference_player import expected_speed, reference_stats
from app.domain.value_objects.stats import Stats

ROLES: tuple[str, ...] = ("dps", "tank", "soutien")
ROLE_LABELS: dict[str, str] = {"dps": "⚔️ DPS", "tank": "🛡️ Tank", "soutien": "💚 Soutien"}
GENERAL = "general"
GENERAL_LABEL = "🏆 Général"

#: Niveau de l'adversaire (et de la recrue), le même pour TOUS les joueurs.
TRIAL_LEVEL = 50
#: Durée de l'épreuve DPS en ticks de jauge (≈ 40 actions à 10 de vitesse).
DPS_TICKS = 400
#: PV de l'adversaire : il ne tombe jamais, c'est le temps ou ton K.O. qui
#: arrête l'épreuve.
OPPONENT_HP = 10 ** 9
#: Identifiant de la recrue dans le combat (jamais un vrai joueur).
RECRUIT_ID = 0

TRIAL_TZ = ZoneInfo("Europe/Paris")
RESULTS_WEEKDAY = 6          # dimanche
RESULTS_HOUR = 20
BEST_DAYS = 5
#: Or du podium de chaque classement, × niveau du joueur.
REWARD_GOLD_PER_LEVEL: tuple[int, ...] = (100, 60, 30)

#: Titres exclusifs de la semaine (cf. titles.json).
WEEKLY_TITLES: dict[str, str] = {
    "dps": "fleau_semaine",
    "tank": "bastion_semaine",
    "soutien": "ange_gardien_semaine",
    GENERAL: "champion_semaine",
}


@dataclass(frozen=True)
class TrialVariant:
    code: str
    role: str
    name: str
    description: str
    #: ATK de l'adversaire en × (DEF + 2,5 % des PV) du joueur de référence ;
    #: 0 = il ne frappe pas.
    attack_mult: float = 0.0
    #: DEF en × ATK du joueur de référence (0,45 = un monstre standard).
    defense_mult: float = 0.45
    speed_mult: float = 1.0
    dodge: int = 0
    crit_chance: int = 0
    crit_damage: int = 100
    abilities: dict = field(default_factory=dict)


VARIANTS: dict[str, tuple[TrialVariant, ...]] = {
    "dps": (
        TrialVariant("classique", "dps", "Le Mannequin",
                     "Il encaisse sans broncher : frappe le plus fort possible en 40 secondes."),
        TrialVariant("cuirasse", "dps", "Le Mannequin cuirassé",
                     "Défense très élevée : les critiques et la pénétration d'armure brillent.",
                     defense_mult=0.7),
        TrialVariant("insaisissable", "dps", "Le Mannequin insaisissable",
                     "Il esquive 25 % des coups : la vitesse et le volume de coups paient.",
                     dodge=25),
        TrialVariant("miroir", "dps", "Le Mannequin miroir",
                     "Il renvoie 15 % des dégâts reçus : un DPS trop fragile tombe avant la fin.",
                     abilities={"reflect": {"pct": 15}}),
    ),
    "tank": (
        TrialVariant("classique", "tank", "Le Bourreau",
                     "Il frappe fort et s'énerve jusqu'à ce que tu tombes : encaisse le plus possible.",
                     attack_mult=2.0),
        TrialVariant("rafale", "tank", "Le Bourreau en rafale",
                     "Trois coups plus légers par attaque : la défense amortit chacun d'eux.",
                     attack_mult=1.0, abilities={"multi_hit": {"hits": 3}}),
        TrialVariant("venin", "tank", "Le Bourreau venimeux",
                     "Ses coups empoisonnent (le poison ignore la défense) : les PV comptent.",
                     attack_mult=2.0, abilities={"poison": {"pct_max_hp": 3, "turns": 4}}),
        TrialVariant("critiques", "tank", "Le Bourreau impitoyable",
                     "30 % de coups critiques ×2 : l'esquive et les protections contre les critiques aident.",
                     attack_mult=1.5, crit_chance=30, crit_damage=200),
        TrialVariant("brise_armure", "tank", "Le Bourreau briseur",
                     "Chaque coup réduit ta défense de 10 % pour l'épreuve (jusqu'à 30 %).",
                     attack_mult=1.8, abilities={"armor_break": {"pct": 10, "max_pct": 30}}),
    ),
    "soutien": (
        TrialVariant("classique", "soutien", "La Recrue",
                     "Le Bourreau ne frappe que la recrue : garde-la en vie le plus longtemps possible.",
                     attack_mult=1.5),
        TrialVariant("saignement", "soutien", "La Recrue blessée",
                     "Ses coups font saigner la recrue : les soins doivent suivre le saignement.",
                     attack_mult=1.5, abilities={"bleed": {"pct": 10, "turns": 3, "max_stacks": 3}}),
        TrialVariant("rafale", "soutien", "La Recrue sous la rafale",
                     "Trois coups légers par attaque sur la recrue.",
                     attack_mult=0.8, abilities={"multi_hit": {"hits": 3}}),
        TrialVariant("coups_lourds", "soutien", "La Recrue face au colosse",
                     "Rares coups très lourds : soigne entre deux frappes.",
                     attack_mult=2.5, speed_mult=0.6),
        TrialVariant("venin", "soutien", "La Recrue empoisonnée",
                     "Ses coups empoisonnent la recrue (le poison ignore la défense).",
                     attack_mult=1.5, abilities={"poison": {"pct_max_hp": 3, "turns": 4}}),
    ),
}


def _digest(*parts) -> int:
    raw = ":".join(str(p) for p in parts).encode()
    return int(hashlib.sha256(raw).hexdigest(), 16)


# ------------------------------------------------------------ calendrier --
def trial_day(now: datetime) -> date:
    """Jour de l'épreuve (heure de Paris)."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(TRIAL_TZ).date()


def week_start(day: date) -> date:
    """Lundi de la semaine de `day`."""
    return day - timedelta(days=day.weekday())


def results_at(week: date) -> datetime:
    """Instant des résultats de la semaine qui commence le lundi `week`."""
    sunday = week + timedelta(days=RESULTS_WEEKDAY)
    return datetime(sunday.year, sunday.month, sunday.day, RESULTS_HOUR, tzinfo=TRIAL_TZ)


def is_closed(now: datetime) -> bool:
    """Dimanche après les résultats : plus d'essai jusqu'à minuit."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now >= results_at(week_start(trial_day(now)))


# ------------------------------------------------------------- variantes --
def variant_of_day(day: date, role: str) -> TrialVariant:
    """Variante du jour pour ce rôle — tirée de la date, la même pour tous."""
    pool = VARIANTS[role]
    return pool[_digest("defi", day.isoformat(), role) % len(pool)]


def attempt_seed(day: date, role: str, player_id: int) -> int:
    """Graine d'un essai : même joueur, même jour, même rôle ⇒ même tirage.
    Seul un changement de build change le score."""
    return _digest("essai", day.isoformat(), role, player_id) % (2 ** 63)


# ------------------------------------------------------------ adversaire --
def opponent(variant: TrialVariant, now: datetime | None = None) -> MobDefinition:
    """L'adversaire de la variante, calibré sur un joueur de niveau TRIAL_LEVEL."""
    ref = reference_stats(TRIAL_LEVEL)
    attack = round(variant.attack_mult * (ref.defense + 0.025 * ref.max_hp))
    # Le Mannequin (épreuve DPS) ne joue jamais : vitesse 0.
    speed = round(expected_speed(TRIAL_LEVEL) * variant.speed_mult) if attack > 0 else 0
    now = now or datetime.now(UTC)
    return MobDefinition(
        id=0, code=f"defi_{variant.role}_{variant.code}", name=variant.name,
        description=variant.description, image_name="", family="defi",
        max_hp=OPPONENT_HP, current_hp=OPPONENT_HP, attack=attack,
        defense=round(variant.defense_mult * ref.attack), xp_reward=0, gold_reward=0,
        spawn_weight=0, speed=speed, crit_chance=variant.crit_chance,
        crit_damage=variant.crit_damage, dodge=variant.dodge, hp_regeneration=0,
        loot_table=None, created_at=now, updated_at=now, element="",
    )


def recruit_stats() -> Stats:
    """La recrue de l'épreuve de soutien : un joueur de référence de TRIAL_LEVEL."""
    return reference_stats(TRIAL_LEVEL)


def score_of(role: str, contribution) -> int:
    """Score d'un essai à partir de la contribution du joueur."""
    if role == "dps":
        return int(contribution.damage_dealt)
    if role == "tank":
        return int(contribution.damage_tanked)
    return int(contribution.hp_healed)


# ------------------------------------------------------------- semaine --
def weekly_scores(rows) -> dict[str, dict[int, int]]:
    """rows : (player_id, role, day, score) des MEILLEURS scores du jour.
    → {rôle: {player_id: somme des BEST_DAYS meilleurs jours}}."""
    per: dict[str, dict[int, list[int]]] = {role: {} for role in ROLES}
    for player_id, role, _day, score in rows:
        if role in per:
            per[role].setdefault(player_id, []).append(int(score))
    return {
        role: {pid: sum(sorted(scores, reverse=True)[:BEST_DAYS])
               for pid, scores in players.items()}
        for role, players in per.items()
    }


def general_scores(weekly: dict[str, dict[int, int]]) -> dict[int, float]:
    """Moyenne des trois rôles, chacun ramené à 100 = le meilleur de la
    semaine. Un rôle non joué compte 0."""
    players = {pid for scores in weekly.values() for pid in scores}
    out: dict[int, float] = {}
    for pid in players:
        total = 0.0
        for role in ROLES:
            scores = weekly.get(role, {})
            best = max(scores.values(), default=0)
            if best > 0:
                total += 100.0 * scores.get(pid, 0) / best
        out[pid] = round(total / len(ROLES), 1)
    return out


def ranking(scores: dict[int, float]) -> list[tuple[int, float]]:
    """(player_id, score) du meilleur au moins bon ; à égalité, le plus petit
    identifiant (le plus ancien joueur) passe devant — déterministe."""
    return sorted(((pid, s) for pid, s in scores.items() if s > 0), key=lambda x: (-x[1], x[0]))


def reward_gold(place: int, level: int) -> int:
    """Or du podium : place 0 = premier."""
    if place >= len(REWARD_GOLD_PER_LEVEL):
        return 0
    return REWARD_GOLD_PER_LEVEL[place] * max(1, int(level))


# ------------------------------------------------------------- un essai --
@dataclass(frozen=True)
class TrialRun:
    score: int
    actions: int
    survived: bool          # le joueur (DPS, tank) ou la recrue (soutien) tient encore
    result: object          # PartyBattleResult


def run_trial(role: str, variant: TrialVariant, *, player_id: int, name: str,
              stats: Stats, passives=None, tactic: str | None = None,
              seed: int | None = None) -> TrialRun:
    """Joue UN essai avec le vrai moteur. `seed` rend l'essai déterministe ;
    l'état du hasard global est rétabli ensuite (le bot ne bloque pas)."""
    import random
    from dataclasses import replace

    from app.domain.services.combat_passives import NO_PASSIVES
    from app.domain.services.party_combat_service import PartyCombatService

    passives = passives or NO_PASSIVES
    if role == "tank":
        passives = replace(passives, healer=False)   # on mesure ce qu'on encaisse

    def member(pid, member_name, st):
        return {"player_id": pid, "user_id": pid, "name": member_name, "avatar_url": "",
                "stats": st, "current_hp": st.max_hp, "max_hp": st.max_hp,
                "current_mana": st.mana_max, "mana_max": st.mana_max}

    party = [member(player_id, name, stats)]
    kwargs: dict = {}
    if role == "dps":
        kwargs["max_ticks"] = DPS_TICKS
    if role == "soutien":
        party.append(member(RECRUIT_ID, "la recrue", recruit_stats()))
        kwargs["escort_ids"] = {RECRUIT_ID}

    state = random.getstate()
    if seed is not None:
        random.seed(seed)
    try:
        # Sans coût en mana : avec la réserve, le soigneur la vidait avant la
        # fin et son score ne mesurait plus que sa taille — identique dans les
        # cinq variantes du défi soutien (mesuré le 25/10/2026). Un défi
        # compare les rôles ; la gestion du mana se joue sur le terrain.
        result = PartyCombatService().fight_party_vs_mob(
            party, opponent(variant), mob_abilities=dict(variant.abilities),
            passives_by_player={player_id: passives},
            tactics_by_player={player_id: tactic} if tactic else {},
            mana_costs={},
            **kwargs,
        )
    finally:
        random.setstate(state)
    mine = next(c for c in result.contributions if c.player_id == player_id)
    watched = RECRUIT_ID if role == "soutien" else player_id
    survived = next(c for c in result.contributions if c.player_id == watched).survived
    return TrialRun(score_of(role, mine), result.turns, survived, result)
