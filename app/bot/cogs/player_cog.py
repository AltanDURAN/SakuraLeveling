import asyncio

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, UTC

from app.domain.entities.player_profile import PlayerProfile
from app.shared.formatters import format_int as _format_int
from app.application.use_cases.change_player_class import ChangePlayerClassUseCase
from app.application.use_cases.transfer_gold import TransferGoldUseCase
from app.application.use_cases.claim_daily_reward import ClaimDailyRewardUseCase
from app.application.use_cases.challenge_player import ChallengePlayerUseCase
from app.application.use_cases.craft_item import CraftItemUseCase
from app.application.use_cases.gather_resource import GatherResourceUseCase
from app.application.use_cases.use_consumable import UseConsumableUseCase
from app.application.use_cases.get_available_classes import GetAvailableClassesUseCase
from app.application.use_cases.get_available_crafts import GetAvailableCraftsUseCase
from app.application.use_cases.get_player_class import GetPlayerClassUseCase
from app.application.use_cases.get_player_equipment import GetPlayerEquipmentUseCase
from app.application.use_cases.equip_item import EquipItemUseCase
from app.application.use_cases.get_player_inventory import GetPlayerInventoryUseCase
from app.application.use_cases.get_player_profile import GetPlayerProfileUseCase
from app.application.use_cases.get_player_stats import GetPlayerStatsUseCase
from app.bot.embeds.duel_embeds import (
    build_duel_intro_embed,
    build_duel_result_embed,
    build_duel_turn_embed,
)
from app.bot.embeds.class_embeds import build_player_class_embed
from app.bot.embeds.daily_embeds import (
    build_daily_cooldown_embed,
    build_daily_success_embed,
)
from app.bot.views.equipment_view import EquipmentView
from app.bot.views.inventory_view import InventoryView
from app.bot.embeds.craft_embeds import FORGE_CATEGORIES, build_craft_list_embed
from app.bot.views.recipe_list_view import RecipeListView
from app.bot.embeds.inventory_embeds import build_inventory_embed
from app.bot.embeds.player_embeds import build_player_profile_embed
from app.domain.services.class_service import ClassService
from app.domain.services.cooldown_service import CooldownService
from app.domain.services.craft_service import CraftService
from app.domain.services.duel_combat_service import DuelCombatService
from app.domain.services.profession_service import ProfessionService
from app.domain.services.stats_service import StatsService
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.craft_repository import CraftRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_duel_rank_repository import (
    PlayerDuelRankRepository,
)
from app.infrastructure.db.repositories.player_kill_repository import PlayerKillRepository
from app.infrastructure.db.repositories.player_career_stats_repository import (
    PlayerCareerStatsRepository,
)
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.skill_tree.skill_tree_loader import (
    get_definition as get_skill_tree_definition,
)
from app.domain.services.skill_tree_service import SkillTreeService
from app.infrastructure.db.repositories.profession_repository import ProfessionRepository
from app.infrastructure.db.session import get_db_session
from app.shared.enums import EquipmentSlot
from app.domain.services.health_regeneration_service import HealthRegenerationService
from app.infrastructure.db.repositories.player_health_repository import PlayerHealthRepository
from app.domain.services.power_score_service import PowerScoreService


class PlayerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _resolve_profile(
        self,
        interaction: discord.Interaction,
        target: discord.Member | None,
        session,
    ) -> tuple[PlayerProfile | None, discord.abc.User]:
        """Renvoie (profile, target_member). Si target est None, get_or_create
        le profil de l'auteur. Si target est spécifié, lookup pur (pas de
        création). Le profil est None si target n'a jamais joué."""
        repo = PlayerRepository(session)

        if target is None:
            target_member = interaction.user
            profile = repo.get_or_create_by_discord_id(
                discord_id=target_member.id,
                username=target_member.name,
                display_name=target_member.display_name,
            )
        else:
            target_member = target
            profile = repo.get_by_discord_id(target_member.id)

        return profile, target_member

    async def _send_no_profile_error(
        self,
        interaction: discord.Interaction,
        target_member,
    ) -> None:
        message = (
            f"❌ {target_member.display_name} n'a pas encore de profil joueur."
        )
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.channel_id != settings.beta_channel_id:
            if interaction.response.is_done():
                await interaction.followup.send(
                    "🚧 Le bot est actuellement en phase de test.\nUtilisez le channel beta dédié.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "🚧 Le bot est actuellement en phase de test.\nUtilisez le channel beta dédié.",
                    ephemeral=True,
                )
            return False

        return True

    @app_commands.command(name="ping", description="Vérifier si le bot fonctionne")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("🏓 Pong !")

    @app_commands.command(name="profile", description="Afficher un profil joueur")
    @app_commands.describe(target="Joueur dont afficher le profil (par défaut : vous)")
    async def profile(
        self,
        interaction: discord.Interaction,
        target: discord.Member | None = None,
    ) -> None:
        with get_db_session() as session:
            profile, target_member = self._resolve_profile(interaction, target, session)
            if profile is None:
                await self._send_no_profile_error(interaction, target_member)
                return

            equipment_repository = EquipmentRepository(session)
            class_repository = ClassRepository(session)
            player_health_repository = PlayerHealthRepository(session)
            kill_repository = PlayerKillRepository(session)
            career_stats_repository = PlayerCareerStatsRepository(session)
            skill_allocation_repository = PlayerSkillAllocationRepository(session)

            equipped_items = equipment_repository.list_by_player_id(profile.player.id)
            active_class = class_repository.get_current_class_for_player(profile.player.id)
            allocations = skill_allocation_repository.list_by_player(profile.player.id)
            skill_bonuses = SkillTreeService(get_skill_tree_definition()).aggregate_bonuses(
                allocations
            )
            from app.application.services.title_bonus_resolver import (
                resolve_title_bonuses,
            )
            title_bonuses = resolve_title_bonuses(session, profile.player.id)
            stats = StatsService().calculate_player_stats(
                profile=profile,
                equipped_items=equipped_items,
                active_class=active_class,
                skill_bonuses=skill_bonuses,
                title_bonuses=title_bonuses,
            )

            power_score_service = PowerScoreService()
            raw_power_score = power_score_service.calculate_from_stats(stats)
            formatted_power_score = power_score_service.format_score(raw_power_score)
            rank_label = power_score_service.compute_rank(raw_power_score)

            health_state = player_health_repository.get_or_create(
                player_id=profile.player.id,
                default_current_hp=stats.max_hp,
            )

            now = datetime.now(UTC)
            regenerated_current_hp = HealthRegenerationService().apply_out_of_combat_regeneration(
                current_hp=health_state.current_hp,
                max_hp=stats.max_hp,
                hp_regeneration=stats.hp_regeneration,
                last_updated_at=health_state.updated_at,
                now=now,
            )

            # On ne persiste la régénération que pour soi-même : éviter d'écrire
            # sur le profil d'un tiers en simple consultation.
            if regenerated_current_hp != health_state.current_hp and target is None:
                player_health_repository.refresh_current_hp(
                    player_id=profile.player.id,
                    new_current_hp=regenerated_current_hp,
                )

            total_kills = kill_repository.get_total_kills(profile.player.id)
            career_stats = career_stats_repository.get_or_create(profile.player.id)

            duel_rank = PlayerDuelRankRepository(session).get_by_player_id(
                profile.player.id
            )

            from app.infrastructure.db.repositories.player_title_repository import (
                PlayerTitleRepository,
            )
            from app.infrastructure.titles.title_loader import get_definition as _get_title_def

            active_title_code = PlayerTitleRepository(session).get_active_title_code(
                profile.player.id
            )
            active_title_name: str | None = None
            if active_title_code:
                title_def = _get_title_def(active_title_code)
                if title_def is not None:
                    active_title_name = f"{title_def.icon} {title_def.name}"

        embed = build_player_profile_embed(
            profile=profile,
            stats=stats,
            active_class=active_class,
            current_hp=regenerated_current_hp,
            power_score=formatted_power_score,
            rank_label=rank_label,
            total_kills=total_kills,
            career_stats=career_stats,
            duel_rank_position=duel_rank.rank_position if duel_rank else None,
            duel_wins=duel_rank.wins if duel_rank else 0,
            duel_losses=duel_rank.losses if duel_rank else 0,
            active_title=active_title_name,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="inventory", description="Afficher un inventaire")
    @app_commands.describe(target="Joueur dont afficher l'inventaire (par défaut : vous)")
    async def inventory(
        self,
        interaction: discord.Interaction,
        target: discord.Member | None = None,
    ) -> None:
        with get_db_session() as session:
            profile, target_member = self._resolve_profile(interaction, target, session)
            if profile is None:
                await self._send_no_profile_error(interaction, target_member)
                return

            inventory_repository = InventoryRepository(session)
            items = inventory_repository.list_by_player_id(profile.player.id)

        view = InventoryView(target_member.display_name, items)
        await interaction.response.send_message(embed=view._build_embed(), view=view)

    @app_commands.command(name="equipement", description="Afficher un équipement (12 slots, 2 pages)")
    @app_commands.describe(target="Joueur dont afficher l'équipement (par défaut : vous)")
    async def equipment(
        self,
        interaction: discord.Interaction,
        target: discord.Member | None = None,
    ) -> None:
        with get_db_session() as session:
            profile, target_member = self._resolve_profile(interaction, target, session)
            if profile is None:
                await self._send_no_profile_error(interaction, target_member)
                return

            equipment_repository = EquipmentRepository(session)
            equipment_items = equipment_repository.list_by_player_id(profile.player.id)

        view = EquipmentView(
            target_name=target_member.display_name,
            equipped_items=equipment_items,
            timeout=600.0,
        )
        await interaction.response.send_message(embed=view.current_embed, view=view)

    @app_commands.command(
        name="equipement_list",
        description="Liste les équipements possédés par catégorie (équipés ou non)",
    )
    @app_commands.describe(target="Joueur ciblé (par défaut : vous)")
    async def equipement_list(
        self,
        interaction: discord.Interaction,
        target: discord.Member | None = None,
    ) -> None:
        from app.bot.views.equipement_list_view import EquipementListView

        with get_db_session() as session:
            profile, target_member = self._resolve_profile(interaction, target, session)
            if profile is None:
                await self._send_no_profile_error(interaction, target_member)
                return

            inventory_repository = InventoryRepository(session)
            equipment_repository = EquipmentRepository(session)
            items = inventory_repository.list_by_player_id(profile.player.id)
            equipped = equipment_repository.list_by_player_id(profile.player.id)

        view = EquipementListView(
            display_name=target_member.display_name,
            items=items,
            equipped=equipped,
        )
        await interaction.response.send_message(
            embed=view._build_embed(), view=view,
        )

    @app_commands.command(name="equip", description="Équiper un item depuis votre inventaire")
    @app_commands.describe(item_code="Code de l'item (autocomplete sur votre inventaire)")
    async def equip(
        self,
        interaction: discord.Interaction,
        item_code: str,
    ) -> None:
        from app.bot.views.equip_confirm_view import (
            EquipConfirmView,
            build_equip_confirm_embed,
            compute_stats_diff,
        )
        from app.domain.entities.player_equipment_item import PlayerEquipmentItem

        with get_db_session() as session:
            profile = PlayerRepository(session).get_or_create_by_discord_id(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )
            inventory_repository = InventoryRepository(session)
            equipment_repository = EquipmentRepository(session)
            class_repository = ClassRepository(session)
            skill_alloc_repo = PlayerSkillAllocationRepository(session)

            inventory_items = inventory_repository.list_by_player_id(profile.player.id)
            matched = next(
                (i for i in inventory_items if i.item_definition.code == item_code),
                None,
            )
            if matched is None:
                await interaction.response.send_message(
                    f"❌ L'item `{item_code}` n'est pas dans votre inventaire.",
                    ephemeral=True,
                )
                return
            if not matched.item_definition.is_equipable:
                await interaction.response.send_message(
                    f"❌ **{matched.item_definition.name}** n'est pas équipable.",
                    ephemeral=True,
                )
                return

            current_equipment = equipment_repository.list_by_player_id(profile.player.id)

            # Auto-pick du slot pour les armes 1-main : on choisit le slot
            # libre (main_droite prioritaire) sans demander à l'utilisateur.
            # Pour les autres items : slot canonique de la définition.
            item_def = matched.item_definition
            from app.shared.enums import EquipmentSlot as _ES
            _hand_slots = {_ES.MAIN_HAND.value, _ES.OFF_HAND.value}
            is_hand_weapon = (
                item_def.equipment_slot in _hand_slots
                and not item_def.requires_two_hands
            )
            if is_hand_weapon:
                md_occupied = next(
                    (e for e in current_equipment if e.slot == _ES.MAIN_HAND.value),
                    None,
                )
                mg_occupied = next(
                    (e for e in current_equipment if e.slot == _ES.OFF_HAND.value),
                    None,
                )
                if md_occupied is None:
                    target_slot = _ES.MAIN_HAND.value
                elif mg_occupied is None:
                    target_slot = _ES.OFF_HAND.value
                else:
                    target_slot = _ES.MAIN_HAND.value
            else:
                target_slot = item_def.equipment_slot

            current_in_slot = next(
                (e for e in current_equipment if e.slot == target_slot), None
            )

            # Si le slot est vide ou occupé par le même item, équipe directement.
            if (
                current_in_slot is None
                or current_in_slot.item_definition.id == matched.item_definition.id
            ):
                use_case = EquipItemUseCase(
                    player_repository=PlayerRepository(session),
                    inventory_repository=inventory_repository,
                    equipment_repository=equipment_repository,
                )
                result = use_case.execute(
                    discord_id=interaction.user.id,
                    username=interaction.user.name,
                    display_name=interaction.user.display_name,
                    item_code=item_code,
                )
                if not result.success:
                    await interaction.response.send_message(
                        result.message, ephemeral=True
                    )
                    return
                msg = result.message
                if result.unequipped_items:
                    msg += f"\n_Déséquipé : {', '.join(result.unequipped_items)}._"
                await interaction.response.send_message(msg)
                return

            # Sinon : un autre item est déjà dans le slot → calcule diff
            active_class = class_repository.get_current_class_for_player(profile.player.id)
            allocations = skill_alloc_repo.list_by_player(profile.player.id)
            skill_bonuses = SkillTreeService(get_skill_tree_definition()).aggregate_bonuses(
                allocations
            )

            current_stats = StatsService().calculate_player_stats(
                profile=profile,
                equipped_items=current_equipment,
                active_class=active_class,
                skill_bonuses=skill_bonuses,
            )
            # Simule la nouvelle config : retirer l'occupant du slot, ajouter
            # le nouvel item. Pas de persistence — juste un objet domain.
            simulated_new = PlayerEquipmentItem(
                id=-1,
                player_id=profile.player.id,
                slot=target_slot,
                item_definition=matched.item_definition,
                created_at=current_in_slot.created_at,
                updated_at=current_in_slot.updated_at,
            )
            simulated = [
                e for e in current_equipment if e.slot != target_slot
            ] + [simulated_new]
            new_stats = StatsService().calculate_player_stats(
                profile=profile,
                equipped_items=simulated,
                active_class=active_class,
                skill_bonuses=skill_bonuses,
            )

            current_in_slot_name = current_in_slot.item_definition.name
            matched_name = matched.item_definition.name

        diffs = compute_stats_diff(current_stats, new_stats)
        embed = build_equip_confirm_embed(
            item_name=matched_name,
            slot=target_slot,
            replacing_name=current_in_slot_name,
            diffs=diffs,
        )
        view = EquipConfirmView(
            author_id=interaction.user.id,
            discord_id=interaction.user.id,
            username=interaction.user.name,
            display_name=interaction.user.display_name,
            item_code=item_code,
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @equip.autocomplete("item_code")
    async def equip_item_code_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Propose les items équipables en inventaire, en excluant ceux qui
        sont DÉJÀ équipés (par item_definition_id) — évite la confusion
        d'avoir un même item proposé alors qu'il est déjà porté."""
        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            profile = player_repository.get_by_discord_id(interaction.user.id)
            if profile is None:
                return []

            inventory_repository = InventoryRepository(session)
            equipment_repository = EquipmentRepository(session)
            items = inventory_repository.list_by_player_id(profile.player.id)
            equipped_ids = {
                e.item_definition.id
                for e in equipment_repository.list_by_player_id(profile.player.id)
            }

        current_lower = current.lower()
        choices: list[app_commands.Choice[str]] = []
        for item in items:
            definition = item.item_definition
            if not definition.is_equipable:
                continue
            # Filtre : ne propose pas un item déjà équipé (même définition)
            if definition.id in equipped_ids:
                continue
            label = f"{definition.name} ({definition.equipment_slot})"[:100]
            if (
                current_lower in definition.code.lower()
                or current_lower in definition.name.lower()
            ):
                choices.append(
                    app_commands.Choice(name=label, value=definition.code)
                )
            if len(choices) >= 25:
                break
        return choices

    @app_commands.command(
        name="unequip",
        description="Déséquiper un emplacement (laisse-le vide, sans rééquiper)",
    )
    @app_commands.describe(slot="Emplacement à vider (autocomplete : seulement ceux occupés)")
    async def unequip(
        self,
        interaction: discord.Interaction,
        slot: str,
    ) -> None:
        with get_db_session() as session:
            profile = PlayerRepository(session).get_or_create_by_discord_id(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )
            equipment_repository = EquipmentRepository(session)
            current = equipment_repository.get_slot(profile.player.id, slot)
            if current is None:
                await interaction.response.send_message(
                    f"❌ Aucun équipement dans `{slot}`.",
                    ephemeral=True,
                )
                return

            item_name = current.item_definition.name
            was_two_hands = bool(current.item_definition.requires_two_hands)
            equipment_repository.unequip_slot(profile.player.id, slot)

        msg = f"✅ **{item_name}** déséquipé de `{slot}`."
        if was_two_hands:
            msg += "\n_(Arme à 2 mains : `main_gauche` est de nouveau libre.)_"
        await interaction.response.send_message(msg)

    @unequip.autocomplete("slot")
    async def unequip_slot_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Liste uniquement les slots actuellement occupés du joueur,
        avec le nom de l'item porté pour rendre le choix explicite."""
        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(interaction.user.id)
            if profile is None:
                return []

            equipped = EquipmentRepository(session).list_by_player_id(profile.player.id)

        current_lower = current.lower()
        choices: list[app_commands.Choice[str]] = []
        for entry in equipped:
            label = f"{entry.slot} — {entry.item_definition.name}"[:100]
            if current_lower and current_lower not in entry.slot.lower():
                continue
            choices.append(app_commands.Choice(name=label, value=entry.slot))
            if len(choices) >= 25:
                break
        return choices

    @app_commands.command(
        name="fight",
        description="Défier un autre joueur en duel 1v1 (PvP, sans gain ni perte)",
    )
    @app_commands.describe(target="Joueur à défier")
    async def fight(self, interaction: discord.Interaction, target: discord.Member) -> None:
        if target.bot:
            await interaction.response.send_message(
                "❌ Vous ne pouvez pas défier un bot.",
                ephemeral=True,
            )
            return
        if target.id == interaction.user.id:
            await interaction.response.send_message(
                "❌ Vous ne pouvez pas vous défier vous-même.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        with get_db_session() as session:
            use_case = ChallengePlayerUseCase(
                player_repository=PlayerRepository(session),
                equipment_repository=EquipmentRepository(session),
                class_repository=ClassRepository(session),
                skill_allocation_repository=PlayerSkillAllocationRepository(session),
                duel_rank_repository=PlayerDuelRankRepository(session),
                cooldown_repository=CooldownRepository(session),
                stats_service=StatsService(),
                duel_combat_service=DuelCombatService(),
                cooldown_service=CooldownService(),
            )
            outcome = use_case.execute(
                challenger_discord_id=interaction.user.id,
                challenger_username=interaction.user.name,
                challenger_display_name=interaction.user.display_name,
                target_discord_id=target.id,
                target_display_name=target.display_name,
            )

        if not outcome.success or outcome.result is None:
            await interaction.followup.send(outcome.message, ephemeral=True)
            return

        challenger_name = outcome.challenger_display_name
        target_name = outcome.target_display_name
        result = outcome.result

        intro = build_duel_intro_embed(
            challenger_name=challenger_name,
            target_name=target_name,
            challenger_max_hp=result.a_max_hp,
            target_max_hp=result.b_max_hp,
        )
        message = await interaction.followup.send(
            content=f"⚔️ {interaction.user.mention} défie {target.mention} !",
            embed=intro,
        )

        await asyncio.sleep(1.5)
        for turn_log in result.turn_logs:
            embed = build_duel_turn_embed(
                challenger_name=challenger_name,
                target_name=target_name,
                result=result,
                turn_log=turn_log,
            )
            await message.edit(embed=embed)
            await asyncio.sleep(1.2)

        final_embed = build_duel_result_embed(
            challenger_name=challenger_name,
            target_name=target_name,
            result=result,
            challenger_won=outcome.challenger_won,
            swapped=outcome.swapped,
            challenger_old_position=outcome.challenger_old_position,
            target_old_position=outcome.target_old_position,
            challenger_new_position=outcome.challenger_new_position,
            target_new_position=outcome.target_new_position,
        )
        await message.edit(embed=final_embed)

    @app_commands.command(name="class", description="Afficher la classe active d'un joueur")
    @app_commands.describe(target="Joueur dont afficher la classe (par défaut : vous)")
    async def player_class(
        self,
        interaction: discord.Interaction,
        target: discord.Member | None = None,
    ) -> None:
        with get_db_session() as session:
            profile, target_member = self._resolve_profile(interaction, target, session)
            if profile is None:
                await self._send_no_profile_error(interaction, target_member)
                return

            class_repository = ClassRepository(session)
            class_repository.get_or_create_player_class_state(profile.player.id)
            active_class = class_repository.get_current_class_for_player(profile.player.id)

        embed = build_player_class_embed(target_member.display_name, active_class)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="class_set", description="Définir votre classe active")
    @app_commands.describe(class_code="Code technique de la classe")
    async def class_set(self, interaction: discord.Interaction, class_code: str) -> None:
        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            class_repository = ClassRepository(session)
            profession_repository = ProfessionRepository(session)
            inventory_repository = InventoryRepository(session)

            use_case = ChangePlayerClassUseCase(
                player_repository=player_repository,
                class_repository=class_repository,
                profession_repository=profession_repository,
                inventory_repository=inventory_repository,
                class_service=ClassService(),
            )

            success, message = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
                class_code=class_code,
            )

        await interaction.response.send_message(message, ephemeral=not success)

    @app_commands.command(
        name="craft_list",
        description="Liste les recettes d'accessoires (collier, bague, ceinture, cape…)",
    )
    async def craft_list(self, interaction: discord.Interaction) -> None:
        await self._send_recipe_list(
            interaction,
            include_categories=None,
            exclude_categories=FORGE_CATEGORIES,
            title="🛠️ Recettes — Atelier",
            color=discord.Color.orange(),
        )

    @app_commands.command(
        name="forge_list",
        description="Liste les recettes d'armes, boucliers et armures (à forger)",
    )
    async def forge_list(self, interaction: discord.Interaction) -> None:
        await self._send_recipe_list(
            interaction,
            include_categories=FORGE_CATEGORIES,
            exclude_categories=None,
            title="🔥 Recettes — Forge",
            color=discord.Color.red(),
        )

    async def _send_recipe_list(
        self,
        interaction: discord.Interaction,
        include_categories: set[str] | None,
        exclude_categories: set[str] | None,
        title: str,
        color: discord.Color,
    ) -> None:
        with get_db_session() as session:
            craft_repository = CraftRepository(session)
            item_repository = ItemRepository(session)
            recipes = craft_repository.list_all()
            all_items = item_repository.list_all()

        item_lookup = {item.code: item for item in all_items}

        def _matches(recipe) -> bool:
            result = item_lookup.get(recipe.result_item_code)
            if result is None:
                return False
            if include_categories is not None and result.category not in include_categories:
                return False
            if exclude_categories is not None and result.category in exclude_categories:
                return False
            return True

        filtered = [r for r in recipes if _matches(r)]
        view = RecipeListView(
            recipes=filtered,
            item_lookup=item_lookup,
            title_prefix=title,
            color=color,
        )
        await interaction.response.send_message(
            embed=view._build_embed(), view=view,
        )

    @app_commands.command(name="craft", description="Fabriquer un objet (équipement / accessoire)")
    @app_commands.describe(recipe_code="Code de la recette (autocomplete)")
    async def craft(self, interaction: discord.Interaction, recipe_code: str) -> None:
        await self._execute_craft(
            interaction, recipe_code, expect_weapon=False
        )

    @app_commands.command(name="forge", description="Forger une arme ou un bouclier")
    @app_commands.describe(recipe_code="Code de la recette (autocomplete sur armes/boucliers)")
    async def forge(self, interaction: discord.Interaction, recipe_code: str) -> None:
        await self._execute_craft(
            interaction, recipe_code, expect_weapon=True
        )

    async def _execute_craft(
        self,
        interaction: discord.Interaction,
        recipe_code: str,
        expect_weapon: bool,
    ) -> None:
        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            craft_repository = CraftRepository(session)
            inventory_repository = InventoryRepository(session)
            item_repository = ItemRepository(session)

            recipe = craft_repository.get_by_code(recipe_code)
            if recipe is None:
                await interaction.response.send_message(
                    f"❌ Recette `{recipe_code}` introuvable.",
                    ephemeral=True,
                )
                return

            result_item = item_repository.get_by_code(recipe.result_item_code)
            if result_item is None:
                await interaction.response.send_message(
                    "❌ Objet de résultat introuvable (config invalide).",
                    ephemeral=True,
                )
                return

            is_forgeable = result_item.category in FORGE_CATEGORIES
            if expect_weapon and not is_forgeable:
                await interaction.response.send_message(
                    f"❌ **{result_item.name}** ne se forge pas : utilisez `/craft` à la place.",
                    ephemeral=True,
                )
                return
            if not expect_weapon and is_forgeable:
                await interaction.response.send_message(
                    f"❌ **{result_item.name}** se forge : utilisez `/forge` à la place.",
                    ephemeral=True,
                )
                return

            use_case = CraftItemUseCase(
                player_repository=player_repository,
                craft_repository=craft_repository,
                inventory_repository=inventory_repository,
                item_repository=item_repository,
                craft_service=CraftService(),
            )

            craft_outcome = use_case.execute_detailed(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
                recipe_code=recipe_code,
            )

        if not craft_outcome.success:
            # Si on a la liste des ingrédients manquants, on affiche le détail
            if craft_outcome.missing_ingredients:
                lines = []
                # Affiche TOUS les ingrédients (avec leur statut), pas juste les
                # manquants, pour que le joueur voie aussi ce qu'il a déjà.
                # missing_ingredients ne contient que les manquants → on
                # complète avec ceux fulfilled. Plus simple : on re-check via
                # le service ici.
                from app.domain.services.craft_service import CraftService as _CS
                with get_db_session() as session2:
                    inv2 = InventoryRepository(session2).list_by_player_id(
                        PlayerRepository(session2).get_by_discord_id(
                            interaction.user.id
                        ).player.id
                    )
                    recipe2 = CraftRepository(session2).get_by_code(recipe_code)
                check2 = _CS().check_requirements(recipe2, inv2)
                for ing in check2.ingredients:
                    if ing.fulfilled:
                        lines.append(f"✅ {ing.item_name} : **{ing.owned}/{ing.required}**")
                    else:
                        lines.append(
                            f"❌ {ing.item_name} : **{ing.owned}/{ing.required}** "
                            f"(manque {ing.missing})"
                        )
                msg = (
                    f"{craft_outcome.message}\n\n**Ingrédients :**\n"
                    + "\n".join(lines)
                )
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.response.send_message(
                    craft_outcome.message, ephemeral=True
                )
            return

        verb = "Forgé" if expect_weapon else "Fabriqué"
        await interaction.response.send_message(
            f"✅ {verb} : **{result_item.name}** est ajouté à votre inventaire."
        )

    @craft.autocomplete("recipe_code")
    async def craft_recipe_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return await self._recipe_autocomplete(
            current, weapons_only=False
        )

    @forge.autocomplete("recipe_code")
    async def forge_recipe_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return await self._recipe_autocomplete(
            current, weapons_only=True
        )

    async def _recipe_autocomplete(
        self,
        current: str,
        weapons_only: bool,
    ) -> list[app_commands.Choice[str]]:
        with get_db_session() as session:
            recipes = CraftRepository(session).list_all()
            items = {item.code: item for item in ItemRepository(session).list_all()}

        current_lower = current.lower()
        choices: list[app_commands.Choice[str]] = []
        for recipe in recipes:
            result = items.get(recipe.result_item_code)
            if result is None:
                continue
            is_forgeable = result.category in FORGE_CATEGORIES
            if weapons_only and not is_forgeable:
                continue
            if not weapons_only and is_forgeable:
                continue
            label = f"{result.name} ({recipe.code})"[:100]
            if (
                current_lower in recipe.code.lower()
                or current_lower in result.name.lower()
            ):
                choices.append(app_commands.Choice(name=label, value=recipe.code))
            if len(choices) >= 25:
                break
        return choices

    @app_commands.command(
        name="pay",
        description="Envoyer de l'or à un autre joueur",
    )
    @app_commands.describe(
        target="Joueur destinataire",
        amount="Montant à envoyer (>= 1)",
    )
    async def pay(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        amount: app_commands.Range[int, 1, 1_000_000_000],
    ) -> None:
        if target.bot:
            await interaction.response.send_message(
                "❌ Vous ne pouvez pas envoyer d'or à un bot.",
                ephemeral=True,
            )
            return

        with get_db_session() as session:
            use_case = TransferGoldUseCase(PlayerRepository(session))
            result = use_case.execute(
                sender_discord_id=interaction.user.id,
                sender_username=interaction.user.name,
                sender_display_name=interaction.user.display_name,
                receiver_discord_id=target.id,
                receiver_display_name=target.display_name,
                amount=amount,
            )

        if not result.success:
            await interaction.response.send_message(result.message, ephemeral=True)
            return

        await interaction.response.send_message(
            f"💸 {interaction.user.mention} a envoyé **{amount}** or à {target.mention}.\n"
            f"_Votre solde : {result.sender_balance_after} or._"
        )

    @app_commands.command(
        name="use",
        description="Utiliser un consommable de votre inventaire (potion, etc.)",
    )
    @app_commands.describe(item_code="Code du consommable (autocomplete sur votre inventaire)")
    async def use(self, interaction: discord.Interaction, item_code: str) -> None:
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            use_case = UseConsumableUseCase(
                player_repository=PlayerRepository(session),
                item_repository=ItemRepository(session),
                inventory_repository=InventoryRepository(session),
                equipment_repository=EquipmentRepository(session),
                class_repository=ClassRepository(session),
                skill_allocation_repository=PlayerSkillAllocationRepository(session),
                health_repository=PlayerHealthRepository(session),
                stats_service=StatsService(),
            )
            result = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
                item_code=item_code,
            )
        await interaction.followup.send(result.message, ephemeral=True)

    @use.autocomplete("item_code")
    async def use_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete sur les consommables actuellement en inventaire."""
        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(interaction.user.id)
            if profile is None:
                return []
            inventory = InventoryRepository(session).list_by_player_id(profile.player.id)
        current_lower = current.lower()
        choices: list[app_commands.Choice[str]] = []
        for inv_item in inventory:
            item = inv_item.item_definition
            if item.category != "consumable":
                continue
            if (
                current_lower in item.code.lower()
                or current_lower in item.name.lower()
            ):
                choices.append(
                    app_commands.Choice(
                        name=f"{item.name} (×{inv_item.quantity})",
                        value=item.code,
                    )
                )
            if len(choices) >= 25:
                break
        return choices

    @app_commands.command(
        name="gold",
        description="Voir votre or (ou celui d'un autre joueur)",
    )
    @app_commands.describe(target="Joueur ciblé (par défaut : vous)")
    async def gold(
        self,
        interaction: discord.Interaction,
        target: discord.Member | None = None,
    ) -> None:
        with get_db_session() as session:
            profile, target_member = self._resolve_profile(interaction, target, session)
            if profile is None:
                await self._send_no_profile_error(interaction, target_member)
                return

            gold_amount = profile.resources.gold
            career_gold = 0
            try:
                career = PlayerCareerStatsRepository(session).get_or_create(
                    profile.player.id
                )
                career_gold = int(getattr(career, "gold_earned_total", 0) or 0)
            except Exception:
                career_gold = 0

        is_self = target_member.id == interaction.user.id
        title = "💰 Votre bourse" if is_self else f"💰 Bourse de {target_member.display_name}"

        embed = discord.Embed(
            title=title,
            color=discord.Color.gold(),
        )
        embed.set_thumbnail(url=target_member.display_avatar.url)
        embed.add_field(
            name="Or actuel",
            value=f"🪙 **{_format_int(gold_amount)}**",
            inline=False,
        )
        if career_gold > 0:
            embed.add_field(
                name="Or amassé (carrière)",
                value=f"📊 {_format_int(career_gold)}",
                inline=False,
            )
        embed.set_footer(text=f"Joueur : {target_member.display_name}")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="daily", description="Récupérer votre récompense quotidienne")
    async def daily(self, interaction: discord.Interaction) -> None:
        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            cooldown_repository = CooldownRepository(session)

            use_case = ClaimDailyRewardUseCase(
                player_repository=player_repository,
                cooldown_repository=cooldown_repository,
                cooldown_service=CooldownService(),
                career_stats_repository=PlayerCareerStatsRepository(session),
            )

            result = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )

        if result.success:
            embed = build_daily_success_embed(
                streak=result.streak,
                gold_gained=result.gold_gained,
                bonus_items=result.bonus_items,
            )
            await interaction.response.send_message(embed=embed)
        else:
            embed = build_daily_cooldown_embed(
                streak=result.streak,
                next_available_at=result.next_available_at,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="gather", description="Récolter des ressources")
    @app_commands.describe(profession_code="Code du métier")
    async def gather(self, interaction: discord.Interaction, profession_code: str):
        with get_db_session() as session:
            use_case = GatherResourceUseCase(
                player_repository=PlayerRepository(session),
                profession_repository=ProfessionRepository(session),
                inventory_repository=InventoryRepository(session),
                item_repository=ItemRepository(session),
                profession_service=ProfessionService(),
            )

            success, message = use_case.execute(
                interaction.user.id,
                interaction.user.name,
                interaction.user.display_name,
                profession_code,
            )

        await interaction.response.send_message(message, ephemeral=not success)

    @app_commands.command(name="classes", description="Afficher les classes disponibles et leur état")
    async def classes(self, interaction: discord.Interaction) -> None:
        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            class_repository = ClassRepository(session)
            profession_repository = ProfessionRepository(session)
            inventory_repository = InventoryRepository(session)

            use_case = GetAvailableClassesUseCase(
                player_repository=player_repository,
                class_repository=class_repository,
                profession_repository=profession_repository,
                inventory_repository=inventory_repository,
                class_service=ClassService(),
            )

            class_entries = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )

        embed = discord.Embed(
            title=f"🧬 Classes de {interaction.user.display_name}",
            color=discord.Color.dark_gold(),
        )

        if not class_entries:
            embed.description = "Aucune classe disponible."
        else:
            lines = []
            for entry in class_entries:
                class_definition = entry["class_definition"]
                unlocked = entry["unlocked"]
                status = "✅ Débloquée" if unlocked else "🔒 Verrouillée"

                requirements = class_definition.unlock_requirements or []
                if requirements:
                    requirement_lines = []
                    for requirement in requirements:
                        requirement_type = requirement.get("type")

                        if requirement_type == "profession_level":
                            requirement_lines.append(
                                f"Métier {requirement['profession_code']} niveau {requirement['level']}"
                            )
                        elif requirement_type == "has_item":
                            requirement_lines.append(
                                f"{requirement['item_code']} x{requirement['quantity']}"
                            )

                    requirement_text = " | ".join(requirement_lines)
                else:
                    requirement_text = "Aucune condition"

                lines.append(
                    f"**{class_definition.code}** — {class_definition.name}\n"
                    f"{class_definition.description}\n"
                    f"{status}\n"
                    f"Conditions : {requirement_text}"
                )

            embed.description = "\n\n".join(lines)

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PlayerCog(bot))