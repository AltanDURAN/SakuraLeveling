"""Puissance d'une PIÈCE d'équipement, isolément.

Un item ne porte pas des stats absolues mais des **deltas** (`+12 atk`), et le
power score du jeu n'est pas linéaire (offensive × PV effectifs). On ne peut
donc pas lui appliquer directement `PowerScoreService.calculate_from_stats`.

On mesure à la place la puissance **marginale** : ce que l'objet apporte à un
joueur de base. C'est la seule lecture qui reste cohérente avec le combat —
+10 DEF vaut beaucoup plus que +10 PV, et la formule le sait déjà.

Sert à fixer le prix du travail des artisans et le palier de maîtrise requis :
plus une pièce est puissante, plus elle coûte cher et prend du temps.

⚠️ Limite connue : la mesure se fait contre un joueur de BASE, qui a peu
d'attaque et de PV. Les stats qui MULTIPLIENT (esquive, dégâts critiques) y
sont donc sous-évaluées par rapport à ce qu'elles valent sur un personnage
équipé. Une pièce qui ne donnerait QUE de l'esquive et du crit ressortira
bon marché chez l'artisan — à surveiller si tu crées ce genre d'objet.
"""

from __future__ import annotations

from app.domain.services.power_score_service import PowerScoreService
from app.domain.value_objects.stats import Stats

# Stats de base V2 d'un joueur (constantes, cf. StatsService — aucune stat
# n'est gagnée au level-up). Le référentiel de comparaison.
BASE_STATS = Stats(
    max_hp=100,
    attack=10,
    defense=5,
    speed=5,
    crit_chance=5,
    crit_damage=150,
    dodge=0,
    hp_regeneration=5,
    mana_max=100,
    mana_regeneration=5,
)

_STAT_KEYS = (
    "max_hp", "attack", "defense", "speed",
    "crit_chance", "crit_damage", "dodge", "hp_regeneration",
    "mana_max", "mana_regeneration",
)


class ItemPowerService:
    def __init__(self, power_service: PowerScoreService | None = None) -> None:
        self._power = power_service or PowerScoreService()

    def marginal_power(self, stat_bonuses: dict | None) -> int:
        """Puissance apportée par l'objet à un joueur de base.

        Toujours ≥ 0 : une pièce à malus net (grand espadon, −5 def) ne peut
        pas coûter un prix négatif. Un objet sans stat vaut 0.
        """
        if not stat_bonuses:
            return 0

        base_score = self._power.calculate_from_stats(BASE_STATS)
        with_item = self._power.calculate_from_stats(
            self._apply(BASE_STATS, stat_bonuses)
        )
        return max(0, with_item - base_score)

    @staticmethod
    def _apply(stats: Stats, bonuses: dict) -> Stats:
        """Applique les deltas de l'objet. Reporte TOUTES les stats — dont le
        mana (invariant : aucune reconstruction de Stats ne doit l'oublier)."""
        values = {key: getattr(stats, key) for key in _STAT_KEYS}
        for key in _STAT_KEYS:
            raw = bonuses.get(key, 0)
            try:
                values[key] += float(raw)
            except (TypeError, ValueError):
                continue

        # Mêmes planchers que le calcul de stats final.
        values["max_hp"] = max(1, values["max_hp"])
        values["attack"] = max(1, values["attack"])
        values["defense"] = max(1, values["defense"])
        values["speed"] = max(1, values["speed"])
        values["crit_chance"] = max(0, values["crit_chance"])
        values["crit_damage"] = max(100, values["crit_damage"])
        # L'esquive est bornée à 99 : à 100 la survie deviendrait infinie et
        # la puissance exploserait.
        values["dodge"] = min(99, max(0, values["dodge"]))
        values["hp_regeneration"] = max(0, values["hp_regeneration"])
        values["mana_max"] = max(0, values["mana_max"])
        values["mana_regeneration"] = max(0, values["mana_regeneration"])

        return Stats(**{k: int(v) if k not in ("crit_chance", "crit_damage", "dodge")
                        else v for k, v in values.items()})
