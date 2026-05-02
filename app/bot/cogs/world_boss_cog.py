"""Cog du système de world boss.

V1 — squelette testable :
    • /admin boss spawn <mob_code> [name] : force un spawn d'un boss à
      partir d'un mob existant boosté ×100
    • View attachée au message du boss : Rejoindre / Quitter / Lancer le combat
    • Le boss reste actif jusqu'à mort (HP persistés en DB entre les combats)
    • Cooldown 1 combat / joueur / jour, reset à minuit UTC

À faire plus tard :
    • Auto-spawn aléatoire 1×/semaine (lundi-dimanche)
    • Liste de bosses dédiée (boss_definitions JSON) avec stats finement
      réglées et particularités
    • Cooldown de respawn 7 jours après défaite
"""

import discord
from discord import app_commands
from discord.ext import commands

from app.application.use_cases.world_boss import (
    CompleteWorldBossUseCase,
    FightWorldBossUseCase,
    JoinWorldBossUseCase,
    LeaveWorldBossUseCase,
    SpawnWorldBossUseCase,
)
from app.bot.checks.admin_check import admin_only
from app.bot.embeds.world_boss_embeds import (
    build_boss_dashboard_embed,
    build_boss_defeated_embed,
)
from app.domain.services.combat_service import CombatService
from app.domain.services.cooldown_service import CooldownService
from app.domain.services.stats_service import StatsService
from app.domain.services.world_boss_scaling_service import WorldBossScalingService
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.db.repositories.world_boss_repository import WorldBossRepository
from app.infrastructure.db.session import get_db_session


def _get_boss_channel(bot: commands.Bot):
    channel_id = settings.boss_channel_id or settings.encounter_channel_id
    return bot.get_channel(channel_id)


class WorldBossView(discord.ui.View):
    """View attachée au message du boss (3 boutons : rejoindre/quitter/combattre)."""

    def __init__(self, cog: "WorldBossCog", boss_id: int) -> None:
        super().__init__(timeout=None)  # persistent par défaut tant que le boss vit
        self.cog = cog
        self.boss_id = boss_id

    @discord.ui.button(label="Rejoindre", style=discord.ButtonStyle.success, emoji="🤝")
    async def join_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            use_case = JoinWorldBossUseCase(
                world_boss_repository=WorldBossRepository(session),
                player_repository=PlayerRepository(session),
            )
            result = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )
        await interaction.followup.send(result.message, ephemeral=True)
        if result.success:
            await self.cog.refresh_boss_message(self.boss_id)

    @discord.ui.button(label="Quitter", style=discord.ButtonStyle.secondary, emoji="🚪")
    async def leave_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            use_case = LeaveWorldBossUseCase(
                world_boss_repository=WorldBossRepository(session),
                player_repository=PlayerRepository(session),
            )
            result = use_case.execute(discord_id=interaction.user.id)
        await interaction.followup.send(result.message, ephemeral=True)
        if result.success:
            await self.cog.refresh_boss_message(self.boss_id)

    @discord.ui.button(
        label="Lancer le combat", style=discord.ButtonStyle.primary, emoji="⚔️"
    )
    async def fight_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            use_case = FightWorldBossUseCase(
                world_boss_repository=WorldBossRepository(session),
                player_repository=PlayerRepository(session),
                equipment_repository=EquipmentRepository(session),
                class_repository=ClassRepository(session),
                skill_allocation_repository=PlayerSkillAllocationRepository(session),
                cooldown_repository=CooldownRepository(session),
                stats_service=StatsService(),
                scaling_service=WorldBossScalingService(),
                combat_service=CombatService(),
                cooldown_service=CooldownService(),
            )
            result = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )
        await interaction.followup.send(result.message, ephemeral=True)
        if result.success:
            await self.cog.refresh_boss_message(self.boss_id)
            if result.boss_defeated:
                await self.cog.complete_boss(self.boss_id, interaction)


