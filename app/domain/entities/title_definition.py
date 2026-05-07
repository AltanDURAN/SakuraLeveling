"""Définition statique d'un titre (chargée depuis le JSON content).

Un titre se débloque par une condition (kills_family, kills_total, etc.)
et confère un effet passif (bonus damage vs famille, reduction damage from
famille, etc.). Le code est l'identifiant stable utilisé en DB et dans
l'autocomplete.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TitleDefinition:
    code: str
    name: str
    description: str
    icon: str  # emoji affiché dans /profile

    # Condition de débloquage. Les types supportés :
    #   "kills_family"  : target=family (ex "slime"), value=count requis
    #   "kills_total"   : value=count requis (toutes familles confondues)
    #   "kills_mob"     : target=mob_code, value=count requis
    #   "dodges_total"  : value=count d'esquives requis (encounters)
    #   "daily_streak"  : value=streak quotidien requis
    #   "duel_top1"     : exclusif — détenu par le rang 1 du ladder 1v1
    #   "kills_record"  : exclusif — détenu par le record absolu de kills
    condition_type: str
    condition_target: str = ""
    condition_value: int = 0

    # Titres exclusifs : 1 seul détenteur à la fois. Le retrait se fait
    # automatiquement quand un autre joueur prend la place (cf.
    # ExclusiveTitleService).
    exclusive: bool = False

    # Effets passifs (appliqués automatiquement dès le titre débloqué).
    # Format : `effects` = liste de dict {type, target, value}.
    # Types :
    #   "damage_bonus_vs_family"      : target=family, value=pct (ex 10 = +10%)
    #   "damage_reduction_from_family": target=family, value=pct
    #   "champion_all_stats"          : value=pct, applique +X% multiplicatif
    #       sur max_hp/attack/defense (ceil), +X flat sur speed/regeneration,
    #       +X additif sur crit_chance/crit_damage/dodge.
    #   "gold_xp_bonus_pct"           : value=pct, +X% sur gold/xp gagnés
    #       en combat (s'applique uniquement au détenteur du titre).
    effects: list[dict] = field(default_factory=list)
