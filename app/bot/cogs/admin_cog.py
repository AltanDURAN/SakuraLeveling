import discord
from discord import app_commands
from discord.ext import commands

from app.application.use_cases.reset_player import ResetPlayerUseCase
from app.bot.checks.admin_check import admin_only
from app.shared.enums import EquipmentSlot
from app.shared.formatters import format_int as _format_int
from app.domain.services.progression_service import ProgressionService
from app.domain.services.shop_pricing_service import ShopPricingService
from app.domain.services.stats_service import StatsService
from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.repositories.player_duel_rank_repository import (
    PlayerDuelRankRepository,
)
from app.infrastructure.db.repositories.player_health_repository import (
    PlayerHealthRepository,
)
from app.infrastructure.db.repositories.player_kill_repository import PlayerKillRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.shop_repository import ShopRepository
from app.infrastructure.db.session import get_db_session


class AdminCog(commands.Cog):
    """Commandes administrateur — réservées aux Discord IDs listés dans `ADMIN_DISCORD_IDS`."""

    admin = app_commands.Group(
        name="admin",
        description="Commandes administrateur",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # -------------------------- Or --------------------------

    @admin.command(name="give_gold", description="Ajoute de l'or à un joueur")
    @app_commands.describe(target="Joueur ciblé", amount="Quantité d'or à ajouter")
    @admin_only
    async def give_gold(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        amount: app_commands.Range[int, 1, 1_000_000_000],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            profile = player_repository.get_by_discord_id(target.id)

            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.",
                    ephemeral=True,
                )
                return

            player_repository.add_gold(profile.player.id, amount)

        await interaction.followup.send(
            f"✅ **{_format_int(amount)}** or ajouté à {target.mention}.",
            ephemeral=True,
        )

    @admin.command(name="set_gold", description="Définit le montant d'or d'un joueur")
    @app_commands.describe(target="Joueur ciblé", amount="Nouvelle quantité d'or (>= 0)")
    @admin_only
    async def set_gold(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        amount: app_commands.Range[int, 0, 1_000_000_000],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            profile = player_repository.get_by_discord_id(target.id)

            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.",
                    ephemeral=True,
                )
                return

            player_repository.set_gold(profile.player.id, amount)

        await interaction.followup.send(
            f"✅ Or de {target.mention} défini à **{_format_int(amount)}**.",
            ephemeral=True,
        )

    # -------------------------- XP / Niveau --------------------------

    @admin.command(name="give_xp", description="Ajoute de l'XP à un joueur (peut faire monter de niveau)")
    @app_commands.describe(target="Joueur ciblé", amount="Quantité d'XP à ajouter")
    @admin_only
    async def give_xp(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        amount: app_commands.Range[int, 1, 1_000_000_000],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        progression_service = ProgressionService()

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            profile = player_repository.get_by_discord_id(target.id)

            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.",
                    ephemeral=True,
                )
                return

            new_level, new_xp, new_skill_points = progression_service.apply_level_up(
                current_level=profile.progression.level,
                current_xp=profile.progression.xp,
                gained_xp=amount,
                current_skill_points=profile.progression.skill_points,
            )

            player_repository.apply_progression(
                player_id=profile.player.id,
                new_level=new_level,
                new_xp=new_xp,
                new_skill_points=new_skill_points,
            )

            level_msg = (
                f" — niveau **{profile.progression.level} → {new_level}**"
                if new_level > profile.progression.level
                else ""
            )

        await interaction.followup.send(
            f"✅ **{_format_int(amount)}** XP ajoutés à {target.mention}{level_msg}.",
            ephemeral=True,
        )

    @admin.command(name="set_level", description="Définit le niveau d'un joueur (XP remis à 0 pour ce niveau)")
    @app_commands.describe(target="Joueur ciblé", level="Nouveau niveau (>= 1)")
    @admin_only
    async def set_level(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        level: app_commands.Range[int, 1, 1000],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            profile = player_repository.get_by_discord_id(target.id)

            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.",
                    ephemeral=True,
                )
                return

            player_repository.apply_progression(
                player_id=profile.player.id,
                new_level=level,
                new_xp=0,
                new_skill_points=profile.progression.skill_points,
            )

        await interaction.followup.send(
            f"✅ Niveau de {target.mention} défini à **{level}**.",
            ephemeral=True,
        )

    # -------------------------- Items --------------------------

    @admin.command(name="give_item", description="Ajoute un objet à l'inventaire d'un joueur")
    @app_commands.describe(
        target="Joueur ciblé",
        item_code="Code de l'objet (ex : slime_gel)",
        quantity="Quantité à ajouter",
    )
    @admin_only
    async def give_item(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        item_code: str,
        quantity: app_commands.Range[int, 1, 9999],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            item_repository = ItemRepository(session)
            inventory_repository = InventoryRepository(session)

            profile = player_repository.get_by_discord_id(target.id)
            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.",
                    ephemeral=True,
                )
                return

            item = item_repository.get_by_code(item_code)
            if item is None:
                await interaction.followup.send(
                    f"❌ Objet `{item_code}` introuvable.",
                    ephemeral=True,
                )
                return

            inventory_repository.add_item(
                player_id=profile.player.id,
                item_definition_id=item.id,
                quantity=quantity,
            )

        await interaction.followup.send(
            f"✅ {quantity}× **{item.name}** ajouté à l'inventaire de {target.mention}.",
            ephemeral=True,
        )

    @admin.command(name="remove_item", description="Retire un objet de l'inventaire d'un joueur")
    @app_commands.describe(
        target="Joueur ciblé",
        item_code="Code de l'objet",
        quantity="Quantité à retirer",
    )
    @admin_only
    async def remove_item(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        item_code: str,
        quantity: app_commands.Range[int, 1, 9999],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            item_repository = ItemRepository(session)
            inventory_repository = InventoryRepository(session)

            profile = player_repository.get_by_discord_id(target.id)
            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.",
                    ephemeral=True,
                )
                return

            item = item_repository.get_by_code(item_code)
            if item is None:
                await interaction.followup.send(
                    f"❌ Objet `{item_code}` introuvable.",
                    ephemeral=True,
                )
                return

            removed = inventory_repository.remove_item(
                player_id=profile.player.id,
                item_definition_id=item.id,
                quantity=quantity,
            )

            if not removed:
                await interaction.followup.send(
                    f"❌ {target.display_name} ne possède pas {quantity}× **{item.name}**.",
                    ephemeral=True,
                )
                return

        await interaction.followup.send(
            f"✅ {quantity}× **{item.name}** retiré de l'inventaire de {target.mention}.",
            ephemeral=True,
        )

    # -------------------------- Skill points --------------------------

    @admin.command(
        name="give_skill_points",
        description="Ajoute des skill points à un joueur (peut être négatif pour retirer)",
    )
    @app_commands.describe(target="Joueur ciblé", amount="Nombre de skill points à ajouter (négatif pour retirer)")
    @admin_only
    async def give_skill_points(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        amount: app_commands.Range[int, -1000, 1000],
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            repo = PlayerRepository(session)
            profile = repo.get_by_discord_id(target.id)
            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.", ephemeral=True
                )
                return
            repo.add_skill_points(profile.player.id, amount)
        verb = "ajouté" if amount >= 0 else "retiré"
        await interaction.followup.send(
            f"✅ **{abs(amount)}** skill point(s) {verb} pour {target.mention}.",
            ephemeral=True,
        )

    @admin.command(
        name="set_skill_points",
        description="Définit le nombre exact de skill points d'un joueur",
    )
    @app_commands.describe(target="Joueur ciblé", amount="Nouvelle valeur (≥ 0)")
    @admin_only
    async def set_skill_points(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        amount: app_commands.Range[int, 0, 10_000],
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            repo = PlayerRepository(session)
            profile = repo.get_by_discord_id(target.id)
            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.", ephemeral=True
                )
                return
            repo.set_skill_points(profile.player.id, amount)
        await interaction.followup.send(
            f"✅ Skill points de {target.mention} définis à **{amount}**.",
            ephemeral=True,
        )

    # -------------------------- HP --------------------------

    @admin.command(
        name="set_current_hp",
        description="Définit les PV courants d'un joueur (0 = KO)",
    )
    @app_commands.describe(target="Joueur ciblé", hp="Nouveaux PV (≥ 0)")
    @admin_only
    async def set_current_hp(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        hp: app_commands.Range[int, 0, 1_000_000],
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(target.id)
            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.", ephemeral=True
                )
                return
            health_repo = PlayerHealthRepository(session)
            # get_or_create exige un default ; on le pose à `hp` puis on update
            # (couvre le cas du joueur jamais blessé).
            health_repo.get_or_create(profile.player.id, default_current_hp=hp)
            health_repo.update_current_hp(profile.player.id, hp)
        await interaction.followup.send(
            f"✅ PV de {target.mention} définis à **{hp}**.", ephemeral=True
        )

    @admin.command(
        name="heal_full",
        description="Restaure tous les PV d'un joueur à son max_hp courant",
    )
    @app_commands.describe(target="Joueur ciblé")
    @admin_only
    async def heal_full(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            player_repo = PlayerRepository(session)
            profile = player_repo.get_by_discord_id(target.id)
            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.", ephemeral=True
                )
                return
            equipped = EquipmentRepository(session).list_by_player_id(profile.player.id)
            active_class = ClassRepository(session).get_current_class_for_player(
                profile.player.id
            )
            stats = StatsService().calculate_player_stats(
                profile=profile, equipped_items=equipped, active_class=active_class,
            )
            health_repo = PlayerHealthRepository(session)
            health_repo.get_or_create(profile.player.id, default_current_hp=stats.max_hp)
            health_repo.update_current_hp(profile.player.id, stats.max_hp)
        await interaction.followup.send(
            f"✅ {target.mention} restauré à pleins PV (**{stats.max_hp}**).",
            ephemeral=True,
        )

    # -------------------------- Daily streak --------------------------

    @admin.command(
        name="set_daily_streak",
        description="Définit le compteur de streak du /daily d'un joueur",
    )
    @app_commands.describe(target="Joueur ciblé", streak="Nombre de jours consécutifs (≥ 0)")
    @admin_only
    async def set_daily_streak(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        streak: app_commands.Range[int, 0, 10_000],
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            repo = PlayerRepository(session)
            profile = repo.get_by_discord_id(target.id)
            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.", ephemeral=True
                )
                return
            repo.set_daily_streak(profile.player.id, streak)
        await interaction.followup.send(
            f"✅ Streak quotidien de {target.mention} défini à **{streak}** jour(s).",
            ephemeral=True,
        )

    # -------------------------- Classe active --------------------------

    @admin.command(
        name="set_class",
        description="Force la classe active d'un joueur (ignore les prérequis de niveau)",
    )
    @app_commands.describe(target="Joueur ciblé", class_code="Code de la classe (autocomplete)")
    @admin_only
    async def set_class(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        class_code: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(target.id)
            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.", ephemeral=True
                )
                return
            class_repo = ClassRepository(session)
            class_def = class_repo.get_by_code(class_code)
            if class_def is None:
                await interaction.followup.send(
                    f"❌ Classe `{class_code}` introuvable.", ephemeral=True
                )
                return
            class_repo.set_player_class(profile.player.id, class_def.id)
        await interaction.followup.send(
            f"✅ Classe de {target.mention} définie à **{class_def.name}**.",
            ephemeral=True,
        )

    # -------------------------- Kill counter --------------------------

    @admin.command(
        name="set_kills",
        description="Définit le compteur de kills d'un joueur pour un mob spécifique",
    )
    @app_commands.describe(
        target="Joueur ciblé",
        mob_code="Code du mob (autocomplete)",
        count="Nouveau compteur (0 = supprime la ligne)",
    )
    @admin_only
    async def set_kills(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        mob_code: str,
        count: app_commands.Range[int, 0, 10_000_000],
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(target.id)
            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.", ephemeral=True
                )
                return
            mob = MobRepository(session).get_by_code(mob_code)
            if mob is None:
                await interaction.followup.send(
                    f"❌ Mob `{mob_code}` introuvable.", ephemeral=True
                )
                return
            PlayerKillRepository(session).set_kill_count(
                profile.player.id, mob_code, count
            )
        await interaction.followup.send(
            f"✅ Kills de **{mob.name}** pour {target.mention} : **{count}**.",
            ephemeral=True,
        )

    # -------------------------- Équipement forcé --------------------------

    @admin.command(
        name="force_equip",
        description="Force l'équipement d'un item sur un slot (bypass des checks de craft/inventaire)",
    )
    @app_commands.describe(
        target="Joueur ciblé",
        item_code="Code de l'item à équiper",
        slot="Slot où équiper (par défaut : slot canonique de l'item)",
    )
    @admin_only
    async def force_equip(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        item_code: str,
        slot: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(target.id)
            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.", ephemeral=True
                )
                return
            item = ItemRepository(session).get_by_code(item_code)
            if item is None:
                await interaction.followup.send(
                    f"❌ Item `{item_code}` introuvable.", ephemeral=True
                )
                return
            target_slot = slot or item.equipment_slot
            if target_slot is None:
                await interaction.followup.send(
                    f"❌ `{item.name}` n'a pas de slot canonique. "
                    f"Précisez `slot` explicitement.",
                    ephemeral=True,
                )
                return
            EquipmentRepository(session).equip_item(
                profile.player.id, item.id, target_slot
            )
        await interaction.followup.send(
            f"✅ {target.mention} équipé de **{item.name}** sur `{target_slot}`.",
            ephemeral=True,
        )

    @admin.command(
        name="force_unequip",
        description="Retire l'équipement d'un slot d'un joueur",
    )
    @app_commands.describe(target="Joueur ciblé", slot="Slot à vider")
    @admin_only
    async def force_unequip(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        slot: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(target.id)
            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.", ephemeral=True
                )
                return
            removed = EquipmentRepository(session).unequip_slot(profile.player.id, slot)
        if removed:
            await interaction.followup.send(
                f"✅ Slot `{slot}` de {target.mention} vidé.", ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"⚠️ Slot `{slot}` était déjà vide.", ephemeral=True
            )

    # -------------------------- Duel rank --------------------------

    @admin.command(
        name="set_duel_rank",
        description="Force la position d'un joueur dans le ladder 1v1 (décale les autres)",
    )
    @app_commands.describe(target="Joueur ciblé", position="Position cible (1 = meilleur)")
    @admin_only
    async def set_duel_rank(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        position: app_commands.Range[int, 1, 10_000],
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(target.id)
            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.", ephemeral=True
                )
                return
            PlayerDuelRankRepository(session).set_rank_position(
                profile.player.id, position
            )
        await interaction.followup.send(
            f"✅ {target.mention} placé au rang **#{position}** du ladder 1v1.",
            ephemeral=True,
        )

    # -------------------------- Encounter management --------------------------

    @admin.command(
        name="end_encounter",
        description="Annule l'encounter actif (combat de groupe en cours)",
    )
    @admin_only
    async def end_encounter(self, interaction: discord.Interaction) -> None:
        encounter_cog = self.bot.get_cog("EncounterCog")
        if encounter_cog is None:
            await interaction.response.send_message(
                "❌ Le cog d'encounter n'est pas chargé.", ephemeral=True
            )
            return
        success, message = encounter_cog.force_end_encounter()
        await interaction.response.send_message(
            f"{'✅' if success else '⚠️'} {message}", ephemeral=True
        )

    # -------------------------- Outils de test --------------------------

    @admin.command(
        name="reset_player",
        description="Réinitialise complètement le profil d'un joueur (garde son identité Discord)",
    )
    @app_commands.describe(target="Joueur à réinitialiser")
    @admin_only
    async def reset_player(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            profile = player_repository.get_by_discord_id(target.id)

            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.",
                    ephemeral=True,
                )
                return

            ResetPlayerUseCase().execute(session=session, player_id=profile.player.id)

        await interaction.followup.send(
            f"✅ Profil de {target.mention} réinitialisé "
            "(niveau 1, 0 or, inventaire/équipement/classes/quêtes/cooldowns/kills/HP vidés).",
            ephemeral=True,
        )

    @admin.command(
        name="spawn_encounter",
        description="Force le spawn immédiat d'un encounter (mob aléatoire ou spécifique)",
    )
    @app_commands.describe(
        mob_code="Code du mob à faire spawn (optionnel : random sinon)"
    )
    @admin_only
    async def spawn_encounter(
        self,
        interaction: discord.Interaction,
        mob_code: str | None = None,
    ) -> None:
        encounter_cog = self.bot.get_cog("EncounterCog")
        if encounter_cog is None:
            await interaction.response.send_message(
                "❌ Le cog d'encounter n'est pas chargé.",
                ephemeral=True,
            )
            return

        success, message = encounter_cog.trigger_immediate_spawn(mob_code=mob_code)
        await interaction.response.send_message(
            f"{'✅' if success else '⚠️'} {message}",
            ephemeral=True,
        )

    # -------------------------- Shop --------------------------

    @admin.command(
        name="shop_add",
        description="Ajoute un objet au shop (achat fixe + vente dynamique)",
    )
    @app_commands.describe(
        item_code="Code de l'objet à mettre en shop",
        buy_price="Prix d'achat (gold) — fixe, payé par les joueurs",
        max_sell_price="Prix de vente maximum (stock vide) — payé au joueur qui vend",
        min_sell_price="Prix de vente minimum (stock saturé). 0 par défaut.",
        stock_threshold="Stock à partir duquel le prix de vente atteint le minimum. 100 par défaut.",
    )
    @admin_only
    async def shop_add(
        self,
        interaction: discord.Interaction,
        item_code: str,
        buy_price: app_commands.Range[int, 0, 1_000_000_000],
        max_sell_price: app_commands.Range[int, 0, 1_000_000_000],
        min_sell_price: app_commands.Range[int, 0, 1_000_000_000] = 0,
        stock_threshold: app_commands.Range[int, 1, 1_000_000] = 100,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        if min_sell_price > max_sell_price:
            await interaction.followup.send(
                "❌ `min_sell_price` doit être ≤ `max_sell_price`.",
                ephemeral=True,
            )
            return

        with get_db_session() as session:
            item_repository = ItemRepository(session)
            shop_repository = ShopRepository(session)

            item = item_repository.get_by_code(item_code)
            if item is None:
                await interaction.followup.send(
                    f"❌ Objet `{item_code}` introuvable.",
                    ephemeral=True,
                )
                return

            existing = shop_repository.get_by_item_code(item_code)
            if existing is not None:
                await interaction.followup.send(
                    f"❌ `{item.name}` est déjà dans le shop. "
                    "Utilisez `/admin shop_set` pour le modifier.",
                    ephemeral=True,
                )
                return

            shop_repository.create(
                item_definition_id=item.id,
                buy_price=buy_price,
                max_sell_price=max_sell_price,
                min_sell_price=min_sell_price,
                stock_threshold=stock_threshold,
                current_stock=0,
                enabled=True,
            )

        await interaction.followup.send(
            f"✅ **{item.name}** ajouté au shop\n"
            f"• Achat : {buy_price} or\n"
            f"• Vente : {min_sell_price}–{max_sell_price} or "
            f"(saturation à {stock_threshold} en stock)",
            ephemeral=True,
        )

    @admin.command(
        name="shop_set",
        description="Modifie les paramètres d'un objet du shop (champs optionnels)",
    )
    @app_commands.describe(
        item_code="Code de l'objet à modifier",
        buy_price="Nouveau prix d'achat (optionnel)",
        max_sell_price="Nouveau prix de vente max (optionnel)",
        min_sell_price="Nouveau prix de vente min (optionnel)",
        stock_threshold="Nouveau seuil de saturation (optionnel)",
        enabled="Activer ou désactiver l'objet (optionnel)",
    )
    @admin_only
    async def shop_set(
        self,
        interaction: discord.Interaction,
        item_code: str,
        buy_price: app_commands.Range[int, 0, 1_000_000_000] | None = None,
        max_sell_price: app_commands.Range[int, 0, 1_000_000_000] | None = None,
        min_sell_price: app_commands.Range[int, 0, 1_000_000_000] | None = None,
        stock_threshold: app_commands.Range[int, 1, 1_000_000] | None = None,
        enabled: bool | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        with get_db_session() as session:
            shop_repository = ShopRepository(session)
            shop_item = shop_repository.get_by_item_code(item_code)

            if shop_item is None:
                await interaction.followup.send(
                    f"❌ `{item_code}` n'est pas dans le shop.",
                    ephemeral=True,
                )
                return

            new_max = max_sell_price if max_sell_price is not None else shop_item.max_sell_price
            new_min = min_sell_price if min_sell_price is not None else shop_item.min_sell_price
            if new_min > new_max:
                await interaction.followup.send(
                    "❌ `min_sell_price` doit être ≤ `max_sell_price`.",
                    ephemeral=True,
                )
                return

            updated = shop_repository.update(
                shop_item_id=shop_item.id,
                buy_price=buy_price,
                max_sell_price=max_sell_price,
                min_sell_price=min_sell_price,
                stock_threshold=stock_threshold,
                enabled=enabled,
            )

        if updated is None:
            await interaction.followup.send("❌ Échec de la mise à jour.", ephemeral=True)
            return

        await interaction.followup.send(
            f"✅ **{updated.item_definition.name}** mis à jour\n"
            f"• Achat : {updated.buy_price} or\n"
            f"• Vente : {updated.min_sell_price}–{updated.max_sell_price} or "
            f"(saturation à {updated.stock_threshold})\n"
            f"• Stock : {updated.current_stock}\n"
            f"• Actif : {'oui' if updated.enabled else 'non'}",
            ephemeral=True,
        )

    @admin.command(name="shop_remove", description="Supprime un objet du shop")
    @app_commands.describe(item_code="Code de l'objet à retirer")
    @admin_only
    async def shop_remove(
        self,
        interaction: discord.Interaction,
        item_code: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        with get_db_session() as session:
            shop_repository = ShopRepository(session)
            shop_item = shop_repository.get_by_item_code(item_code)

            if shop_item is None:
                await interaction.followup.send(
                    f"❌ `{item_code}` n'est pas dans le shop.",
                    ephemeral=True,
                )
                return

            shop_repository.delete(shop_item.id)

        await interaction.followup.send(
            f"✅ **{shop_item.item_definition.name}** retiré du shop.",
            ephemeral=True,
        )

    @admin.command(
        name="shop_set_stock",
        description="Définit manuellement le stock d'un objet (utile pour reset le prix)",
    )
    @app_commands.describe(item_code="Code de l'objet", stock="Nouvelle valeur de stock (>= 0)")
    @admin_only
    async def shop_set_stock(
        self,
        interaction: discord.Interaction,
        item_code: str,
        stock: app_commands.Range[int, 0, 10_000_000],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        pricing_service = ShopPricingService()

        with get_db_session() as session:
            shop_repository = ShopRepository(session)
            shop_item = shop_repository.get_by_item_code(item_code)

            if shop_item is None:
                await interaction.followup.send(
                    f"❌ `{item_code}` n'est pas dans le shop.",
                    ephemeral=True,
                )
                return

            updated = shop_repository.set_stock(shop_item.id, stock)

        new_sell = pricing_service.current_sell_price(updated)
        await interaction.followup.send(
            f"✅ Stock de **{updated.item_definition.name}** défini à **{stock}**\n"
            f"• Nouveau prix de vente : {new_sell} or",
            ephemeral=True,
        )

    @shop_set.autocomplete("item_code")
    @shop_remove.autocomplete("item_code")
    @shop_set_stock.autocomplete("item_code")
    async def shop_existing_item_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        with get_db_session() as session:
            shop_repository = ShopRepository(session)
            shop_items = shop_repository.list_all(only_enabled=False)

        current_lower = current.lower()
        choices: list[app_commands.Choice[str]] = []

        for shop_item in shop_items:
            item = shop_item.item_definition
            if (
                current_lower in item.code.lower()
                or current_lower in item.name.lower()
            ):
                choices.append(
                    app_commands.Choice(
                        name=f"{item.name} ({item.code})",
                        value=item.code,
                    )
                )

            if len(choices) >= 25:
                break

        return choices

    @shop_add.autocomplete("item_code")
    async def shop_addable_item_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        with get_db_session() as session:
            item_repository = ItemRepository(session)
            shop_repository = ShopRepository(session)
            already_in_shop = {
                shop_item.item_definition.id
                for shop_item in shop_repository.list_all(only_enabled=False)
            }
            items = item_repository.list_all()

        current_lower = current.lower()
        choices: list[app_commands.Choice[str]] = []

        for item in items:
            if item.id in already_in_shop:
                continue
            if (
                current_lower in item.code.lower()
                or current_lower in item.name.lower()
            ):
                choices.append(
                    app_commands.Choice(
                        name=f"{item.name} ({item.code})",
                        value=item.code,
                    )
                )

            if len(choices) >= 25:
                break

        return choices

    # -------------------------- Autocomplete --------------------------

    @give_item.autocomplete("item_code")
    @remove_item.autocomplete("item_code")
    @force_equip.autocomplete("item_code")
    async def item_code_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        with get_db_session() as session:
            item_repository = ItemRepository(session)
            items = item_repository.list_all()

        if not items:
            return []

        current_lower = current.lower()
        choices: list[app_commands.Choice[str]] = []

        for item in items:
            if (
                current_lower in item.code.lower()
                or current_lower in item.name.lower()
            ):
                choices.append(
                    app_commands.Choice(
                        name=f"{item.name} ({item.code})",
                        value=item.code,
                    )
                )

            if len(choices) >= 25:
                break

        return choices

    @set_kills.autocomplete("mob_code")
    @spawn_encounter.autocomplete("mob_code")
    async def mob_code_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        with get_db_session() as session:
            mobs = MobRepository(session).list_all()
        current_lower = current.lower()
        choices: list[app_commands.Choice[str]] = []
        for mob in mobs:
            if current_lower in mob.code.lower() or current_lower in mob.name.lower():
                choices.append(
                    app_commands.Choice(
                        name=f"{mob.name} ({mob.code})", value=mob.code
                    )
                )
            if len(choices) >= 25:
                break
        return choices

    @set_class.autocomplete("class_code")
    async def class_code_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        with get_db_session() as session:
            classes = ClassRepository(session).list_all()
        current_lower = current.lower()
        choices: list[app_commands.Choice[str]] = []
        for cls in classes:
            if current_lower in cls.code.lower() or current_lower in cls.name.lower():
                choices.append(
                    app_commands.Choice(
                        name=f"{cls.name} ({cls.code})", value=cls.code
                    )
                )
            if len(choices) >= 25:
                break
        return choices

    @force_equip.autocomplete("slot")
    @force_unequip.autocomplete("slot")
    async def slot_autocomplete(
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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
