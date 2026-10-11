"""Progression du joueur : courbe d'XP, niveaux, points gagnés.

SAISON 1 (octobre 2026) — refonte complète.

Avant : `xp_requise = 100 × niveau` (LINÉAIRE), et comme un mob donne
`6.25 × niveau` d'XP, il fallait **16 kills par niveau, du début à la fin**.
Un vétéran et un débutant progressaient exactement au même rythme, donc l'écart
entre eux ne se refermait JAMAIS.

Maintenant la courbe est **quadratique** : le nombre de kills par niveau monte
avec le niveau. Deux conséquences voulues :

  • le haut niveau coûte cher, donc un nouveau joueur gagne des niveaux
    beaucoup plus vite qu'un ancien et **rattrape l'écart en NIVEAUX** ;
  • l'ancien garde malgré tout son avance, parce qu'elle correspond à du
    **TEMPS réellement investi** qu'il faudra bien rattraper en kills.

Calibrage (cf. `scripts/calibrate_progression.py`) :

    kills(niveau) = 8 + 0.547 × niveau

    niveau   1 →   9 kills        niveau  50 →  35 kills
    niveau  10 →  13 kills        niveau  75 →  49 kills
    niveau  25 →  22 kills        niveau  99 →  62 kills

    ≈ 3 500 kills pour atteindre le niveau 100.

⚠️ Le plancher de 8 kills est VOULU : les premiers niveaux ne doivent pas
tomber tout seuls. Un joueur met une dizaine de jours à atteindre le niveau 10
— la galère du début fait partie de l'expérience.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Niveau maximum de la saison. Au-delà, l'XP n'est plus accumulée.
LEVEL_CAP = 100

#: Kills nécessaires au tout premier niveau — plancher anti « niveau gratuit ».
KILLS_FLOOR = 8.0
#: Croissance du nombre de kills par niveau.
KILLS_PER_LEVEL_COEF = 0.547
#: XP que rend un mob calibré au palier du joueur (`restat_mobs`).
XP_PER_KILL_COEF = 6.25

#: Points gagnés à chaque niveau.
STAT_POINTS_PER_LEVEL = 1
SKILL_POINTS_PER_LEVEL = 1


@dataclass(frozen=True)
class LevelUpResult:
    """Résultat d'un gain d'XP.

    Dataclass plutôt qu'un tuple : la montée de niveau donne désormais DEUX
    monnaies distinctes (points de stats pour les stats de base, points de
    compétence pour l'arbre), et il y en aura peut-être d'autres.
    """

    level: int
    xp: int
    skill_points: int
    stat_points: int
    levels_gained: int = 0

    @property
    def leveled_up(self) -> bool:
        return self.levels_gained > 0


class ProgressionService:
    def xp_required_for_next_level(self, level: int) -> int:
        """XP à accumuler pour passer de `level` à `level + 1`.

        Dérivée du nombre de kills visé : `xp = xp_par_kill × kills_visés`.
        Exprimer la courbe en KILLS plutôt qu'en XP brute est délibéré — c'est
        la seule unité que le joueur ressent, et la seule qu'on puisse
        équilibrer honnêtement.
        """
        if level >= LEVEL_CAP:
            return 0
        level = max(1, level)
        return round(XP_PER_KILL_COEF * level * self.kills_for_level(level))

    def kills_for_level(self, level: int) -> float:
        """Nombre de mobs de son palier à tuer pour passer ce niveau."""
        return KILLS_FLOOR + KILLS_PER_LEVEL_COEF * max(1, level)

    def total_xp_to_reach(self, level: int) -> int:
        """XP cumulée depuis le niveau 1 — sert aux simulations et à l'admin."""
        return sum(
            self.xp_required_for_next_level(lvl)
            for lvl in range(1, max(1, min(level, LEVEL_CAP)))
        )

    def apply_level_up(
        self,
        current_level: int,
        current_xp: int,
        gained_xp: int,
        current_skill_points: int,
        current_stat_points: int = 0,
    ) -> LevelUpResult:
        """Applique un gain d'XP et renvoie le nouvel état complet.

        Au niveau maximum, l'XP excédentaire est **ignorée** (pas accumulée) :
        une barre qui se remplit sans jamais rien donner est plus frustrante
        qu'un palier assumé.
        """
        level = current_level
        xp = current_xp + max(0, gained_xp)
        skill_points = current_skill_points
        stat_points = current_stat_points
        gained_levels = 0

        while level < LEVEL_CAP:
            required = self.xp_required_for_next_level(level)
            if required <= 0 or xp < required:
                break
            xp -= required
            level += 1
            gained_levels += 1
            skill_points += SKILL_POINTS_PER_LEVEL
            stat_points += STAT_POINTS_PER_LEVEL

        if level >= LEVEL_CAP:
            xp = 0

        return LevelUpResult(
            level=level,
            xp=xp,
            skill_points=skill_points,
            stat_points=stat_points,
            levels_gained=gained_levels,
        )
