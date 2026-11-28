"""Récompenses d'un combat de zone (`apply_rewards`) : or, XP, butin, pièces,
essences, titres, quêtes, journal et carrière. Méthodes d'`EncounterService`
(mixin), sorties d'`encounter_service.py` le 28/11/2026 (audit) : texte inchangé."""

from app.application.use_cases.records import track_fight
from app.application.services.exclusive_title_service import ExclusiveTitleService
from app.application.services.title_bonus_resolver import resolve_title_bonuses
from app.application.services.title_unlock_service import TitleUnlockService
from app.application.use_cases.daily_quests import DailyQuestProgressService
from app.application.use_cases.weekly_quests import WeeklyQuestProgressService
from app.domain.services.lunar_service import effects_text as lunar_effects_text
from app.domain.services.loot_service import LootService
from app.infrastructure.loot.family_drop_loader import get_family_drops
from app.domain.services import pack_service
from app.domain.services.progression_service import ProgressionService, newcomer_xp_multiplier
from app.domain.services.reward_distribution_service import RewardDistributionService
from app.domain.services.skill_tree_service import SkillTreeService
from app.domain.services.element_affinity_progression_service import (
    ElementAffinityProgressionService,
)
from app.domain.value_objects.battle_summary import BattleSummary
from app.domain.value_objects.player_reward import EssenceGain, PlayerReward
from app.domain.value_objects.skill_bonuses import SkillBonuses
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.domain.services.gear_passives import active_passives
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.element_affinity_repository import (
    ElementAffinityRepository,
)
from app.infrastructure.db.repositories.element_essence_repository import (
    ElementEssenceRepository,
)
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.repositories.player_career_stats_repository import (
    PlayerCareerStatsRepository,
)
from app.infrastructure.db.repositories.player_kill_repository import PlayerKillRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.daily_quest_repository import DailyQuestRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.db.repositories.player_title_repository import PlayerTitleRepository
from app.infrastructure.db.repositories.weekly_quest_repository import WeeklyQuestRepository
from app.infrastructure.db.session import get_db_session
from app.application.use_cases.cards import player_card_bonuses
from app.domain.services.card_service import stochastic_round, with_card_bonuses
from app.infrastructure.skill_tree.skill_tree_loader import (
    get_definition as get_skill_tree_definition,
)
from app.domain.services.monitoring import kinds
from app.infrastructure.monitoring.telemetry import record as record_event


