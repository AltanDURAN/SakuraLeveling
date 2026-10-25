"""LA formule de dégâts — une seule pour TOUS les combats (saison 1, oct. 2026).

    dégâts     = ATK − DEF, mais jamais moins de 25 % de l'ATK
    contrecoup = DEF − 75 % de l'ATK, quand c'est positif

La défense absorbe au plus 75 % d'un coup. Ce qu'elle a EN TROP au-delà de ce
plafond ne se perd pas : il revient à l'attaquant en CONTRECOUP. Décidé avec
l'auteur (25/10/2026) :

  • avant, `max(1, ATK − DEF)` : en saison 1 un build équilibré a ATK ≈ DEF,
    les coups tombaient au plancher de 1 dégât (duels JcJ — depuis retirés —
    bloqués au tour max, tank incapable de tuer, monstres blindés
    increvables) ;
  • tant que la DEF reste sous 75 % de l'ATK, la formule donne EXACTEMENT
    l'ancien résultat : le calibrage des monstres n'a pas bougé ;
  • le contrecoup n'est PAS une action : il ne compte pas comme un tour, ne
    déclenche aucun effet (riposte, vol de vie, fureur…) et ne provoque pas
    de contrecoup en retour — il est toujours inférieur à l'attaque, pas de
    boucle. Il ignore les boucliers et la défense de l'attaquant.

Le crit s'applique AVANT (`attack` est l'attaque critée du coup) : il perce
l'armure et réduit d'autant le contrecoup.
"""

from __future__ import annotations

#: Part minimale d'un coup qui traverse la défense (la défense en absorbe au
#: plus 75 %).
ARMOR_FLOOR = 0.25

#: Passif d'équipement Épines : contrecoup augmenté de 10 %.
THORNS_RECOIL_BONUS = 0.10


def resolve_hit(attack: float, defense: float) -> tuple[int, int]:
    """(dégâts infligés au défenseur, contrecoup renvoyé à l'attaquant)."""
    attack = max(0.0, float(attack))
    defense = max(0.0, float(defense))
    damage = max(1, round(max(attack - defense, attack * ARMOR_FLOOR)))
    recoil = max(0, round(defense - attack * (1 - ARMOR_FLOOR)))
    return damage, recoil


def thorns_recoil(recoil: int, has_thorns: bool) -> int:
    """Contrecoup après le passif Épines du défenseur."""
    if recoil <= 0 or not has_thorns:
        return recoil
    return round(recoil * (1 + THORNS_RECOIL_BONUS))
