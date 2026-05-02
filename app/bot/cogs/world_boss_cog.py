"""Cog du système de world boss.

Système final V1 :
    • /boss spawn <boss_code>     [admin]   force un spawn d'un boss défini
                                            dans boss_definitions.json
    • /boss list                  [public]  liste les boss définis (vue admin
                                            mais pratique pour tous)
    • View attachée au message du boss : Rejoindre / Quitter / Lancer combat
    • Le boss reste actif jusqu'à mort (HP persistés en DB entre combats)
    • Cooldown 1 combat / joueur / jour, reset à minuit UTC
    • Modifiers du boss (immunity, enrage, crit_immunity) appliqués en combat
    • Auto-spawn loop : check toutes les heures. Si pas de boss actif et
      cooldown respawn 7j passé, tirage aléatoire pondéré (5%/heure) →
      spawn dans le canal boss

Reste à venir (besoin liste user) :
    • Bosses définitifs avec stats équilibrées
    • Particularités custom (modifiers étendus : phases, summons, etc.)
"""

import discord
from discord import app_commands
from discord.ext import commands, tasks

from app.application.use_cases.world_boss import (
    CompleteWorldBossUseCase,
    FightWorldBossUseCase,
    JoinWorldBossUseCase,
    LeaveWorldBossUseCase,
    SpawnRandomWorldBossUseCase,
    SpawnWorldBossUseCase,
)
from app.bot.checks.admin_check import admin_only
from app.bot.embeds.world_boss_embeds import (
    build_boss_dashboard_embed,
    build_boss_defeated_embed,
)
from app.domain.services.boss_modifier_service import BossModifierService
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
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.db.repositories.world_boss_repository import WorldBossRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.world_boss.boss_definition_loader import list_definitions


def _get_boss_channel(bot: commands.Bot):
    channel_id = settings.boss_channel_id or settings.encounter_channel_id
    return bot.get_channel(channel_id)


class WorldBossView(discord.ui.View):
    """View persistante attachée au message du boss (3 boutons).

    Persistante = `timeout=None` + chaque bouton a un `custom_id` stable.
    Au démarrage du bot, le cog ré-enregistre une instance via
    `bot.add_view(...)` pour que Discord reconnecte les clics aux callbacks
    sans avoir besoin du message original. Indispensable pour un boss qui
    peut survivre à un reboot.
    """

    def __init__(self, cog: "WorldBossCog | None" = None) -> None:
        super().__init__(timeout=None)
        self.cog = cog

    def _resolve_cog(self, interaction: discord.Interaction) -> "WorldBossCog | None":
        """Si la view a été restaurée sans cog (pas de référence au reboot),
        on récupère le cog vivant depuis le bot."""
        if self.cog is not None:
            return self.cog
        return interaction.client.get_cog("WorldBossCog")

    async def _resolve_active_boss_id(self) -> int | None:
        """Trouve l'id du boss actuellement actif (peu importe quel message
        a déclenché l'interaction). Renvoie None si aucun boss actif."""
        with get_db_session() as session:
            boss = WorldBossRepository(session).get_active()
        return boss.id if boss else None

    @discord.ui.button(
        label="Rejoindre",
        style=discord.ButtonStyle.success,
        emoji="🤝",
        custom_id="world_boss:join",
    )
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
            cog = self._resolve_cog(interaction)
            boss_id = await self._resolve_active_boss_id()
            if cog and boss_id:
                await cog.refresh_boss_message(boss_id)

    @discord.ui.button(
        label="Quitter",
        style=discord.ButtonStyle.secondary,
        emoji="🚪",
        custom_id="world_boss:leave",
    )
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
            cog = self._resolve_cog(interaction)
            boss_id = await self._resolve_active_boss_id()
            if cog and boss_id:
                await cog.refresh_boss_message(boss_id)

    @discord.ui.button(
        label="Lancer le combat",
        style=discord.ButtonStyle.primary,
        emoji="⚔️",
        custom_id="world_boss:fight",
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
                modifier_service=BossModifierService(),
            )
            result = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )
        await interaction.followup.send(result.message, ephemeral=True)
        if result.success:
            cog = self._resolve_cog(interaction)
            boss_id = await self._resolve_active_boss_id()
            if cog and boss_id:
                await cog.refresh_boss_message(boss_id)
            if result.boss_defeated and cog:
                # boss_id ici peut être None (déjà passé en defeated) — on
                # le retrouve depuis le get_latest_defeated.
                with get_db_session() as session:
                    last = WorldBossRepository(session).get_latest_defeated()
                if last:
                    await cog.complete_boss(last.id)