class WorldBossCog(commands.Cog):
    """Cog admin + interactions joueur pour le world boss."""

    boss = app_commands.Group(name="boss", description="Gestion des world bosses")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @boss.command(
        name="spawn",
        description="[Admin] Spawn un world boss à partir d'un mob (boost ×100)",
    )
    @app_commands.describe(
        mob_code="Code du mob de base (autocomplete sur les mobs existants)",
        custom_name="Nom personnalisé du boss (optionnel)",
    )
    @admin_only
    async def boss_spawn(
        self,
        interaction: discord.Interaction,
        mob_code: str,
        custom_name: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        with get_db_session() as session:
            use_case = SpawnWorldBossUseCase(
                world_boss_repository=WorldBossRepository(session),
                mob_repository=MobRepository(session),
            )
            result = use_case.execute(mob_code=mob_code, custom_name=custom_name)

        if not result.success or result.boss is None:
            await interaction.followup.send(result.message, ephemeral=True)
            return

        # Poste le message du boss dans le canal dédié
        channel = _get_boss_channel(self.bot)
        if channel is None:
            await interaction.followup.send(
                "❌ Channel boss introuvable (vérifier `BOSS_CHANNEL_ID`).",
                ephemeral=True,
            )
            return

        view = WorldBossView(self, result.boss.id)
        embed = build_boss_dashboard_embed(
            result.boss, num_participants=0, team_bonus_pct=0,
        )
        message = await channel.send(
            content=f"⚡ Un nouveau **world boss** apparaît : **{result.boss.name}** !",
            embed=embed,
            view=view,
        )

        with get_db_session() as session:
            WorldBossRepository(session).set_message_id(result.boss.id, message.id)

        await interaction.followup.send(
            f"{result.message}\n📍 Posté dans <#{channel.id}>.",
            ephemeral=True,
        )

    @boss_spawn.autocomplete("mob_code")
    async def mob_code_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        with get_db_session() as session:
            mobs = MobRepository(session).list_all()
        current_lower = current.lower()
        return [
            app_commands.Choice(name=f"{m.name} ({m.code})", value=m.code)
            for m in mobs
            if current_lower in m.code.lower() or current_lower in m.name.lower()
        ][:25]

    # ---------- helpers ----------

    async def refresh_boss_message(self, boss_id: int) -> None:
        """Re-construit l'embed du boss et l'édite. Tolérant aux erreurs."""
        try:
            with get_db_session() as session:
                repo = WorldBossRepository(session)
                boss = repo.get_by_id(boss_id)
                if boss is None or boss.channel_message_id is None:
                    return
                num = repo.count_joined(boss_id)

            scaling = WorldBossScalingService()
            bonus_pct = int(
                (scaling.compute_team_bonus_multiplier(num) - 1) * 100
            )

            channel = _get_boss_channel(self.bot)
            if channel is None:
                return
            try:
                message = await channel.fetch_message(boss.channel_message_id)
            except discord.NotFound:
                return
            embed = build_boss_dashboard_embed(boss, num, bonus_pct)
            view = WorldBossView(self, boss_id) if boss.is_alive else None
            await message.edit(embed=embed, view=view)
        except Exception:
            # Best effort — un échec d'édition ne doit pas planter une commande
            pass

    async def complete_boss(
        self, boss_id: int, interaction: discord.Interaction
    ) -> None:
        """Distribue les récompenses et poste le récap dans le canal."""
        with get_db_session() as session:
            use_case = CompleteWorldBossUseCase(
                world_boss_repository=WorldBossRepository(session),
                player_repository=PlayerRepository(session),
                item_repository=ItemRepository(session),
                inventory_repository=InventoryRepository(session),
            )
            result = use_case.execute(boss_id)
            boss = WorldBossRepository(session).get_by_id(boss_id)

        channel = _get_boss_channel(self.bot)
        if channel is None or boss is None:
            return
        embed = build_boss_defeated_embed(boss, result.rewards)
        await channel.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WorldBossCog(bot))