class EncounterRewardsMixin:
    @staticmethod
    def _roll_gear_drop(session, player_id: int, mob, rng=None,
                        drop_bonus: float = 1.0, drop_rate_multiplier: float = 1.0) -> list[tuple[str, str]]:
        """Tirage de la pièce du monstre pour UN survivant (cf. gear_service).

        Le passif « Trouvaille » (épique et plus) ajoute +10 % aux raretés
        inférieures à celle de sa pièce ; `drop_bonus` (arbre + titres) est
        bridé par `roll_drop`.
        Renvoie [(nom, rareté)] ou [] — au plus une pièce par mort."""
        from app.domain.services.gear_passives import active_passives
        from app.domain.services.gear_service import roll_drop
        from app.infrastructure.db.repositories.gear_repository import GearRepository
        from app.infrastructure.db.repositories.item_repository import ItemRepository

        code = getattr(mob, "gear_item_code", "") or ""
        if not code:
            return []
        equipped = EquipmentRepository(session).list_by_player_id(player_id)
        lucky = next((e.rarity for e in equipped
                      if e.item_definition.passive == "lucky_find"
                      and "lucky_find" in active_passives([e])), None)
        rarity = roll_drop(rng, drop_rate_multiplier=drop_rate_multiplier, drop_bonus=drop_bonus,
                           lucky_find_rarity=lucky)
        if rarity is None:
            return []
        item = ItemRepository(session).get_by_code(code)
        if item is None:
            return []
        GearRepository(session).add(player_id, item.id, rarity, source="drop")
        record_event(session, kinds.GEAR_DROP, player_id=player_id, ref=code, data={"rarity": rarity.value})
        return [(item.name, rarity.value)]

    @staticmethod
    def _fusable(session, player_id: int, gear_drop: list[tuple[str, str]]) -> list[str]:
        """Les pièces reçues dont le joueur a maintenant 2 copies (même pièce,
        même rareté) : le récap renvoie vers le forgeron (revue de novembre)."""
        if not gear_drop:
            return []
        from app.infrastructure.db.repositories.gear_repository import GearRepository

        owned = GearRepository(session).list_owned(player_id)
        return [name for name, rarity in dict.fromkeys(gear_drop)
                if sum(1 for g in owned if g.item_definition.name == name and g.rarity == rarity) >= 2]

    def apply_rewards(self, encounter, result) -> BattleSummary | None:
        """Récompenses d'un combat de zone — un monstre ou une MEUTE (cf.
        pack_service : XP et or de la meute entière, une victoire par monstre,
        le butin de chacun avec la probabilité du facteur de meute)."""
        if encounter is None:
            return None

        states = list(getattr(encounter, "mobs", None) or [encounter.mob_state])
        with get_db_session() as session:
            mob_repository = MobRepository(session)
            definitions = [mob_repository.get_by_code(s.code) for s in states]

        if any(d is None for d in definitions):
            return None
        mob = definitions[0]                      # le chef : nom, image, famille du récap
        size = len(definitions)
        mob_name = getattr(encounter, "mob_names", mob.name) if size > 1 else mob.name
        # Événement lunaire (pleine lune, lune de sang, éclipse…) : XP, or et
        # chances de butin multipliés ; les essences ont leur propre facteur.
        lunar = getattr(encounter, "lunar", None)
        lunar_rewards = lunar.rule.rewards if lunar is not None else 1.0
        lunar_essences = lunar.rule.essences if lunar is not None else 1.0
        lunar_note = (f"{lunar.label} — {lunar_effects_text(lunar.rule)}" if lunar is not None else "")
        xp_reward = round(pack_service.pack_reward([d.xp_reward for d in definitions]) * lunar_rewards)
        gold_reward = round(pack_service.pack_reward([d.gold_reward for d in definitions]) * lunar_rewards)

        reward_distribution_service = RewardDistributionService()
        loot_service = LootService()

        rewards: list[PlayerReward] = []
        contributions_by_id = {c.player_id: c for c in result.contributions}

        if not result.victory:
            with get_db_session() as session:
                career_repository = PlayerCareerStatsRepository(session)
                for participant in encounter.participants.values():
                    contribution = contributions_by_id.get(participant.player_id)
                    self._record_combat_career_stats(
                        career_repository=career_repository,
                        participant=participant,
                        contribution=contribution,
                        won_combat=False,
                    )
                    rewards.append(
                        PlayerReward(
                            player_id=participant.player_id,
                            user_id=participant.user_id,
                            name=participant.display_name,
                            avatar_url=participant.avatar_url,
                            gold=0,
                            xp=0,
                            items=[],
                            contribution=contribution,
                        )
                    )
                self._journal_combat(session, encounter, result, rewards)
                track_fight(session, encounter, result)          # records : exploits
                session.commit()

            return BattleSummary(
                outcome="defeat",
                mob_name=mob_name,
                mob_image_name=mob.image_name,
                mob_family=mob.family,
                turns=result.turns,
                rewards=rewards,
                base_xp_reward=xp_reward,
                base_gold_reward=gold_reward,
                lunar_note=lunar_note,
                mob_count=size,
            )

        contribution_shares = reward_distribution_service.compute_contribution_shares(
            contributions=result.contributions,
        )
        gold_per_player = reward_distribution_service.distribute_gold(
            mob_gold_reward=gold_reward,
            contributions=result.contributions,
        )
        # XP : même montant plein pour tous, morts inclus (pas de variance).
        xp_per_player = reward_distribution_service.distribute_xp(
            mob_xp_reward=xp_reward,
            contributions=result.contributions,
        )

        # Une seule transaction : or, objets, kills, titres et quêtes de TOUS
        # les participants — validés ensemble, ou rien (unit_of_work).
        with get_db_session(atomic=True) as session:
            player_repository = PlayerRepository(session)
            kill_repository = PlayerKillRepository(session)
            inventory_repository = InventoryRepository(session)
            item_repository = ItemRepository(session)
            career_repository = PlayerCareerStatsRepository(session)
            skill_allocation_repository = PlayerSkillAllocationRepository(session)
            title_unlock_service = TitleUnlockService(
                title_repository=PlayerTitleRepository(session),
                kill_repository=kill_repository,
            )
            skill_tree_service = SkillTreeService(get_skill_tree_definition())
            essence_repository = ElementEssenceRepository(session)
            affinity_repository = ElementAffinityRepository(session)
            affinity_progression = ElementAffinityProgressionService()
            # Essences par kill = propriété de la ZONE de spawn (via la famille) :
            # fourchette [min, max] tirée aléatoirement à chaque kill.
            from app.infrastructure.encounters.farm_zone_loader import (
                get_essences_range_for_family,
            )
            # Bénédiction de l'offrande commune (tout le serveur, 24 h).
            # Le Nouvel An (événements saisonniers) les réunit toutes.
            from app.application.use_cases.offering import active_blessings
            from app.domain.services.offering_service import blessings_value

            blessings = active_blessings(session)
            # Objets d'événement (sucres d'orge…) : chaque monstre vaincu en
            # donne à chaque survivant, sans tirage (événements saisonniers).
            from app.application.use_cases.seasonal import event_drops

            festive_drops = event_drops()
            blessed_xp = 1 + blessings_value(blessings, "xp_pct") / 100
            blessed_materials = int(blessings_value(blessings, "material_bonus"))
            blessed_gear = 1 + blessings_value(blessings, "gear_drop_pct") / 100
            blessed_essences = int(blessings_value(blessings, "essence_bonus"))

            for participant in encounter.participants.values():
                contribution = contributions_by_id.get(participant.player_id)
                survived = contribution is not None and contribution.survived

                self._record_combat_career_stats(
                    career_repository=career_repository,
                    participant=participant,
                    contribution=contribution,
                    won_combat=survived,
                )

                # Bonus de l'arbre de compétences (xp/gold/drop) propres à ce joueur
                allocations = skill_allocation_repository.list_by_player(
                    participant.player_id
                )
                bonuses: SkillBonuses = skill_tree_service.aggregate_bonuses(allocations)

                # Bonus du titre Farmer Fou (+1% gold/xp). N'affecte que le
                # détenteur — les coéquipiers n'en bénéficient pas. Titres des
                # records : de l'or seulement (+5 / +3 / +1 %), additionné.
                # Cartes à collectionner : butin contre CE monstre (comme le
                # Chasseur légendaire), XP / or / matériaux / pièces / essences.
                cards = player_card_bonuses(session, participant.player_id)
                title_bonuses = with_card_bonuses(
                    resolve_title_bonuses(session, participant.player_id), cards)
                pack_pct = cards.pack_reward_pct if size > 1 else 0
                # Tous ces % s'additionnent (Farmer Fou, records, cartes).
                xp_bonus_pct = (title_bonuses.gold_xp_bonus_pct + cards.xp_pct + pack_pct) / 100.0
                gold_bonus_pct = (title_bonuses.gold_xp_bonus_pct + title_bonuses.gold_bonus_pct
                                  + cards.gold_pct + pack_pct) / 100.0

                # Coup de pouce des débuts (cf. ProgressionService).
                level_before = self._level_of(player_repository, participant.player_id)
                newcomer = newcomer_xp_multiplier(level_before)

                base_xp = xp_per_player.get(participant.player_id, 0)
                xp = round(
                    base_xp * (1 + bonuses.xp_drop_percent) * (1 + xp_bonus_pct) * blessed_xp * newcomer
                )

                # L'XP est gagnée par TOUS les participants, morts inclus
                # (le mob est vaincu) — appliquée via le palier de niveau.
                progression = self._grant_xp(player_repository, participant.player_id, xp)
                growth = {
                    "level_before": level_before,
                    "level_after": progression.level if progression else level_before,
                    "stat_points": progression.stat_points if progression else 0,
                    "skill_points": progression.skill_points if progression else 0,
                    "newcomer_bonus": newcomer > 1,
                }

                if not survived:
                    # Mort en combat : XP oui (déjà appliquée), mais PAS d'or,
                    # PAS de loot, PAS de crédit de kill (pénalité de mort).
                    rewards.append(
                        PlayerReward(
                            player_id=participant.player_id,
                            user_id=participant.user_id,
                            name=participant.display_name,
                            avatar_url=participant.avatar_url,
                            gold=0,
                            xp=xp,
                            items=[],
                            contribution=contribution,
                            contribution_share=0.0,
                            **growth,
                        )
                    )
                    continue

                base_gold = gold_per_player.get(participant.player_id, 0)
                gold = round(
                    base_gold * (1 + bonuses.gold_drop_percent) * (1 + gold_bonus_pct)
                )
                if gold > 0:
                    player_repository.add_gold(participant.player_id, gold, source="combat")
                    career_repository.add(participant.player_id, gold_earned=gold)

                _wqp = WeeklyQuestProgressService(WeeklyQuestRepository(session))
                _dqp = DailyQuestProgressService(DailyQuestRepository(session))
                group_size = len(encounter.participants)
                essence_hunter = blessed_essences + (1 if "essence_hunter" in active_passives(
                    EquipmentRepository(session).list_by_player_id(participant.player_id)
                ) else 0)

                dropped: dict[str, int] = {}
                festive: dict[str, int] = {}
                gear_drop: list[tuple[str, str]] = []
                essence_gains: list[EssenceGain] = []
                unlocked: list = []       # titres débloqués, montrés au récapitulatif
                # Chaque monstre vaincu : une victoire (kill, titres, quêtes) ;
                # son butin tombe toujours seul, avec la probabilité du
                # facteur de meute sinon (pack_service.loot_roll).
                for state, definition in zip(states, definitions):
                    kill_repository.increment(participant.player_id, definition.code)
                    for item_code, per_kill in festive_drops:
                        festive[item_code] = festive.get(item_code, 0) + per_kill
                    if pack_service.loot_roll(size):
                        # Chasseur Légendaire : multiplicateur drop rate spécifique
                        # à ce mob, multiplicatif (ne casse pas la rareté).
                        chasseur_mult = title_bonuses.drop_rate_multiplier_for_mob(definition.code)
                        for item_code, quantity in loot_service.generate_loot(
                            definition,
                            drop_rate_multiplier=(bonuses.drop_rate_multiplier * chasseur_mult * lunar_rewards
                                                  * (1 + cards.materials_pct / 100)),
                            family_drops=get_family_drops(),
                        ):
                            dropped[item_code] = dropped.get(item_code, 0) + quantity
                        # Aurélia (offrande commune) : +X matériaux de fusion.
                        family_item = (get_family_drops().get(definition.family) or {}).get("item_code")
                        if blessed_materials and family_item:
                            dropped[family_item] = dropped.get(family_item, 0) + blessed_materials
                        # Équipement v2 : 0 ou 1 pièce, celle que porte le monstre.
                        gear_drop += self._roll_gear_drop(
                            session, participant.player_id, definition,
                            drop_bonus=(bonuses.drop_rate_multiplier * chasseur_mult * blessed_gear
                                        * (1 + cards.gear_drop_pct / 100)),
                            drop_rate_multiplier=lunar_rewards,
                        )
                        # Essences élémentaires : drop selon la zone (nombre tiré
                        # dans [min, max] pour CE kill) + auto-conversion en
                        # affinité (survivants uniquement, comme le kill).
                        import random as _random
                        essences_min, essences_max = get_essences_range_for_family(definition.family)
                        essence_gains = self._merge_essences(essence_gains, self._award_element_essences(
                            essence_repository=essence_repository,
                            affinity_repository=affinity_repository,
                            progression_service=affinity_progression,
                            player_id=participant.player_id,
                            mob=definition,
                            essences_per_kill=stochastic_round(
                                _random.randint(essences_min, essences_max) * lunar_essences
                                * (1 + cards.essence_pct / 100)),
                            element_override=getattr(state, "element", "") or "",
                            # Chasseur d'essences (pièce épique et plus) : +1 par kill.
                            bonus_essences=essence_hunter,
                        ))

                    # Check titres : kills_family / kills_mob.
                    if definition.family:
                        unlocked += title_unlock_service.check_kills_family(
                            participant.player_id, definition.family
                        )
                    unlocked += title_unlock_service.check_kills_mob(
                        participant.player_id, definition.code,
                    )
                    # Kill : n'importe quel monstre, sa famille, et « à plusieurs »
                    _wqp.on_kill(
                        participant.player_id, definition.family or "", definition.code, count=1,
                        group_size=group_size,
                    )
                    _dqp.on_kill(
                        participant.player_id, definition.family or "", definition.code, count=1,
                        group_size=group_size,
                    )
                unlocked += title_unlock_service.check_kills_total(participant.player_id)
                dropped_items = list(dropped.items())

                # Check titre Intouchable : esquives totales tracées en
                # carrière (career_stats.dodges_total). On lit le total
                # APRÈS l'incrément qu'on vient de faire dans
                # `_record_combat_career_stats`.
                career_after = career_repository.get_or_create(
                    participant.player_id
                )
                unlocked += title_unlock_service.check_dodges_total(
                    participant.player_id, career_after.dodges_total,
                )

                # Titre exclusif Farmer Fou : transfert si le candidat
                # dépasse STRICTEMENT le détenteur actuel (ex aequo ⇒ le
                # premier arrivé garde — comportement décidé côté beta).
                try:
                    excl = ExclusiveTitleService(session)
                    holder_id = excl.current_holder("farmer_fou")
                    candidate_total = kill_repository.get_total_kills(
                        participant.player_id
                    )
                    if holder_id is None and candidate_total > 0:
                        excl.award_to("farmer_fou", participant.player_id)
                    elif holder_id is not None and holder_id != participant.player_id:
                        holder_total = kill_repository.get_total_kills(holder_id)
                        if candidate_total > holder_total:
                            excl.award_to("farmer_fou", participant.player_id)
                except Exception as _e:
                    import logging
                    logging.getLogger(__name__).warning(
                        "Farmer Fou title hook failed: %s", _e, exc_info=True,
                    )

                # Progress quêtes hebdo + quotidiennes (best effort)
                if gold > 0:
                    _wqp.on_gold_earned(participant.player_id, gold)
                    _dqp.on_gold_earned(participant.player_id, gold)
                if xp > 0:
                    _wqp.on_xp_earned(participant.player_id, xp)
                    _dqp.on_xp_earned(participant.player_id, xp)
                # Damage dealt / tanked depuis la contribution combat
                if contribution.damage_dealt > 0:
                    _wqp.on_damage_dealt(
                        participant.player_id, contribution.damage_dealt,
                    )
                    _dqp.on_damage_dealt(
                        participant.player_id, contribution.damage_dealt,
                    )
                if contribution.damage_tanked > 0:
                    _wqp.on_damage_tanked(
                        participant.player_id, contribution.damage_tanked,
                    )
                    _dqp.on_damage_tanked(
                        participant.player_id, contribution.damage_tanked,
                    )
                if contribution.hp_healed > 0:   # soins + boucliers aux alliés
                    _wqp.on_hp_healed(participant.player_id, contribution.hp_healed)
                    _dqp.on_hp_healed(participant.player_id, contribution.hp_healed)

                items_total = 0
                item_names: dict[str, str] = {}
                for item_code, quantity in dropped_items:
                    item = item_repository.get_by_code(item_code)
                    if item is None:
                        continue
                    item_names[item_code] = item.name
                    inventory_repository.add_item(
                        player_id=participant.player_id,
                        item_definition_id=item.id,
                        quantity=quantity,
                    )
                    items_total += quantity
                if items_total > 0:
                    _wqp.on_items_dropped(participant.player_id, items_total)
                    _dqp.on_items_dropped(participant.player_id, items_total)
                # Objets d'événement : hors quêtes de butin (ils ne tombent
                # qu'une semaine, les quêtes ne doivent pas en dépendre).
                for item_code, quantity in festive.items():
                    item = item_repository.get_by_code(item_code)
                    if item is None:
                        continue
                    item_names[item_code] = item.name
                    inventory_repository.add_item(
                        player_id=participant.player_id,
                        item_definition_id=item.id,
                        quantity=quantity,
                    )
                    dropped_items.append((item_code, quantity))

                rewards.append(
                    PlayerReward(
                        player_id=participant.player_id,
                        user_id=participant.user_id,
                        name=participant.display_name,
                        avatar_url=participant.avatar_url,
                        gold=gold,
                        xp=xp,
                        items=dropped_items,
                        item_names=item_names,
                        contribution=contribution,
                        contribution_share=contribution_shares.get(
                            participant.player_id, 0.0
                        ),
                        essence_gains=essence_gains,
                        gear=gear_drop,
                        fusable_gear=self._fusable(session, participant.player_id, gear_drop),
                        titles=[event.title.name for event in unlocked],
                        **growth,
                    )
                )
            self._journal_combat(session, encounter, result, rewards)
            track_fight(session, encounter, result)              # records : exploits

        return BattleSummary(
            outcome="victory",
            mob_name=mob_name,
            mob_image_name=mob.image_name,
            mob_family=mob.family,
            turns=result.turns,
            rewards=rewards,
            base_xp_reward=xp_reward,
            base_gold_reward=gold_reward,
            lunar_note=lunar_note,
            mob_count=size,
        )

    @staticmethod
    def _journal_combat(session, encounter, result, rewards: list[PlayerReward]) -> None:
        """Journal de surveillance : une ligne par participant (issue, durée,
        part du combat, or et XP touchés) — monstres les plus farmés, taux de
        victoire, temps passé par zone, or par heure de jeu."""
        mobs = [s.code for s in (getattr(encounter, "mobs", None) or [encounter.mob_state])]
        lunar = getattr(encounter, "lunar", None)
        channel = getattr(encounter, "channel_id", 0) or None
        started = getattr(encounter, "started_at", None)
        key = f"{channel or 0}:{int(started.timestamp()) if started else 0}"
        for r in rewards:
            c = r.contribution
            res = "loss" if not result.victory else ("win" if c is not None and c.survived else "death")
            data = {"mobs": mobs, "res": res, "n": len(encounter.participants), "turns": result.turns,
                    "enc": key}
            if c is not None:
                data.update(dmg=c.damage_dealt, tank=c.damage_tanked, heal=c.hp_healed,
                            share=round(r.contribution_share or 0, 3))
            if lunar is not None:
                data["lune"] = getattr(lunar, "code", "")
            record_event(session, kinds.COMBAT, player_id=r.player_id, zone=channel, ref=mobs[0],
                         gold=r.gold, xp=r.xp, qty=len(mobs) if res == "win" else 0, data=data)

    @staticmethod
    def _merge_essences(gains: list[EssenceGain], more: list[EssenceGain]) -> list[EssenceGain]:
        """Additionne les gains d'essences de plusieurs monstres (meute) : un
        gain par élément, affinité de départ du premier, d'arrivée du dernier."""
        by_element = {g.element: g for g in gains}
        for g in more:
            prev = by_element.get(g.element)
            by_element[g.element] = g if prev is None else EssenceGain(
                element=g.element,
                essences_gained=prev.essences_gained + g.essences_gained,
                affinity_before=prev.affinity_before,
                affinity_after=g.affinity_after,
            )
        return list(by_element.values())

    @staticmethod
    def _award_element_essences(
        essence_repository: ElementEssenceRepository,
        affinity_repository: ElementAffinityRepository,
        progression_service: ElementAffinityProgressionService,
        player_id: int,
        mob,
        essences_per_kill: int,
        element_override: str = "",
        bonus_essences: int = 0,
    ) -> list[EssenceGain]:
        """Dépose les essences des élément(s) du mob et convertit
        automatiquement en niveaux d'affinité (coût N→N+1 = N+1). Renvoie les
        gains pour affichage dans le récap. Mob neutre → aucun gain.

        `element_override` : élément SPAWNÉ (roulé au spawn) — prioritaire sur
        `mob.element` stocké, pour que les essences correspondent à l'élément
        réellement affiché sur la scène."""
        from app.shared.enums import parse_elements

        elements = parse_elements((element_override or "").strip() or (getattr(mob, "element", "") or ""))
        if not elements or essences_per_kill <= 0:
            return []

        from app.domain.services.element_talent_service import essence_gain

        essences_map = essence_repository.get_essences(player_id)
        affinities_map = affinity_repository.get_affinities(player_id)
        talents = affinity_repository.get_talents(player_id)

        gains: list[EssenceGain] = []
        for elem in elements:
            talent = talents.get(elem)
            # Talent : +10 % d'essences par point ; élément mort ⇒ rien.
            gained = essence_gain(essences_per_kill, talent.talent if talent else 0)
            if gained <= 0:
                continue  # élément mort : même le Chasseur d'essences n'y peut rien
            gained += max(0, bonus_essences)
            before_aff = int(affinities_map.get(elem, 0))
            current_ess = int(essences_map.get(elem, 0))
            conv = progression_service.apply_essences(
                before_aff, current_ess, gained, cap=talent.cap,
            )
            essence_repository.set_essence(player_id, elem, conv.remaining_essences)
            if conv.levels_gained > 0:
                affinity_repository.set_affinity(player_id, elem, conv.new_affinity)
            gains.append(
                EssenceGain(
                    element=elem,
                    essences_gained=gained,
                    affinity_before=before_aff,
                    affinity_after=conv.new_affinity,
                )
            )
        return gains

    @staticmethod
    def _level_of(player_repository, player_id: int) -> int:
        profile = player_repository.get_profile_by_player_id(player_id)
        return profile.progression.level if profile is not None else 1

    @staticmethod
    def _grant_xp(player_repository, player_id: int, xp: int):
        """Applique un gain d'XP en passant par le palier de niveau, et renvoie
        le nouvel état (`LevelUpResult`, None si rien n'a changé) pour que le
        récapitulatif annonce le niveau gagné.

        Mutualisé entre survivants et morts (les morts gagnent l'XP aussi).
        Passe par ProgressionService pour gérer level-up + skill points,
        au lieu d'un `add_xp` brut qui empilerait l'XP au-delà du palier.
        """
        if xp <= 0:
            return None
        profile_after = player_repository.get_profile_by_player_id(player_id)
        if profile_after is None:
            return None
        progression = ProgressionService().apply_level_up(
            current_level=profile_after.progression.level,
            current_xp=profile_after.progression.xp,
            gained_xp=xp,
            current_skill_points=profile_after.progression.skill_points,
            current_stat_points=profile_after.progression.stat_points,
        )
        # ⚠️ Les points de STATS (saison 1) doivent suivre : sans eux, un
        # passage de niveau en combat ne donnait aucun point à placer.
        player_repository.apply_progression(
            player_id=player_id,
            new_level=progression.level,
            new_xp=progression.xp,
            new_skill_points=progression.skill_points,
            new_stat_points=progression.stat_points,
        )
        return progression

    def _record_combat_career_stats(
        self,
        career_repository: PlayerCareerStatsRepository,
        participant,
        contribution,
        won_combat: bool,
    ) -> None:
        """Met à jour les stats cumulées d'un participant après un combat.

        combats_fought : +1 systématique (a participé)
        combats_won    : +1 si le joueur a survécu à une victoire (won_combat=True)
        combats_lost   : +1 sinon (mort en combat OU défaite de l'équipe)
        damage_*, hp_healed : valeurs absolues du PlayerContribution si présent.
        """
        damage_dealt = contribution.damage_dealt if contribution else 0
        damage_tanked = contribution.damage_tanked if contribution else 0
        hp_healed = contribution.hp_healed if contribution else 0
        dodges = getattr(contribution, "dodges", 0) if contribution else 0

        career_repository.add(
            participant.player_id,
            damage_dealt=damage_dealt,
            damage_tanked=damage_tanked,
            hp_healed=hp_healed,
            dodges=dodges,
            combats_fought=1,
            combats_won=1 if won_combat else 0,
            combats_lost=0 if won_combat else 1,
        )