class WorldBossCog(commands.Cog):
    """Cog admin + interactions joueur pour le world boss.

    Ajoute un loop horaire `auto_spawn_loop` qui peut faire apparaître un
    boss aléatoire si :
        • Aucun boss actif
        • Dernière défaite > 7 jours OU jamais spawné
        • Tirage 5% / heure (en moyenne ~1 spawn/jour après la fenêtre)
    """

    boss = app_commands.Group(name="boss", description="Gestion des world bosses")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # Enregistre la view persistante : Discord pourra reconnecter les
        # clics (custom_id stables) même si le bot a redémarré.
        self.bot.add_view(WorldBossView(self))
        self.auto_spawn_loop.start()

    def cog_unload(self) -> None:
        self.auto_spawn_loop.cancel()

    @tasks.loop(hours=1)
    async def auto_spawn_loop(self) -> None:
        try:
            with get_db_session() as session:
                use_case = SpawnRandomWorldBossUseCase(
                    world_boss_repository=WorldBossRepository(session),
                )
                decision = use_case.execute()
            if decision.spawned and decision.boss is not None:
                await self._post_boss_message(decision.boss)
        except Exception:
            # Best effort — un échec ne doit jamais planter le bot
            pass

    @auto_spawn_loop.before_loop
    async def _before_auto_spawn(self) -> None:
        await self.bot.wait_until_ready()

    @boss.command(
        name="spawn",
        description="[Admin] Spawn manuel d'un world boss défini",
    )
    @app_commands.describe(boss_code="Code du boss (autocomplete)")
    @admin_only
    async def boss_spawn(
        self,
        interaction: discord.Interaction,
        boss_code: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        with get_db_session() as session:
            use_case = SpawnWorldBossUseCase(
                world_boss_repository=WorldBossRepository(session),
            )
            result = use_case.execute(boss_code=boss_code)

        if not result.success or result.boss is None:
            await interaction.followup.send(result.message, ephemeral=True)
            return

        message = await self._post_boss_message(result.boss)
        if message is None:
            await interaction.followup.send(
                "❌ Channel boss introuvable (vérifier `BOSS_CHANNEL_ID`).",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"{result.message}\n📍 Posté dans le canal boss.", ephemeral=True
        )

    @boss_spawn.autocomplete("boss_code")
    async def boss_code_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        current_lower = current.lower()
        defs = list_definitions()
        out: list[app_commands.Choice[str]] = []
        for d in defs:
            if (
                current_lower in d.code.lower()
                or current_lower in d.name.lower()
                or current_lower in d.tier.lower()
            ):
                out.append(
                    app_commands.Choice(
                        name=f"[{d.tier}] {d.name} ({d.code})",
                        value=d.code,
                    )
                )
            if len(out) >= 25:
                break
        return out

    @boss.command(
        name="list",
        description="Liste les world bosses définis (codes + tier + lore)",
    )
    async def boss_list(self, interaction: discord.Interaction) -> None:
        defs = list_definitions()
        if not defs:
            await interaction.response.send_message(
                "ℹ️ Aucun boss défini.", ephemeral=True,
            )
            return

        lines: list[str] = []
        for d in defs:
            mod_keys = ", ".join(d.modifiers.keys()) if d.modifiers else "—"
            lines.append(
                f"**[{d.tier}] {d.name}** (`{d.code}`)\n"
                f"  ❤️ {d.max_hp:,} PV | ⚔️ {d.attack} atk | 🛡️ {d.defense} def | "
                f"💨 {d.speed} spd | poids {d.spawn_weight}\n"
                f"  Particularités : {mod_keys}\n"
                f"  _{d.lore or d.description}_"
            )
        embed = discord.Embed(
            title="📜 Catalogue des World Bosses",
            description="\n\n".join(lines)[:4000],
            color=discord.Color.dark_purple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---------- helpers ----------

    async def _post_boss_message(self, boss) -> discord.Message | None:
        channel = _get_boss_channel(self.bot)
        if channel is None:
            return None

        view = WorldBossView(self)
        embed = build_boss_dashboard_embed(
            boss, num_participants=0, team_bonus_pct=0,
        )
        message = await channel.send(
            content=f"⚡ Un nouveau **world boss** apparaît : **{boss.name}** !",
            embed=embed,
            view=view,
        )
        with get_db_session() as session:
            WorldBossRepository(session).set_message_id(boss.id, message.id)
        return message

    async def refresh_boss_message(self, boss_id: int) -> None:
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
            view = WorldBossView(self) if boss.is_alive else None
            await message.edit(embed=embed, view=view)
        except Exception:
            pass

    async def complete_boss(self, boss_id: int) -> None:
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
