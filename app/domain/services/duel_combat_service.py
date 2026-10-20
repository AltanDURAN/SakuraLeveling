import random

from app.domain.services.combat_passives import NO_PASSIVES, CombatPassives
from app.domain.value_objects.duel_result import DuelResult, DuelTurnLog
from app.domain.value_objects.stats import Stats


class DuelCombatService:
    """Combat 1v1 entre deux joueurs (PvP).

    Mécanique de jauge par la vitesse, symétrique : deux `Stats` strictement
    comparables. Les deux combattants démarrent à `max_hp` (les PV réels ne
    sont pas lus — aucune perte de PV réelle après un duel).

    Passifs de l'arbre appliqués (cf. combat_passives) : dégâts infligés
    (Titan), défense ignorée (Léthal), réduction des dégâts reçus, vol de vie
    (Vampire, soins reçus du Paladin compris) et Tenace. Ceux qui concernent
    des alliés (Égide, Rempart, provocation, sort de soin) n'ont pas d'effet
    seul : le Soigneur attaque normalement en duel.

    Garde-fou : `MAX_TURNS` (200) borne la boucle. Au-delà, le gagnant est celui
    qui a le plus de PV restants (en % de ses PV max).
    """

    MAX_TURNS = 200

    def fight_player_vs_player(
        self,
        a_stats: Stats,
        b_stats: Stats,
        a_damage_mult: float = 1.0,
        b_damage_mult: float = 1.0,
        a_passives: CombatPassives | None = None,
        b_passives: CombatPassives | None = None,
    ) -> DuelResult:
        # a_damage_mult / b_damage_mult : avantage élémentaire (Mage compris),
        # appliqué aux dégâts sortants APRÈS défense (même règle que le groupe).
        fighters = {
            "a": {"stats": a_stats, "hp": a_stats.max_hp, "gauge": 0, "mult": a_damage_mult,
                  "passives": a_passives or NO_PASSIVES, "held": False},
            "b": {"stats": b_stats, "hp": b_stats.max_hp, "gauge": 0, "mult": b_damage_mult,
                  "passives": b_passives or NO_PASSIVES, "held": False},
        }
        turns = 0
        turn_logs: list[DuelTurnLog] = []

        def finished() -> bool:
            return fighters["a"]["hp"] <= 0 or fighters["b"]["hp"] <= 0

        while not finished() and turns < self.MAX_TURNS:
            fighters["a"]["gauge"] += a_stats.speed
            fighters["b"]["gauge"] += b_stats.speed

            for actor, foe_key in (("a", "b"), ("b", "a")):
                me, foe = fighters[actor], fighters[foe_key]
                while me["gauge"] >= 100 and not finished() and turns < self.MAX_TURNS:
                    turns += 1
                    me["gauge"] -= 100
                    # NB : hp_regeneration ne s'applique PAS en combat.
                    damage, is_crit, dodged = self._strike(me, foe)
                    turn_logs.append(
                        DuelTurnLog(
                            turn_number=turns,
                            actor=actor,
                            damage=damage,
                            is_crit=is_crit,
                            target_dodged=dodged,
                            a_hp_after=fighters["a"]["hp"],
                            b_hp_after=fighters["b"]["hp"],
                        )
                    )
                    if finished():
                        return self._result(actor, turns, fighters, a_stats, b_stats, turn_logs)

        a_ratio = fighters["a"]["hp"] / a_stats.max_hp if a_stats.max_hp > 0 else 0
        b_ratio = fighters["b"]["hp"] / b_stats.max_hp if b_stats.max_hp > 0 else 0
        winner = "a" if a_ratio >= b_ratio else "b"
        return self._result(winner, turns, fighters, a_stats, b_stats, turn_logs)

    @staticmethod
    def _strike(me: dict, foe: dict) -> tuple[int, bool, bool]:
        """Un coup : crit AVANT défense, puis multiplicateurs, esquive, Tenace."""
        stats: Stats = me["stats"]
        mine: CombatPassives = me["passives"]
        theirs: CombatPassives = foe["passives"]

        raw_attack = stats.attack
        is_crit = False
        if random.random() < (stats.crit_chance / 100):
            raw_attack = int(raw_attack * (stats.crit_damage / 100))
            is_crit = True

        defense = foe["stats"].defense
        if mine.armor_penetration_pct > 0:
            defense = int(defense * (1 - min(100.0, mine.armor_penetration_pct) / 100))
        damage = max(1, raw_attack - defense)
        if me["mult"] != 1.0:
            damage = max(1, round(damage * me["mult"]))
        if mine.damage_dealt_pct:
            damage = max(1, round(damage * (1 + mine.damage_dealt_pct / 100)))
        if theirs.damage_reduction_fraction > 0:
            damage = max(1, round(damage * (1 - theirs.damage_reduction_fraction)))

        if random.random() < (foe["stats"].dodge / 100):
            return 0, is_crit, True

        if damage >= foe["hp"] > 0 and theirs.last_stand and not foe["held"]:
            foe["held"] = True
            damage = foe["hp"] - 1
        foe["hp"] = max(0, foe["hp"] - damage)

        if mine.lifesteal_pct > 0 and damage > 0 and me["hp"] > 0:
            heal = damage * mine.lifesteal_pct / 100 * (1 + mine.heal_received_pct / 100)
            me["hp"] = min(stats.max_hp, me["hp"] + int(round(heal)))
        return damage, is_crit, False

    @staticmethod
    def _result(winner, turns, fighters, a_stats, b_stats, turn_logs) -> DuelResult:
        return DuelResult(
            winner=winner,
            turns=turns,
            a_remaining_hp=fighters["a"]["hp"],
            b_remaining_hp=fighters["b"]["hp"],
            a_max_hp=a_stats.max_hp,
            b_max_hp=b_stats.max_hp,
            turn_logs=turn_logs,
        )
