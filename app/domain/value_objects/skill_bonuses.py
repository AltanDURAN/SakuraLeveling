from dataclasses import dataclass

from app.domain.value_objects.stats import Stats


@dataclass
class SkillBonuses:
    """Agrégation de tous les bonus passifs accordés par l'arbre de compétences.

    Conventions :
    - `*_percent` : multiplicateur additif (0.15 = +15%) appliqué à la stat correspondante
      (ex : final_attack = base_attack × (1 + atk_percent))
    - `*_flat` : ajouté tel quel à la stat correspondante (convention 0..100 pour crit/dodge,
      entiers pour speed et hp_regeneration)
    - `xp_drop_percent`, `gold_drop_percent` : multiplicateur additif appliqué au gain final
    - `drop_rate_multiplier` : multiplicateur (neutre = 1.0) appliqué au taux de drop de
      chaque entrée de loot table. Préserve la rareté des items rares.
    """

    # Nœuds PLATS : le moteur infini de l'arbre en V2 (croissance linéaire,
    # sans plafond — c'est ici qu'on absorbe les points illimités).
    atk_flat: int = 0
    def_flat: int = 0
    hp_max_flat: int = 0
    # Nœuds % (multiplicateurs) : plafonnés en amont (aggregate_bonuses).
    atk_percent: float = 0.0
    def_percent: float = 0.0
    hp_max_percent: float = 0.0
    crit_chance_flat: int = 0
    crit_damage_flat: int = 0
    dodge_flat: int = 0
    speed_flat: int = 0
    hp_regeneration_flat: int = 0
    xp_drop_percent: float = 0.0
    gold_drop_percent: float = 0.0
    drop_rate_multiplier: float = 1.0

    @classmethod
    def empty(cls) -> "SkillBonuses":
        return cls()

    def apply_to_stats(self, stats: Stats) -> Stats:
        """Renvoie une nouvelle Stats avec les bonus de l'arbre appliqués.

        - Stats flat additives (crit_chance, crit_damage, dodge, speed, hp_regeneration)
          sont ajoutées telles quelles AVANT les caps.
        - Stats principales (max_hp, attack, defense) reçoivent leur bonus % MULTIPLICATIF
          appliqué après les flats.

        Caps existants (gérés en amont par StatsService) : crit_chance ≤ 75, dodge ≤ 50.
        """
        new_max_hp = round((stats.max_hp + self.hp_max_flat) * (1 + self.hp_max_percent))
        new_attack = round((stats.attack + self.atk_flat) * (1 + self.atk_percent))
        new_defense = round((stats.defense + self.def_flat) * (1 + self.def_percent))

        new_crit_chance = stats.crit_chance + self.crit_chance_flat
        new_crit_damage = stats.crit_damage + self.crit_damage_flat
        new_dodge = stats.dodge + self.dodge_flat
        new_speed = stats.speed + self.speed_flat
        new_hp_regen = stats.hp_regeneration + self.hp_regeneration_flat

        # Caps de cohérence (dupliqués pour ne pas dépendre de StatsService)
        new_crit_chance = min(new_crit_chance, 75)
        new_dodge = min(new_dodge, 50)
        new_crit_damage = max(new_crit_damage, 100)

        return Stats(
            max_hp=new_max_hp,
            attack=new_attack,
            defense=new_defense,
            crit_chance=new_crit_chance,
            crit_damage=new_crit_damage,
            dodge=new_dodge,
            hp_regeneration=max(0, new_hp_regen),
            speed=max(1, new_speed),
        )
