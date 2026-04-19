from app.domain.entities.mob_definition import MobDefinition
from app.domain.value_objects.stats import Stats


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