import discord
from discord import app_commands
from discord.ext import commands

from app.application.use_cases.get_player_profile import GetPlayerProfileUseCase
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.application.use_cases.get_player_inventory import GetPlayerInventoryUseCase
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.application.use_cases.equip_item import EquipItemUseCase
from app.application.use_cases.get_player_equipment import GetPlayerEquipmentUseCase
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.application.use_cases.get_player_stats import GetPlayerStatsUseCase
from app.domain.services.stats_service import StatsService
from app.application.use_cases.fight_mob import FightMobUseCase
from app.domain.services.combat_service import CombatService
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.domain.services.loot_service import LootService
from app.domain.services.progression_service import ProgressionService
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.session import get_db_session
from app.application.use_cases.change_player_class import ChangePlayerClassUseCase
from app.application.use_cases.get_player_class import GetPlayerClassUseCase
from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.application.use_cases.craft_item import CraftItemUseCase
from app.application.use_cases.get_available_crafts import GetAvailableCraftsUseCase
from app.domain.services.craft_service import CraftService
from app.infrastructure.db.repositories.craft_repository import CraftRepository
from app.application.use_cases.claim_daily_reward import ClaimDailyRewardUseCase
from app.domain.services.cooldown_service import CooldownService
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository


class PlayerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
    @app_commands.command(name="ping", description="Vérifier si le bot fonctionne")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("🏓 Pong !")

    @app_commands.command(name="profile", description="Afficher votre profil joueur")
    async def profile(self, interaction: discord.Interaction) -> None:
        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            equipment_repository = EquipmentRepository(session)
            class_repository = ClassRepository(session)

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

        embed = discord.Embed(
            title=f"👤 Profil de {profile.player.display_name}",
            color=discord.Color.blue(),
        )

        embed.add_field(name="🎯 Niveau", value=str(profile.progression.level), inline=True)
        embed.add_field(name="✨ XP", value=str(profile.progression.xp), inline=True)
        embed.add_field(name="💰 Gold", value=str(profile.resources.gold), inline=True)

        embed.add_field(name="❤️ PV", value=str(stats.max_hp), inline=True)
        embed.add_field(name="⚔️ Attaque", value=str(stats.attack), inline=True)
        embed.add_field(name="🛡️ Défense", value=str(stats.defense), inline=True)

        embed.set_footer(text=f"ID Discord : {profile.player.discord_id}")

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

        embed = discord.Embed(
            title=f"🎒 Inventaire de {interaction.user.display_name}",
            color=discord.Color.green(),
        )

        if not items:
            embed.description = "Votre inventaire est vide."
        else:
            lines = [
                f"{item.item_definition.name} x{item.quantity}"
                for item in items
            ]
            embed.description = "\n".join(lines)

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
        allowed_slots = {"helmet", "chest", "leggins", "boots", "weapon", "ring_1", "ring_2"}

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
        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            equipment_repository = EquipmentRepository(session)
            mob_repository = MobRepository(session)
            inventory_repository = InventoryRepository(session)
            item_repository = ItemRepository(session)

            use_case = FightMobUseCase(
                player_repository=player_repository,
                equipment_repository=equipment_repository,
                mob_repository=mob_repository,
                inventory_repository=inventory_repository,
                item_repository=item_repository,
                stats_service=StatsService(),
                combat_service=CombatService(),
                loot_service=LootService(),
                progression_service=ProgressionService(),
            )

            result = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
                mob_code=mob_code,
            )

        if result is None:
            await interaction.response.send_message(
                "Monstre introuvable.",
                ephemeral=True,
            )
            return

        color = discord.Color.green() if result.victory else discord.Color.red()

        embed = discord.Embed(
            title="⚔️ Résultat du combat",
            description=result.summary,
            color=color,
        )

        embed.add_field(name="Tours", value=str(result.turns), inline=True)
        embed.add_field(name="PV restants joueur", value=str(result.player_remaining_hp), inline=True)
        embed.add_field(name="PV restants monstre", value=str(result.mob_remaining_hp), inline=True)

        if result.victory:
            embed.add_field(name="XP gagnée", value=str(result.xp_gained), inline=True)
            embed.add_field(name="Gold gagné", value=str(result.gold_gained), inline=True)

            if result.items_gained:
                loot_lines = [f"{item_code} x{quantity}" for item_code, quantity in result.items_gained]
                embed.add_field(name="Loot", value="\n".join(loot_lines), inline=False)

            if result.leveled_up and result.new_level is not None:
                embed.add_field(name="🎉 Level up", value=f"Niveau {result.new_level}", inline=False)

        await interaction.response.send_message(embed=embed)
    
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

        embed = discord.Embed(
            title=f"🧬 Classe de {interaction.user.display_name}",
            color=discord.Color.gold(),
        )

        if active_class is None:
            embed.description = "Aucune classe active."
        else:
            embed.add_field(name="Nom", value=active_class.name, inline=False)
            embed.add_field(name="Description", value=active_class.description, inline=False)

            bonuses = active_class.stat_bonuses or {}
            if bonuses:
                bonus_lines = [f"{key}: +{value}" for key, value in bonuses.items()]
                embed.add_field(name="Bonus", value="\n".join(bonus_lines), inline=False)

        await interaction.response.send_message(embed=embed)


    @app_commands.command(name="class_set", description="Définir votre classe active")
    @app_commands.describe(class_code="Code technique de la classe")
    async def class_set(self, interaction: discord.Interaction, class_code: str) -> None:
        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            class_repository = ClassRepository(session)

            use_case = ChangePlayerClassUseCase(
                player_repository=player_repository,
                class_repository=class_repository,
            )

            success = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
                class_code=class_code,
            )

        if not success:
            await interaction.response.send_message(
                "Classe introuvable.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Classe active définie sur `{class_code}`."
        )
    
    @app_commands.command(name="craft_list", description="Afficher les recettes disponibles")
    async def craft_list(self, interaction: discord.Interaction) -> None:
        with get_db_session() as session:
            craft_repository = CraftRepository(session)
            use_case = GetAvailableCraftsUseCase(craft_repository)

            recipes = use_case.execute()

        embed = discord.Embed(
            title="🛠️ Recettes disponibles",
            color=discord.Color.orange(),
        )

        if not recipes:
            embed.description = "Aucune recette disponible."
        else:
            lines = []
            for recipe in recipes:
                ingredients = ", ".join(
                    f"{ingredient.item_code} x{ingredient.quantity}"
                    for ingredient in recipe.ingredients
                )
                lines.append(
                    f"**{recipe.code}** → {recipe.result_item_code} x{recipe.result_quantity}\n"
                    f"Ingrédients : {ingredients}"
                )

            embed.description = "\n\n".join(lines)

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
    
async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PlayerCog(bot))