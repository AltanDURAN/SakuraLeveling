"""Quêtes ADAPTÉES à chaque joueur (25/10/2026, demande de l'auteur).

Avant, une quête était fixe : « Tuer 5 slimes », « Gagner 500 or »,
« Infliger 1 000 dégâts ». À haut niveau elles se faisaient en un coup ; au
niveau 1, « 500 or » demandait ~170 victoires ; et toutes visaient la zone F.

Désormais `daily_quests.json` / `weekly_quests.json` décrivent des MODÈLES ;
au tirage, chaque modèle devient une quête CONCRÈTE pour CE joueur :

  • la cible suit sa ZONE : « Vaincre 6 morts-vivants » pour un joueur du
    cimetière, des démons pour un joueur du berceau (famille accessible à son
    rang, la plus avancée pour son niveau, assez présente dans sa zone) ;
  • la quantité suit son NIVEAU : XP, or, dégâts à infliger ou à encaisser
    sont exprimés en « victoires à son niveau » (`scale`), convertis avec les
    mêmes repères que le calibrage des monstres (joueur de référence) ;
  • le RÔLE compte : dégâts pour un DPS, dégâts encaissés pour un tank, défi
    Soutien pour un soigneur (champ `roles`, déduit de ses classes) ;
  • une quête QUOTIDIENNE se fait seul en une journée : ~6 victoires à son
    niveau au plus, rien qui exige un groupe (ça, c'est pour l'hebdo).

Les récompenses restent celles du modèle, indexées sur le niveau
(`quest_reward_service`).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from app.domain.services.reference_player import reference_stats

#: XP et or d'une victoire contre un monstre de son niveau (cf. restat_mobs).
XP_PER_KILL_PER_LEVEL = 6.25
GOLD_PER_KILL_PER_LEVEL = 3.0
#: Or réellement touché : le pool d'un monstre se partage en groupe.
GOLD_SHARE = 0.6
#: Coups qu'un joueur encaisse en moyenne par combat à son niveau.
HITS_TAKEN_PER_FIGHT = 8
#: Soins donnés aux alliés par combat de groupe, en part de ses PV max.
HEAL_PER_FIGHT_PCT = 0.25
#: Une famille n'est proposée que si elle pèse au moins cette part des
#: apparitions de sa zone (sinon « 6 slimes » demandait ~40 combats).
MIN_FAMILY_SHARE = 0.5

#: Libellés au pluriel des familles (repli : le code).
FAMILY_LABELS: dict[str, str] = {
    "slime": "slimes", "gobelin": "gobelins", "mort-vivant": "morts-vivants",
    "demoniaque": "démons", "primordial": "bêtes primordiales",
    "nocturne": "créatures nocturnes", "draconique": "dragons", "abyssal": "créatures du Néant",
}
ROLE_LABELS: dict[str, str] = {"dps": "DPS", "tank": "Tank", "soutien": "Soutien"}

#: Classes → rôles du joueur (spécialisation ou classe de base de la voie).
_ROLE_CLASSES: dict[str, frozenset[str]] = {
    "dps": frozenset({"assassin", "guerrier"}),
    "tank": frozenset({"rempart", "gardien"}),
    "soutien": frozenset({"soigneur", "clerc"}),
}


@dataclass(frozen=True)
class QuestTemplate:
    code: str
    name: str
    description: str               # « {n} » = quantité, « {cible} » = cible
    tier: str                      # easy | medium | hard
    objective_type: str            # kill_any, kill_family, xp_earned, …
    quantity: float                # nombre d'unités (victoires, objets…)
    scale: str = "count"           # count | xp | gold | damage | tanked | healed
    target: str = ""               # "" | "zone_family" | code de rôle (défi)
    roles: tuple[str, ...] = ()    # vide = tout le monde
    reward_gold: int = 0           # au niveau de référence des quêtes (20)
    reward_xp: int = 0
    reward_items: list = field(default_factory=list)


@dataclass(frozen=True)
class FamilyChoice:
    family: str
    min_level: int                 # niveau du plus faible de ses monstres
    share: float                   # part des apparitions de sa zone


@dataclass(frozen=True)
class QuestContext:
    level: int
    roles: frozenset[str]          # dps / tank / soutien ; vide = aucun rôle
    families: tuple[FamilyChoice, ...] = ()   # familles ACCESSIBLES au joueur


@dataclass(frozen=True)
class ConcreteQuest:
    code: str
    name: str
    description: str
    tier: str
    objective_type: str
    target: str
    quantity: int


def player_roles(classes) -> frozenset[str]:
    owned = set(classes or ())
    return frozenset(role for role, codes in _ROLE_CLASSES.items() if owned & codes)


def _nice(value: float) -> int:
    """Arrondi lisible : 2 chiffres significatifs (1 234 → 1 200)."""
    value = max(1.0, value)
    if value < 100:
        return int(round(value))
    digits = len(str(int(value))) - 2
    return int(round(value, -digits))


def scaled_quantity(scale: str, units: float, level: int) -> int:
    """Quantité concrète : `units` victoires à son niveau, converties."""
    level = max(1, int(level))
    if scale == "count":
        return max(1, int(round(units)))
    ref = reference_stats(level)
    per_unit = {
        "xp": XP_PER_KILL_PER_LEVEL * level,
        "gold": GOLD_PER_KILL_PER_LEVEL * level * GOLD_SHARE,
        "damage": 11 * ref.attack,                                       # PV d'un monstre
        "tanked": HITS_TAKEN_PER_FIGHT * (ref.defense + 0.025 * ref.max_hp),
        "healed": HEAL_PER_FIGHT_PCT * ref.max_hp,
    }.get(scale, 1.0)
    return _nice(units * per_unit)


def best_family(ctx: QuestContext) -> FamilyChoice | None:
    """La famille la plus avancée que le joueur peut affronter à son niveau
    (et assez présente dans sa zone pour une quête du jour)."""
    candidates = [f for f in ctx.families if f.share >= MIN_FAMILY_SHARE]
    if not candidates:
        return None
    reachable = [f for f in candidates if f.min_level <= ctx.level + 3]
    pool = reachable or candidates
    return max(pool, key=lambda f: f.min_level) if reachable else min(pool, key=lambda f: f.min_level)


def eligible(template: QuestTemplate, ctx: QuestContext) -> bool:
    # Un joueur sans classe de rôle est « general » (débutant, généraliste pur).
    roles = set(ctx.roles) or {"general"}
    if template.roles and not (set(template.roles) & roles):
        return False
    if template.target == "zone_family" and best_family(ctx) is None:
        return False
    return True


def concretize(template: QuestTemplate, ctx: QuestContext) -> ConcreteQuest:
    target, label = template.target, ""
    if template.target == "zone_family":
        family = best_family(ctx)
        target = family.family if family else ""
        label = FAMILY_LABELS.get(target, target)
    elif template.target in ROLE_LABELS:
        label = ROLE_LABELS[template.target]
    quantity = scaled_quantity(template.scale, template.quantity, ctx.level)
    n = f"{quantity:,}".replace(",", " ")
    return ConcreteQuest(
        code=template.code,
        name=template.name.replace("{cible}", label),
        description=template.description.replace("{n}", n).replace("{cible}", label),
        tier=template.tier,
        objective_type=template.objective_type,
        target=target,
        quantity=quantity,
    )


def pick(templates: list[QuestTemplate], ctx: QuestContext, count: int = 3,
         rng: random.Random | None = None) -> list[ConcreteQuest]:
    """`count` quêtes pour ce joueur : une par difficulté si possible, jamais
    deux fois le même objectif."""
    rng = rng or random.Random()
    pool = [t for t in templates if eligible(t, ctx)]
    chosen: list[QuestTemplate] = []
    for tier in ("easy", "medium", "hard"):
        bucket = [t for t in pool if t.tier == tier
                  and t.objective_type not in {c.objective_type for c in chosen}]
        if bucket and len(chosen) < count:
            chosen.append(rng.choice(bucket))
    rest = [t for t in pool if t not in chosen]
    rng.shuffle(rest)
    for t in rest:
        if len(chosen) >= count:
            break
        if t.objective_type not in {c.objective_type for c in chosen}:
            chosen.append(t)
    return [concretize(t, ctx) for t in chosen]
