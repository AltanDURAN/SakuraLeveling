import random

from app.domain.value_objects.duel_result import DuelResult, DuelTurnLog
from app.domain.value_objects.stats import Stats


class DuelCombatService:
    """Combat 1v1 entre deux joueurs (PvP).

    Reprend la mécanique gauge speed-based de `CombatService.fight_player_vs_mob`
    mais symétrique : pas de mob, deux `Stats` strictement comparables. Les deux
    combattants démarrent à `max_hp` (les current_hp réels ne sont pas lus —
    cf. spec : aucune perte d'HP réelle suite au duel).

    Garde-fou : `MAX_TURNS` (200) borne la boucle si jamais deux jeux de stats
    s'auto-équilibrent (peu probable avec dégâts ≥ 1, mais évite tout risque).
    Au-delà, on déclare gagnant celui qui a le plus de PV restants.
    """

    MAX_TURNS = 200

    def fight_player_vs_player(
        self,
        a_stats: Stats,
        b_stats: Stats,
    ) -> DuelResult:
        a_hp = a_stats.max_hp
        b_hp = b_stats.max_hp

        a_gauge = 0
        b_gauge = 0
        turns = 0
        turn_logs: list[DuelTurnLog] = []

        while a_hp > 0 and b_hp > 0 and turns < self.MAX_TURNS:
            a_gauge += a_stats.speed
            b_gauge += b_stats.speed

            acted = False

            while a_gauge >= 100 and a_hp > 0 and b_hp > 0 and turns < self.MAX_TURNS:
                turns += 1
                acted = True
                a_gauge -= 100

                if a_stats.hp_regeneration > 0:
                    a_hp = min(a_stats.max_hp, a_hp + a_stats.hp_regeneration)

                damage = max(1, a_stats.attack - b_stats.defense)
                is_crit = False
                dodged = False

                if random.random() < (a_stats.crit_chance / 100):
                    damage = int(damage * (a_stats.crit_damage / 100))
                    is_crit = True

                if random.random() < (b_stats.dodge / 100):
                    damage = 0
                    dodged = True
                else:
                    b_hp = max(0, b_hp - damage)

                turn_logs.append(
                    DuelTurnLog(
                        turn_number=turns,
                        actor="a",
                        damage=damage,
                        is_crit=is_crit,
                        target_dodged=dodged,
                        a_hp_after=a_hp,
                        b_hp_after=b_hp,
                    )
                )

                if b_hp <= 0:
                    return DuelResult(
                        winner="a",
                        turns=turns,
                        a_remaining_hp=a_hp,
                        b_remaining_hp=0,
                        a_max_hp=a_stats.max_hp,
                        b_max_hp=b_stats.max_hp,
                        turn_logs=turn_logs,
                    )

            while b_gauge >= 100 and a_hp > 0 and b_hp > 0 and turns < self.MAX_TURNS:
                turns += 1
                acted = True
                b_gauge -= 100

                if b_stats.hp_regeneration > 0:
                    b_hp = min(b_stats.max_hp, b_hp + b_stats.hp_regeneration)

                damage = max(1, b_stats.attack - a_stats.defense)
                is_crit = False
                dodged = False

                if random.random() < (b_stats.crit_chance / 100):
                    damage = int(damage * (b_stats.crit_damage / 100))
                    is_crit = True

                if random.random() < (a_stats.dodge / 100):
                    damage = 0
                    dodged = True
                else:
                    a_hp = max(0, a_hp - damage)

                turn_logs.append(
                    DuelTurnLog(
                        turn_number=turns,
                        actor="b",
                        damage=damage,
                        is_crit=is_crit,
                        target_dodged=dodged,
                        a_hp_after=a_hp,
                        b_hp_after=b_hp,
                    )
                )

                if a_hp <= 0:
                    return DuelResult(
                        winner="b",
                        turns=turns,
                        a_remaining_hp=0,
                        b_remaining_hp=b_hp,
                        a_max_hp=a_stats.max_hp,
                        b_max_hp=b_stats.max_hp,
                        turn_logs=turn_logs,
                    )

            if not acted:
                continue

        # Sortie sur MAX_TURNS sans KO : le vainqueur est celui aux HP les plus
        # élevés (en pourcentage de max_hp pour comparer équitablement deux
        # plafonds différents). Égalité parfaite → "a" (l'attaquant).
        a_ratio = a_hp / a_stats.max_hp if a_stats.max_hp > 0 else 0
        b_ratio = b_hp / b_stats.max_hp if b_stats.max_hp > 0 else 0
        winner = "a" if a_ratio >= b_ratio else "b"
        return DuelResult(
            winner=winner,
            turns=turns,
            a_remaining_hp=a_hp,
            b_remaining_hp=b_hp,
            a_max_hp=a_stats.max_hp,
            b_max_hp=b_stats.max_hp,
            turn_logs=turn_logs,
        )
