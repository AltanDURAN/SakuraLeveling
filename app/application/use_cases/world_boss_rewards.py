"""Récompenses d'un world boss vaincu ou reparti (`CompleteWorldBossUseCase`).
Sorties de `world_boss.py` le 28/11/2026 (audit) : texte inchangé ; toujours
importables depuis `world_boss`."""

import random
from dataclasses import dataclass, field
from app.infrastructure.db.unit_of_work import transactional
from app.domain.services.contribution_tier_service import tier_for_share
from app.domain.services.progression_service import ProgressionService
from app.domain.services.quest_reward_service import scale_reward
from app.domain.services.reward_distribution_service import contribution_scores
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.world_boss_repository import WorldBossRepository
from app.infrastructure.world_boss.boss_definition_loader import (
    get_definition as get_boss_definition,
)
@dataclass
class BossRewardEntry:
    player_id: int
    display_name: str
    role: str  # "top_damage" | "top_tank" | "top_heal" | "participant"
    gold: int
    xp: int
    items: list[tuple[str, int]] = field(default_factory=list)
    # Palier de contribution atteint + part de l'effort total (affichage).
    tier_code: str = "bronze"
    tier_label: str = "🥉 Combattant"
    share: float = 0.0
    damage: int = 0


@dataclass
class CompleteBossResult:
    success: bool
    message: str
    rewards: list[BossRewardEntry] = field(default_factory=list)


