from app.domain.entities.mob_definition import MobDefinition
from app.domain.value_objects.stats import Stats


# Paliers de rang fondés sur le power score. Pour chaque palier, le rang
# s'applique tant que le score est STRICTEMENT inférieur à la borne.
# Au-delà du dernier palier, on retombe sur le rang max "SSS+".
# Pattern : chaque lettre couvre 3 sous-rangs (-, base, +) à 2× / 5× / 10×
# de la base, puis on saute d'un facteur 20× pour la lettre suivante.
_RANK_THRESHOLDS: list[tuple[int, str]] = [
    (200, "F-"), (500, "F"), (1_000, "F+"),
    (2_000, "E-"), (5_000, "E"), (10_000, "E+"),
    (20_000, "D-"), (50_000, "D"), (100_000, "D+"),
    (200_000, "C-"), (500_000, "C"), (1_000_000, "C+"),
    (2_000_000, "B-"), (5_000_000, "B"), (10_000_000, "B+"),
    (20_000_000, "A-"), (50_000_000, "A"), (100_000_000, "A+"),
    (200_000_000, "S-"), (500_000_000, "S"), (1_000_000_000, "S+"),
    (2_000_000_000, "SS-"), (5_000_000_000, "SS"), (10_000_000_000, "SS+"),
    (20_000_000_000, "SSS-"), (50_000_000_000, "SSS"),
]
_RANK_MAX = "SSS+"


class PowerScoreService:
    def calculate_from_stats(self, stats: Stats) -> int:
        score = (
            (
                (
                    stats.max_hp
                    * (1 + stats.defense / 100)
                    * (1 / max(0.01, 1 - stats.dodge / 100))
                    * (1 + stats.hp_regeneration / max(1, stats.max_hp))
                )
                / 11.2875
            )
            / (
                105
                / max(
                    1,
                    stats.attack
                    * (1 + (stats.crit_chance * stats.crit_damage) / 10000)
                    * (1 + stats.speed / 100),
                )
            )
            * 10
        )

        return max(1, int(score))

    def calculate_from_mob(self, mob: MobDefinition) -> int:
        mob_stats = Stats(
            max_hp=mob.max_hp,
            attack=mob.attack,
            defense=mob.defense,
            crit_chance=mob.crit_chance,
            crit_damage=mob.crit_damage,
            dodge=mob.dodge,
            hp_regeneration=mob.hp_regeneration,
            speed=mob.speed,
        )
        return self.calculate_from_stats(mob_stats)

    def calculate_party_score(self, players_stats: list[Stats]) -> int:
        return sum(self.calculate_from_stats(stats) for stats in players_stats)

    def format_score(self, score: int) -> str:
        if score < 1_000:
            return str(score)

        if score < 1_000_000:
            return f"{score // 1_000}K"

        return f"{score // 1_000_000}M"

    def calculate_and_format_from_stats(self, stats: Stats) -> str:
        return self.format_score(self.calculate_from_stats(stats))

    def calculate_and_format_from_mob(self, mob: MobDefinition) -> str:
        return self.format_score(self.calculate_from_mob(mob))

    def calculate_and_format_party_score(self, players_stats: list[Stats]) -> str:
        return self.format_score(self.calculate_party_score(players_stats))

    def compute_rank(self, score: int) -> str:
        """Renvoie le rang correspondant à un power score (F- → SSS+).

        Itération linéaire — la liste fait <30 entrées, l'overhead est nul
        comparé à la lisibilité d'avoir le mapping en données pures.
        """
        for threshold, label in _RANK_THRESHOLDS:
            if score < threshold:
                return label
        return _RANK_MAX

    def compute_rank_from_stats(self, stats: Stats) -> str:
        return self.compute_rank(self.calculate_from_stats(stats))