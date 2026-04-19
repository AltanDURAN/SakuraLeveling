import asyncio

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, UTC

from app.application.use_cases.change_player_class import ChangePlayerClassUseCase
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
from app.bot.embeds.craft_embeds import build_craft_list_embed
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
from app.infrastructure.db.repositories.player_repository import PlayerRepository
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

    @app_commands.command(name="profile", description="Afficher votre profil joueur")
    async def profile(self, interaction: discord.Interaction) -> None:
        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            equipment_repository = EquipmentRepository(session)
            class_repository = ClassRepository(session)
            player_health_repository = PlayerHealthRepository(session)

            profile_use_case = GetPlayerProfileUseCase(player_repository)
            stats_use_case = GetPlayerStatsUseCase(
                player_repository=player_repository,
                equipment_repository=equipment_repository,
                class_repository=class_repository,
                stats_service=StatsService(),
            )

            profile = profile_use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )

            stats = stats_use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )
            
            power_score_service = PowerScoreService()
            raw_power_score = power_score_service.calculate_from_stats(stats)
            formatted_power_score = power_score_service.format_score(raw_power_score)

            active_class = class_repository.get_current_class_for_player(profile.player.id)

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

            if regenerated_current_hp != health_state.current_hp:
                player_health_repository.refresh_current_hp(
                    player_id=profile.player.id,
                    new_current_hp=regenerated_current_hp,
                )

        embed = build_player_profile_embed(
            profile=profile,
            stats=stats,
            active_class=active_class,
            current_hp=regenerated_current_hp,
            power_score=formatted_power_score,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="inventory", description="Afficher votre inventaire")
    async def inventory(self, interaction: discord.Interaction) -> None:
        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            inventory_repository = InventoryRepository(session)
            use_case = GetPlayerInventoryUseCase(
                player_repository=player_repository,
                inventory_repository=inventory_repository,
            )

            _, items = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )

        embed = build_inventory_embed(interaction.user.display_name, items)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="equipment", description="Afficher votre équipement")
    async def equipment(self, interaction: discord.Interaction) -> None:
        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            equipment_repository = EquipmentRepository(session)
            use_case = GetPlayerEquipmentUseCase(
                player_repository=player_repository,
                equipment_repository=equipment_repository,
            )

            equipment_items = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )

        embed = discord.Embed(
            title=f"🛡️ Équipement de {interaction.user.display_name}",
            color=discord.Color.purple(),
        )

        if not equipment_items:
            embed.description = "Aucun équipement."
        else:
            lines = [
                f"**{item.slot}** : {item.item_definition.name}"
                for item in equipment_items
            ]
            embed.description = "\n".join(lines)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="equip", description="Équiper un item depuis votre inventaire")
    @app_commands.describe(item_code="Code technique de l'item", slot="Slot d'équipement")
    async def equip(
        self,
        interaction: discord.Interaction,
        item_code: str,
        slot: str,
    ) -> None:
        allowed_slots = {slot.value for slot in EquipmentSlot}

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

            success = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
                item_code=item_code,
                slot=slot,
            )

        if not success:
            await interaction.response.send_message(
                "Item introuvable dans votre inventaire.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Item `{item_code}` équipé dans le slot `{slot}`."
        )

    @app_commands.command(name="fight", description="Combattre un monstre")
    @app_commands.describe(mob_code="Code technique du monstre")
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
                stats_service=StatsService(),
                combat_service=CombatService(),
                loot_service=LootService(),
                progression_service=ProgressionService(),
                quest_service=QuestService(),
                class_repository=class_repository,
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

    @app_commands.command(name="class", description="Afficher votre classe active")
    async def player_class(self, interaction: discord.Interaction) -> None:
        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            class_repository = ClassRepository(session)

            use_case = GetPlayerClassUseCase(
                player_repository=player_repository,
                class_repository=class_repository,
            )

            active_class = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )

        embed = build_player_class_embed(interaction.user.display_name, active_class)
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

    @app_commands.command(name="craft_list", description="Afficher les recettes disponibles")
    async def craft_list(self, interaction: discord.Interaction) -> None:
        with get_db_session() as session:
            craft_repository = CraftRepository(session)
            use_case = GetAvailableCraftsUseCase(craft_repository)

            recipes = use_case.execute()

        embed = build_craft_list_embed(recipes)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="craft", description="Fabriquer un objet")
    @app_commands.describe(recipe_code="Code technique de la recette")
    async def craft(self, interaction: discord.Interaction, recipe_code: str) -> None:
        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            craft_repository = CraftRepository(session)
            inventory_repository = InventoryRepository(session)
            item_repository = ItemRepository(session)

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
                "Craft impossible. Vérifiez la recette et vos ingrédients.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Craft `{recipe_code}` réalisé avec succès."
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
                progression_service=ProgressionService(),
            )

            success, message = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )

        if success:
            await interaction.response.send_message(message)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(name="quests", description="Afficher vos quêtes")
    async def quests(self, interaction: discord.Interaction) -> None:
        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            quest_repository = QuestRepository(session)
            inventory_repository = InventoryRepository(session)

            use_case = GetPlayerQuestsUseCase(
                player_repository=player_repository,
                quest_repository=quest_repository,
                inventory_repository=inventory_repository,
                quest_service=QuestService(),
            )

            quest_entries = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )

        embed = discord.Embed(
            title=f"📜 Quêtes de {interaction.user.display_name}",
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