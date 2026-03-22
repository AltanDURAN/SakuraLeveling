from app.domain.entities.mob_definition import MobDefinition
from app.domain.value_objects.battle_result import BattleResult
from app.domain.value_objects.stats import Stats


class CombatService:
    def fight_player_vs_mob(
        self,
        player_stats: Stats,
        mob: MobDefinition,
    ) -> BattleResult:
        player_hp = player_stats.max_hp
        mob_hp = mob.max_hp
        turns = 0

        player_damage = max(1, player_stats.attack - mob.defense)
        mob_damage = max(1, mob.attack - player_stats.defense)

        while player_hp > 0 and mob_hp > 0:
            turns += 1

            mob_hp -= player_damage
            if mob_hp <= 0:
                return BattleResult(
                    victory=True,
                    turns=turns,
                    player_remaining_hp=max(0, player_hp),
                    mob_remaining_hp=max(0, mob_hp),
                    xp_gained=mob.xp_reward,
                    gold_gained=mob.gold_reward,
                    items_gained=[],
                    leveled_up=False,
                    new_level=None,
                    summary=(
                        f"Vous avez vaincu **{mob.name}** en {turns} tour(s)."
                    ),
                )

            player_hp -= mob_damage
            if player_hp <= 0:
                return BattleResult(
                    victory=False,
                    turns=turns,
                    player_remaining_hp=max(0, player_hp),
                    mob_remaining_hp=max(0, mob_hp),
                    xp_gained=0,
                    gold_gained=0,
                    items_gained=[],
                    leveled_up=False,
                    new_level=None,
                    summary=(
                        f"Vous avez été vaincu par **{mob.name}** en {turns} tour(s)."
                    ),
                )

        return BattleResult(
            victory=False,
            turns=turns,
            player_remaining_hp=max(0, player_hp),
            mob_remaining_hp=max(0, mob_hp),
            xp_gained=0,
            gold_gained=0,
            items_gained=[],
            leveled_up=False,
            new_level=None,
            summary="Le combat s'est terminé de manière inattendue.",
        )