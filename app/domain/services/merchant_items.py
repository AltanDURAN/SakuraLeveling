"""Les outils de Sorn, le marchand (26/10/2026, décision de l'auteur).

Sorn ne vend plus de potions (c'est Elna) : il vend des OUTILS — du confort et
des raccourcis de temps, jamais de puissance — et des cosmétiques. Effets
(`stat_bonuses["effect"]` de l'objet, utilisés par `/utiliser`) :

  • `summon_elite` (Cor de chasse, un par ZONE, `rank`) : fait apparaître
    l'élite de la zone dans son salon, après le combat en cours. Il faut avoir
    accès à la zone ; `HORN_COOLDOWN` entre deux cors, une seule élite
    invoquée par zone à la fois. Prix ≈ 3 × l'or de l'élite : il change de l'or
    en XP et en combat de groupe, jamais rentable en or ;
  • `trial_retry` (Sceau du second souffle, un par RANG) : efface l'attente
    après un échec à l'épreuve de CE rang ;
  • `respec_stats` (Parchemin d'oubli) : reprend tous les points de stats ;
  • `reset_tree` (Jeton) : un reset d'arbre EN PLUS du gratuit de la semaine ;
  • `daily_guard` (Sablier de fidélité) : passif, le premier jour de /daily
    manqué ne divise pas la série.

Prix : FIXES et identiques pour tous, ou par rang/zone (cor, sceau) ; le
parchemin et le jeton suivent le niveau (ils rapportent plus à haut niveau),
avec un seul exemplaire à la fois (`shop_items.price_per_level` / `max_owned`).
"""

from __future__ import annotations

from datetime import timedelta

EFFECT_SUMMON_ELITE = "summon_elite"
EFFECT_TRIAL_RETRY = "trial_retry"
EFFECT_RESPEC = "respec_stats"
EFFECT_RESET_TREE = "reset_tree"
EFFECT_DAILY_GUARD = "daily_guard"
TOOL_EFFECTS = frozenset({EFFECT_SUMMON_ELITE, EFFECT_TRIAL_RETRY, EFFECT_RESPEC,
                          EFFECT_RESET_TREE, EFFECT_DAILY_GUARD})

#: Attente entre deux cors de chasse (par joueur).
HORN_ACTION_KEY = "hunting_horn"
HORN_COOLDOWN = timedelta(hours=1)

#: Le sablier : code de l'objet consommé par /daily.
DAILY_GUARD_ITEM = "sablier_fidelite"

RANK_ORDER: tuple[str, ...] = ("F", "E", "D", "C", "B", "A", "S", "SS", "SSS")


def rank_index(rank: str | None) -> int:
    return RANK_ORDER.index(rank) if rank in RANK_ORDER else 0


def next_rank(rank: str | None) -> str | None:
    index = rank_index(rank)
    return RANK_ORDER[index + 1] if index + 1 < len(RANK_ORDER) else None


def missed_after_guard(missed: int, has_guard: bool) -> tuple[int, bool]:
    """(jours manqués comptés, sablier consommé ?) : le sablier efface UN
    jour manqué — la série n'est pas divisée pour ce jour-là."""
    if missed > 0 and has_guard:
        return missed - 1, True
    return missed, False
