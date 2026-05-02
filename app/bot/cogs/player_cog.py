import asyncio

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, UTC

from app.bot.checks.admin_check import admin_only
from app.domain.entities.player_profile import PlayerProfile
from app.application.use_cases.change_player_class import ChangePlayerClassUseCase
from app.application.use_cases.transfer_gold import TransferGoldUseCase
from app.application.use_cases.claim_daily_reward import ClaimDailyRewardUseCase
from app.application.use_cases.claim_quest_reward import ClaimQuestRewardUseCase
from app.application.use_cases.craft_item import CraftItemUseCase
from app.application.use_cases.fight_mob import FightMobUseCase
from app.application.use_cases.gather_resource import GatherResourceUseCase
from app.application.use_cases.get_available_classes import GetAvailableClassesUseCase
from app.application.use_cases.get_available_crafts import GetAvailableCraftsUseCase
from app.application.use_cases.get_player_class import GetPlayerClassUseCase
from app.application.use_cases.get_player_equipment import GetPlayerEquipmentUseCase
from app.application.use_cases.equip_item import EquipItemUseCase
from app.application.use_cases.get_player_inventory import GetPlayerInventoryUseCase
from app.application.use_cases.get_player_profile import GetPlayerProfileUseCase
from app.application.use_cases.get_player_quests import GetPlayerQuestsUseCase
from app.application.use_cases.get_player_stats import GetPlayerStatsUseCase
from app.bot.embeds.battle_embeds import (
    build_battle_result_embed,
    build_battle_turn_embed,
)
from app.bot.embeds.class_embeds import build_player_class_embed
from app.bot.embeds.daily_embeds import (
    build_daily_cooldown_embed,
    build_daily_success_embed,
)
from app.bot.views.equipment_view import EquipmentView
from app.bot.embeds.craft_embeds import WEAPON_CATEGORIES, build_craft_list_embed
from app.bot.embeds.inventory_embeds import build_inventory_embed
from app.bot.embeds.player_embeds import build_player_profile_embed
from app.domain.services.class_service import ClassService
from app.domain.services.combat_service import CombatService
from app.domain.services.cooldown_service import CooldownService
from app.domain.services.craft_service import CraftService
from app.domain.services.loot_service import LootService
from app.domain.services.profession_service import ProfessionService
from app.domain.services.progression_service import ProgressionService
from app.domain.services.quest_service import QuestService
from app.domain.services.stats_service import StatsService
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.craft_repository import CraftRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
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
from app.infrastructure.db.repositories.quest_repository import QuestRepository
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
            stats = StatsService().calculate_player_stats(
                profile=profile,
                equipped_items=equipped_items,
                active_class=active_class,
                skill_bonuses=skill_bonuses,
            )

            power_score_service = PowerScoreService()
            formatted_power_score = power_score_service.format_score(
                power_score_service.calculate_from_stats(stats)
            )

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

        embed = build_player_profile_embed(
            profile=profile,
            stats=stats,
            active_class=active_class,
            current_hp=regenerated_current_hp,
            power_score=formatted_power_score,
            total_kills=total_kills,
            career_stats=career_stats,
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

        embed = build_inventory_embed(target_member.display_name, items)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="equipment", description="Afficher un équipement (12 slots, 2 pages)")
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

    @app_commands.command(name="equip", description="Équiper un item depuis votre inventaire")
    @app_commands.describe(
        item_code="Code de l'item (autocomplete)",
        slot="Slot cible (optionnel : utilise le slot par défaut de l'item)",
    )
    async def equip(
        self,
        interaction: discord.Interaction,
        item_code: str,
        slot: str | None = None,
    ) -> None:
        if slot is not None:
            allowed_slots = {s.value for s in EquipmentSlot}
            if slot not in allowed_slots:
                await interaction.response.send_message(
                    f"Slot invalide. Slots disponibles : {', '.join(sorted(allowed_slots))}",
                    ephemeral=True,
                )
                return

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            inventory_repository = InventoryRepository(session)
            equipment_repository = EquipmentRepository(session)

            use_case = EquipItemUseCase(
                player_repository=player_repository,
                inventory_repository=inventory_repository,
                equipment_repository=equipment_repository,
            )

            result = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
                item_code=item_code,
                slot=slot,
            )

        if not result.success:
            await interaction.response.send_message(result.message, ephemeral=True)
            return

        message = result.message
        if result.unequipped_items:
            message += (
                f"\n_Déséquipé(s) : {', '.join(result.unequipped_items)}._"
            )
        await interaction.response.send_message(message)

    @equip.autocomplete("item_code")
    async def equip_item_code_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Propose uniquement les items équipables présents dans l'inventaire."""
        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            profile = player_repository.get_by_discord_id(interaction.user.id)
            if profile is None:
                return []

            inventory_repository = InventoryRepository(session)
            items = inventory_repository.list_by_player_id(profile.player.id)

        current_lower = current.lower()
        choices: list[app_commands.Choice[str]] = []
        for item in items:
            definition = item.item_definition
            if not definition.is_equipable:
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

    @equip.autocomplete("slot")
    async def equip_slot_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        current_lower = current.lower()
        return [
            app_commands.Choice(name=s.value, value=s.value)
            for s in EquipmentSlot
            if current_lower in s.value.lower()
        ][:25]

    @app_commands.command(name="fight", description="[Admin] Combattre un monstre (test)")
    @app_commands.describe(mob_code="Code technique du monstre")
    @admin_only
    async def fight(self, interaction: discord.Interaction, mob_code: str) -> None:
        await interaction.response.defer()

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            equipment_repository = EquipmentRepository(session)
            mob_repository = MobRepository(session)
            inventory_repository = InventoryRepository(session)
            item_repository = ItemRepository(session)
            quest_repository = QuestRepository(session)
            class_repository = ClassRepository(session)

            use_case = FightMobUseCase(
                player_repository=player_repository,
                equipment_repository=equipment_repository,
                mob_repository=mob_repository,
                inventory_repository=inventory_repository,
                item_repository=item_repository,
                quest_repository=quest_repository,
                kill_repository=PlayerKillRepository(session),
                stats_service=StatsService(),
                combat_service=CombatService(),
                loot_service=LootService(),
                progression_service=ProgressionService(),
                quest_service=QuestService(),
                class_repository=class_repository,
                skill_allocation_repository=PlayerSkillAllocationRepository(session),
            )

            result = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
                mob_code=mob_code,
            )

        if result is None:
            await interaction.followup.send(
                "Monstre introuvable.",
                ephemeral=True,
            )
            return

        if not result.turn_logs:
            embed = build_battle_result_embed(result)
            await interaction.followup.send(embed=embed)
            return

        first_embed = build_battle_turn_embed(result, result.turn_logs[0])
        message = await interaction.followup.send(embed=first_embed)

        for turn_log in result.turn_logs[1:]:
            await asyncio.sleep(1.5)
            embed = build_battle_turn_embed(result, turn_log)
            await message.edit(embed=embed)

        await asyncio.sleep(1.5)
        final_embed = build_battle_result_embed(result)
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
        description="Liste les recettes d'équipement et accessoires (hors armes/boucliers)",
    )
    async def craft_list(self, interaction: discord.Interaction) -> None:
        await self._send_recipe_list(
            interaction,
            include_categories=None,
            exclude_categories=WEAPON_CATEGORIES,
            title="🛠️ Recettes — Équipement & Accessoires",
            color=discord.Color.orange(),
        )

    @app_commands.command(
        name="forge_list",
        description="Liste les recettes d'armes et boucliers (à forger)",
    )
    async def forge_list(self, interaction: discord.Interaction) -> None:
        await self._send_recipe_list(
            interaction,
            include_categories=WEAPON_CATEGORIES,
            exclude_categories=None,
            title="🔥 Recettes — Forge (armes & boucliers)",
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
        embed = build_craft_list_embed(
            recipes=filtered,
            item_lookup=item_lookup,
            title=title,
            color=color,
        )
        await interaction.response.send_message(embed=embed)

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

            is_weapon = result_item.category in WEAPON_CATEGORIES
            if expect_weapon and not is_weapon:
                await interaction.response.send_message(
                    f"❌ **{result_item.name}** n'est pas une arme : utilisez `/craft` à la place.",
                    ephemeral=True,
                )
                return
            if not expect_weapon and is_weapon:
                await interaction.response.send_message(
                    f"❌ **{result_item.name}** est une arme : utilisez `/forge` à la place.",
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

            success = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
                recipe_code=recipe_code,
            )

        if not success:
            await interaction.response.send_message(
                "❌ Ingrédients insuffisants ou recette indisponible.",
                ephemeral=True,
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
            is_weapon = result.category in WEAPON_CATEGORIES
            if weapons_only and not is_weapon:
                continue
            if not weapons_only and is_weapon:
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
            )
            await interaction.response.send_message(embed=embed)
        else:
            embed = build_daily_cooldown_embed(
                streak=result.streak,
                next_available_at=result.next_available_at,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="quests", description="Afficher les quêtes d'un joueur")
    @app_commands.describe(target="Joueur dont afficher les quêtes (par défaut : vous)")
    async def quests(
        self,
        interaction: discord.Interaction,
        target: discord.Member | None = None,
    ) -> None:
        quest_service = QuestService()

        with get_db_session() as session:
            profile, target_member = self._resolve_profile(interaction, target, session)
            if profile is None:
                await self._send_no_profile_error(interaction, target_member)
                return

            quest_repository = QuestRepository(session)
            inventory_repository = InventoryRepository(session)

            quests = quest_repository.list_definitions()
            inventory_items = inventory_repository.list_by_player_id(profile.player.id)

            quest_entries: list[dict] = []

            for quest in quests:
                state = quest_repository.get_or_create_player_quest_state(
                    profile.player.id,
                    quest.id,
                )

                progress = state.progress_quantity
                is_completed = state.is_completed

                if quest.objective_type == "collect_item":
                    progress, is_completed = quest_service.compute_progress_for_collect_quest(
                        quest,
                        inventory_items,
                    )
                    # On ne persiste l'état des quêtes "collect_item" que pour soi-même.
                    if target is None:
                        quest_repository.update_progress(
                            profile.player.id,
                            quest.id,
                            progress,
                            is_completed,
                        )

                quest_entries.append(
                    {
                        "quest": quest,
                        "state": state,
                        "progress": progress,
                        "is_completed": is_completed,
                    }
                )

        embed = discord.Embed(
            title=f"📜 Quêtes de {target_member.display_name}",
            color=discord.Color.teal(),
        )

        if not quest_entries:
            embed.description = "Aucune quête disponible."
        else:
            lines = []
            for entry in quest_entries:
                quest = entry["quest"]
                progress = entry["progress"]
                is_completed = entry["is_completed"]
                status = "✅ Terminée" if is_completed else "⏳ En cours"
                lines.append(
                    f"**{quest.code}** — {quest.name}\n"
                    f"{quest.description}\n"
                    f"Progression : {progress}/{quest.required_quantity} • {status}"
                )

            embed.description = "\n\n".join(lines)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="quest_claim", description="Récupérer la récompense d'une quête")
    @app_commands.describe(quest_code="Code technique de la quête")
    async def quest_claim(self, interaction: discord.Interaction, quest_code: str) -> None:
        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            quest_repository = QuestRepository(session)
            item_repository = ItemRepository(session)
            inventory_repository = InventoryRepository(session)

            use_case = ClaimQuestRewardUseCase(
                player_repository=player_repository,
                quest_repository=quest_repository,
                item_repository=item_repository,
                inventory_repository=inventory_repository,
                progression_service=ProgressionService(),
                career_stats_repository=PlayerCareerStatsRepository(session),
            )

            success, message = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
                quest_code=quest_code,
            )

        await interaction.response.send_message(message, ephemeral=not success)

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