from app.domain.entities.mob_definition import MobDefinition
from app.domain.value_objects.stats import Stats


# Paliers de rang fondés sur le power score. Pour chaque palier, le rang
# s'applique tant que le score est STRICTEMENT inférieur à la borne.
# Au-delà du dernier palier, on retombe sur le rang max "SSS+".
#
# Les bornes sont DÉRIVÉES de la courbe du joueur de référence (build
# équilibré sans équipement) : la borne d'un rang = le score du joueur de
# référence au début du palier suivant. Résultat : un joueur reste à son
# rang tout au long de son palier de niveau. Niveau ~100 = rang S (l'endgame
# "actuel"), et SS-/SSS+ couvrent le tail infini au-delà.
#
# Si on change la formule `calculate_from_stats` ou la courbe de référence,
# régénérer ces bornes (script : score de référence à chaque niveau-repère).
_RANK_THRESHOLDS: list[tuple[int, str]] = [
    (310, "F-"), (525, "F"), (800, "F+"),
    (1_125, "E-"), (1_510, "E"), (1_950, "E+"),
    (2_450, "D-"), (3_000, "D"), (3_600, "D+"),
    (4_300, "C-"), (5_000, "C"), (5_800, "C+"),
    (6_600, "B-"), (7_500, "B"), (8_500, "B+"),
    (9_500, "A-"), (10_500, "A"), (11_650, "A+"),
    (12_600, "S-"), (13_600, "S"), (21_700, "S+"),
    (36_000, "SS-"), (64_000, "SS"), (130_000, "SS+"),
    (292_000, "SSS-"), (650_000, "SSS"),
]
_RANK_MAX = "SSS+"


# Combien de "coups encaissés" vaut 1 point de défense en PV effectifs.
# La défense est SOUSTRACTIVE en combat (chaque coup encaissé est réduit de
# DEF), donc sur un combat de ~20-30 coups, 1 DEF économise ~25 PV de dégâts.
# C'est ce qui rend la défense valorisée comme des PV-plats dans le score
# (cohérent avec le combat), et NON comme un pourcentage.
_DEF_EFFECTIVE_HITS = 25

# Facteur d'échelle : cale le score du joueur de référence niveau 1 vers ~150
# et niveau 100 vers ~13 000 (entrée du rang S). Purement cosmétique.
_SCALE = 42


class PowerScoreService:
    def calculate_from_stats(self, stats: Stats) -> int:
        """Power score = puissance offensive × PV effectifs.

        Offensive : attaque, amplifiée par l'espérance de crit et la vitesse.
        PV effectifs : PV + défense convertie en PV-plats (cohérent avec le
        combat soustractif), le tout divisé par le taux de survie à l'esquive.
        """
        # Espérance de bonus crit : chance × (multiplicateur − neutre).
        # crit_damage est en convention 100 = neutre, 150 = ×1.5, donc le
        # bonus réel est (crit_damage − 100). (Avant : bug qui utilisait
        # crit_damage entier → sur-évaluait massivement le crit.)
        crit_bonus = (stats.crit_chance / 100) * max(0, stats.crit_damage - 100) / 100
        offensive = stats.attack * (1 + crit_bonus) * (1 + stats.speed / 100)

        # PV effectifs : défense en PV-plats (PAS en %), cohérent avec la
        # soustraction en combat. L'esquive multiplie la survie.
        effective_hp = (
            stats.max_hp + stats.defense * _DEF_EFFECTIVE_HITS
        ) / max(0.01, 1 - stats.dodge / 100)

        score = offensive * effective_hp / _SCALE
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
