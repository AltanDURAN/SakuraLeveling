"""Application des modifiers d'un boss à un combat en cours.

Modifiers supportés (V1) :
    • damage_immunity_threshold : filtre les dégâts entrants < N (réduit à 0)
    • enrage_below_pct + enrage_attack_multiplier : si current_hp / max_hp <
      threshold, multiplier l'attack du boss
    • crit_immunity : annule l'effet "crit" du joueur (les crits = dmg normaux)

Tout modifier inconnu est ignoré poliment — facilite l'extension par contenu
JSON sans casser le moteur.
"""

from dataclasses import dataclass

from app.domain.value_objects.stats import Stats


@dataclass
class CombatAdjustments:
    """Ajustements appliqués pour un round précis (avant le combat)."""

    boss_attack: int
    player_crit_chance: int  # 0 si crit_immunity actif
    damage_immunity_threshold: int  # 0 si pas d'immunité

    enraged: bool = False  # juste pour le log/UI


class BossModifierService:
    def compute_adjustments(
        self,
        modifiers: dict,
        boss_max_hp: int,
        boss_current_hp: int,
        boss_attack: int,
        player_crit_chance: int,
    ) -> CombatAdjustments:
        adjusted_attack = boss_attack
        enraged = False

        # Enrage : si HP courants en-dessous du seuil, multiplier l'attaque
        threshold_pct = modifiers.get("enrage_below_pct")
        attack_mult = modifiers.get("enrage_attack_multiplier", 1.0)
        if threshold_pct is not None and boss_max_hp > 0:
            ratio_pct = (boss_current_hp / boss_max_hp) * 100
            if ratio_pct <= threshold_pct:
                adjusted_attack = int(boss_attack * attack_mult)
                enraged = True

        # Crit immunity : on neutralise la crit_chance du joueur
        adjusted_crit = (
            0 if modifiers.get("crit_immunity") else player_crit_chance
        )

        # Damage immunity threshold : on l'expose tel quel pour filtrage côté caller
        threshold = int(modifiers.get("damage_immunity_threshold", 0))

        return CombatAdjustments(
            boss_attack=adjusted_attack,
            player_crit_chance=adjusted_crit,
            damage_immunity_threshold=threshold,
            enraged=enraged,
        )

    @staticmethod
    def filter_incoming_damage(damage: int, threshold: int) -> int:
        """Renvoie le dégât effectif après filtre du seuil d'immunité.
        Si damage < threshold → 0 (le coup tape mais glisse sur la carapace)."""
        if threshold <= 0:
            return damage
        return 0 if damage < threshold else damage

    def apply_adjustments_to_boss_stats(
        self,
        modifiers: dict,
        boss_max_hp: int,
        boss_current_hp: int,
        base_stats: Stats,
    ) -> Stats:
        """Pour le combat solo, retourne les stats du boss avec enrage appliqué.
        Note : speed/defense/dodge ne sont pas affectés par les modifiers V1."""
        adj = self.compute_adjustments(
            modifiers=modifiers,
            boss_max_hp=boss_max_hp,
            boss_current_hp=boss_current_hp,
            boss_attack=base_stats.attack,
            player_crit_chance=0,  # côté boss on s'en fiche pour ce calcul
        )
        return Stats(
            max_hp=base_stats.max_hp,
            attack=adj.boss_attack,
            defense=base_stats.defense,
            speed=base_stats.speed,
            crit_chance=base_stats.crit_chance,
            crit_damage=base_stats.crit_damage,
            dodge=base_stats.dodge,
            hp_regeneration=0,  # toujours 0 pour un boss
        )