class CompleteWorldBossUseCase:
    """Distribue les récompenses à tous les participants d'un boss vaincu, ou
    d'un boss reparti vivant (`escaped=True`) : l'or et l'XP valent alors la
    part de ses PV qu'on lui a retirée, sans butin exclusif ni titres. Sinon un
    serveur encore faible resterait sans aucune récompense toute la semaine.

    Règles spec :
        • Top damage / top tank / top heal reçoivent un bonus catégorie
        • Tous les participants reçoivent une récompense de base
        • Le top-X reçoit AUSSI la récompense de base ("récompense de base
          supplémentaire pour ceux qui ont déjà eu des bonus")

    Récompenses V1 (génériques, à affiner) :
        • Top damage / tank / heal : +200g, +100xp, +1 potion_soin
        • Base (tous) : +50g, +25xp, +1 potion_soin
    """

    # Récompense de base (présence suffit) — tous les participants.
    BASE_REWARD_GOLD = 50
    BASE_REWARD_ITEM = ("potion_soin", 1)
    # XP ÉGALE pour tous (× multiplicateur de tier).
    XP_PER_TIER = 50
    # Pool d'or FIXE (× tier) réparti AU PRORATA de la contribution.
    GOLD_POOL_PER_TIER = 200
    # Bonus top-3 global (rangs 1/2/3, × tier).
    TOP3_GOLD = (150, 100, 50)
    # Bonus top-1 par catégorie (dégâts/tank/soin/participation, × tier) + potion.
    CATEGORY_BONUS_GOLD = 100
    CATEGORY_BONUS_ITEM = ("potion_soin", 1)

    def __init__(
        self,
        world_boss_repository: WorldBossRepository,
        player_repository: PlayerRepository,
        item_repository: ItemRepository,
        inventory_repository: InventoryRepository,
        progression_service: ProgressionService | None = None,
    ) -> None:
        self.world_boss_repository = world_boss_repository
        self.player_repository = player_repository
        self.item_repository = item_repository
        self.inventory_repository = inventory_repository
        self.progression_service = progression_service or ProgressionService()

    @transactional
    def execute(self, boss_id: int, escaped: bool = False) -> CompleteBossResult:
        boss = self.world_boss_repository.get_by_id(boss_id)
        if boss is None:
            return CompleteBossResult(False, "❌ Boss introuvable.")

        participations = self.world_boss_repository.list_participations_with_metrics(boss_id)
        if escaped:
            self.world_boss_repository.mark_escaped(boss_id)
        if not participations:
            return CompleteBossResult(
                False, "⚠️ Aucun participant à récompenser.", rewards=[],
            )

        # Part du travail accomplie : 100 % sur un boss tué.
        completion = 1.0 if not escaped else 1 - max(0, boss.current_hp) / max(1, boss.max_hp)

        # Multiplicateur de tier (gros boss = plus grosses récompenses).
        tier_mult = 1 + (boss.max_hp // 200_000)
        gold_pool = self.GOLD_POOL_PER_TIER * tier_mult
        xp_each = self.XP_PER_TIER * tier_mult

        # Score de contribution combiné (dégâts, coups encaissés, soins).
        scores = contribution_scores(participations)
        total_score = sum(scores.values()) or 1.0

        # Top-1 par catégorie (None si métrique nulle).
        top_damage = max(participations, key=lambda p: p.damage_dealt)
        top_tank = max(participations, key=lambda p: p.damage_tanked)
        top_heal = max(participations, key=lambda p: p.hp_healed)
        top_part = max(participations, key=lambda p: p.fights_count)
        top_damage_id = top_damage.player_id if top_damage.damage_dealt > 0 else None
        top_tank_id = top_tank.player_id if top_tank.damage_tanked > 0 else None
        top_heal_id = top_heal.player_id if top_heal.hp_healed > 0 else None
        top_part_id = top_part.player_id if top_part.fights_count > 0 else None

        # Loot exclusif du boss : roll indépendant par participant.
        boss_def = get_boss_definition(boss.code)
        boss_loot = boss_def.loot_table if boss_def is not None and not escaped else []

        # Top-3 global (par score combiné) → rangs pour le bonus.
        top3 = sorted(participations, key=lambda p: scores[p.player_id], reverse=True)[:3]
        top3_rank = {p.player_id: i for i, p in enumerate(top3) if scores[p.player_id] > 0}
        # MVP = meilleur score global (pour le titre exclusif, cf. plus bas).
        mvp_id = top3[0].player_id if top3 and scores[top3[0].player_id] > 0 else None

        rewards: list[BossRewardEntry] = []
        for p in participations:
            profile = self.player_repository.get_profile_by_player_id(p.player_id)
            if profile is None:
                continue

            # Base (présence) + part proportionnelle du pool d'or, le tout
            # amplifié par le PALIER DE CONTRIBUTION atteint (Combattant →
            # Vétéran → Champion → Légende). Le palier donne un objectif clair
            # là où le simple prorata restait abstrait.
            share = scores[p.player_id] / total_score
            tier = tier_for_share(share)
            total_gold = int(
                (self.BASE_REWARD_GOLD + int(gold_pool * share)) * tier.gold_multiplier
            )
            total_xp = xp_each  # XP ÉGALE pour tous
            items: list[tuple[str, int]] = [self.BASE_REWARD_ITEM]
            items.extend(tier.bonus_items)
            roles_won: list[str] = []

            # Bonus top-3 global (cumulable avec les bonus de catégorie).
            if p.player_id in top3_rank:
                total_gold += self.TOP3_GOLD[top3_rank[p.player_id]] * tier_mult
                roles_won.append(f"top{top3_rank[p.player_id] + 1}_global")

            # Bonus top-1 par catégorie (cumulables).
            cat_bonus = self.CATEGORY_BONUS_GOLD * tier_mult
            if p.player_id == top_damage_id:
                total_gold += cat_bonus
                items.append(self.CATEGORY_BONUS_ITEM)
                roles_won.append("top_damage")
            if p.player_id == top_tank_id:
                total_gold += cat_bonus
                items.append(self.CATEGORY_BONUS_ITEM)
                roles_won.append("top_tank")
            if p.player_id == top_heal_id:
                total_gold += cat_bonus
                items.append(self.CATEGORY_BONUS_ITEM)
                roles_won.append("top_heal")
            if p.player_id == top_part_id:
                total_gold += cat_bonus
                roles_won.append("top_participation")

            # Loot exclusif : chaque participant roll la table du boss.
            for entry in boss_loot:
                try:
                    if random.random() < float(entry.get("drop_rate", 0)):
                        qmin = int(entry.get("min_quantity", 1))
                        qmax = int(entry.get("max_quantity", qmin))
                        items.append((entry["item_code"], random.randint(qmin, qmax)))
                except (KeyError, ValueError, TypeError):
                    continue

            if escaped:
                items = [self.BASE_REWARD_ITEM]     # le butin récompense la victoire
            role = roles_won[0] if roles_won else "participant"

            # Les montants ci-dessus sont des montants de NIVEAU 1 : on les
            # indexe sur le niveau du joueur (cf. quest_reward_service), sinon
            # le raid de la semaine ne vaudrait plus rien à haut niveau. Le
            # raid est hebdomadaire et doit rester marquant : référence 1.
            level = profile.progression.level
            total_gold = round(scale_reward(total_gold, level, reference_level=1) * completion)
            total_xp = round(scale_reward(total_xp, level, reference_level=1) * completion)

            # Application en DB
            self.player_repository.add_gold(p.player_id, total_gold, source="raid")
            # XP avec calcul de level-up correct (sinon l'XP est juste
            # ajoutée mais le joueur ne gagne pas de niveau ni de skill points)
            progression = self.progression_service.apply_level_up(
                current_level=profile.progression.level,
                current_xp=profile.progression.xp,
                gained_xp=total_xp,
                current_skill_points=profile.progression.skill_points,
                current_stat_points=profile.progression.stat_points,
            )
            new_level = progression.level
            new_xp = progression.xp
            new_skill_points = progression.skill_points
            self.player_repository.apply_progression(
                player_id=p.player_id,
                new_level=new_level,
                new_xp=new_xp,
                new_skill_points=new_skill_points,
                new_stat_points=progression.stat_points,
            )
            for item_code, qty in items:
                item = self.item_repository.get_by_code(item_code)
                if item is not None:
                    self.inventory_repository.add_item(p.player_id, item.id, qty)

            rewards.append(
                BossRewardEntry(
                    player_id=p.player_id,
                    display_name=profile.player.display_name,
                    role=role,
                    gold=total_gold,
                    xp=total_xp,
                    items=items,
                    tier_code=tier.code,
                    tier_label=tier.format(),
                    share=share,
                    damage=p.damage_dealt,
                )
            )

        # Titres : « Tueur de <boss> » à tous les vainqueurs (petit bonus) +
        # « MVP des World Boss » exclusif au meilleur contributeur (rotatif).
        try:
            from app.application.services.exclusive_title_service import (
                ExclusiveTitleService,
            )
            from app.infrastructure.db.repositories.player_title_repository import (
                PlayerTitleRepository,
            )
            session = self.world_boss_repository.session
            title_repo = PlayerTitleRepository(session)
            tueur_code = f"tueur_{boss.code}"
            if not escaped:
                for p in participations:
                    title_repo.unlock(p.player_id, tueur_code)
            if mvp_id is not None and not escaped:
                ExclusiveTitleService(session).award_to("mvp_world_boss", mvp_id)
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "Attribution des titres world boss échouée", exc_info=True
            )

        verb = "repart" if escaped else "vaincu"
        return CompleteBossResult(
            success=True,
            message=f"🏆 **{boss.name}** {verb} — {len(rewards)} participant(s) récompensé(s).",
            rewards=rewards,
        )
