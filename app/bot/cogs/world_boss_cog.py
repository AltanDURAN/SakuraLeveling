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

import asyncio

import discord
from discord import app_commands
from discord.ext import commands, tasks

from app.application.use_cases.world_boss import (
    CompleteWorldBossUseCase,
    JoinWorldBossUseCase,
    LaunchPartyFightWorldBossUseCase,
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
        label="Voter pour lancer",
        style=discord.ButtonStyle.primary,
        emoji="🗳️",
        custom_id="world_boss:vote",
    )
    async def vote_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        from app.application.use_cases.world_boss import (
            VoteForFightWorldBossUseCase,
        )
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            use_case = VoteForFightWorldBossUseCase(
                world_boss_repository=WorldBossRepository(session),
                player_repository=PlayerRepository(session),
            )
            result = use_case.execute(discord_id=interaction.user.id)
        await interaction.followup.send(result.message, ephemeral=True)

        cog = self._resolve_cog(interaction)
        if cog is None:
            return
        # Toujours refresh le message pour mettre à jour le compteur
        # de votes (X/Y) côté View.
        if result.boss_id:
            await cog.refresh_boss_message(result.boss_id)

        if result.success and result.should_launch and result.boss_id:
            # Tous les inscrits ont voté → lancer combat collectif
            await cog.launch_party_fight(result.boss_id)


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

    @boss.command(
        name="stop",
        description="[Admin] Arrête le world boss en cours (pas de récompenses distribuées)",
    )
    @admin_only
    async def boss_stop(self, interaction: discord.Interaction) -> None:
        """Stoppe le boss actif : marque defeated, supprime le message
        Discord, sans distribuer de récompenses. Pour cleanup / debug."""
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            repo = WorldBossRepository(session)
            boss = repo.get_active()
            if boss is None or not boss.is_alive:
                await interaction.followup.send(
                    "ℹ️ Aucun world boss actif à arrêter.", ephemeral=True,
                )
                return
            repo.mark_defeated(boss.id)
            boss_name = boss.name
            message_id = boss.channel_message_id

        # Supprime le message Discord du boss (s'il existe encore)
        if message_id is not None:
            channel = _get_boss_channel(self.bot)
            if channel is not None:
                try:
                    msg = await channel.fetch_message(message_id)
                    await msg.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass

        await interaction.followup.send(
            f"🛑 World boss **{boss_name}** arrêté (aucune récompense distribuée).",
            ephemeral=True,
        )

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
                participants = repo.list_joined_participants(boss_id)
                num = len(participants)
                votes = repo.count_voted(boss_id)
                fought = sum(
                    1
                    for p in repo.list_participations_with_metrics(boss_id)
                    if p.fights_count > 0
                )
                # Charge display names des participants pour la banner
                player_payload: list[dict] = []
                for part in participants:
                    profile = PlayerRepository(session).get_profile_by_player_id(
                        part.player_id,
                    )
                    name = profile.player.display_name if profile else f"#{part.player_id}"
                    player_payload.append({
                        "name": name, "avatar_url": "",
                        "current_hp": part.damage_dealt and 1 or 1,
                        "max_hp": 1,
                    })

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

            # Rendu PNG comme un spawn d'encounter naturel
            from app.bot.rendering.fight_scene import compose_players_banner
            from app.shared.paths import (
                LANDSCAPES_ASSETS_DIR, GENERATED_ENCOUNTERS_DIR,
                MOBS_ASSETS_DIR,
            )
            mob_image_name = boss.image_name
            if not mob_image_name or not (MOBS_ASSETS_DIR / mob_image_name).exists():
                mob_image_name = "boss_default.png"
            out = GENERATED_ENCOUNTERS_DIR / f"world_boss_{boss.id}.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            try:
                # Rendu sync + download avatars → off-thread (cf. audit B5).
                await asyncio.to_thread(
                    compose_players_banner,
                    players=player_payload,
                    mob={
                        "name": boss.name,
                        "image_name": mob_image_name,
                        "current_hp": boss.current_hp,
                        "max_hp": boss.max_hp,
                        "attack": boss.attack,
                        "defense": boss.defense,
                        "speed": boss.speed,
                        "crit_chance": boss.crit_chance,
                        "crit_damage": boss.crit_damage,
                        "dodge": boss.dodge,
                        "hp_regeneration": 0,
                    },
                    output_path=str(out),
                    background_path=str(
                        LANDSCAPES_ASSETS_DIR / "clairiere_sinistre.png"
                    ),
                    players_power_score="",
                )
                attachment = discord.File(str(out), filename=out.name)
            except Exception:
                attachment = None

            embed = build_boss_dashboard_embed(
                boss, num, bonus_pct, num_fought=fought,
                votes=votes,
            )
            if attachment is not None:
                embed.set_image(url=f"attachment://{out.name}")
            view = WorldBossView(self) if boss.is_alive else None
            if attachment is not None:
                await message.edit(
                    embed=embed, view=view, attachments=[attachment],
                )
            else:
                await message.edit(embed=embed, view=view, attachments=[])
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "refresh_boss_message failed",
            )

    async def launch_party_fight(self, boss_id: int) -> None:
        """Lance le combat collectif quand tous les voteurs sont prêts."""
        try:
            with get_db_session() as session:
                use_case = LaunchPartyFightWorldBossUseCase(
                    world_boss_repository=WorldBossRepository(session),
                    player_repository=PlayerRepository(session),
                    equipment_repository=EquipmentRepository(session),
                    class_repository=ClassRepository(session),
                    skill_allocation_repository=PlayerSkillAllocationRepository(session),
                    cooldown_repository=CooldownRepository(session),
                    stats_service=StatsService(),
                    scaling_service=WorldBossScalingService(),
                    cooldown_service=CooldownService(),
                    modifier_service=BossModifierService(),
                )
                result = use_case.execute(boss_id)

            channel = _get_boss_channel(self.bot)
            if channel is not None:
                await channel.send(result.message)
            await self.refresh_boss_message(boss_id)
            if result.boss_defeated:
                await self.complete_boss(boss_id)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("launch_party_fight failed")

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
