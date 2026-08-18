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
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

# Combat quotidien : inscription minuit→20h50, lancement auto à 21h (Paris).
_PARIS = ZoneInfo("Europe/Paris")
_DAILY_FIGHT_TIME = time(hour=21, minute=0, tzinfo=_PARIS)
_REGISTRATION_CLOSE = time(hour=20, minute=50)  # joins fermés 20h50→minuit

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
from app.shared.formatters import format_int
from discord.utils import escape_markdown


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
        # Fenêtre d'inscription : minuit → 20h50 (Paris). Fermée ensuite,
        # jusqu'au combat de 21h puis réouverte le lendemain à minuit.
        now_paris = datetime.now(_PARIS).timetz()
        if now_paris.replace(tzinfo=None) >= _REGISTRATION_CLOSE:
            await interaction.followup.send(
                "🚪 Inscriptions **fermées** (20h50→21h). Le combat se lance à "
                "**21h**. Reviens t'inscrire après minuit pour le combat de demain.",
                ephemeral=True,
            )
            return
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
        # Détail des inscrits : savoir QUI est déjà là (et donc si ça vaut le
        # coup d'attendre du monde) est le premier réflexe après s'être inscrit.
        roster = await self._build_roster_embed()
        await interaction.followup.send(
            result.message, embed=roster, ephemeral=True,
        )
        if result.success:
            cog = self._resolve_cog(interaction)
            boss_id = await self._resolve_active_boss_id()
            if cog and boss_id:
                await cog.refresh_boss_message(boss_id)

    async def _build_roster_embed(self) -> discord.Embed | None:
        """Liste des inscrits au prochain assaut, avec leur état (a voté / a
        déjà frappé cette semaine) et le bonus d'équipe atteint."""
        with get_db_session() as session:
            repo = WorldBossRepository(session)
            boss = repo.get_active()
            if boss is None:
                return None
            joined = repo.list_joined_participants(boss.id)
            metrics = {
                m.player_id: m
                for m in repo.list_participations_with_metrics(boss.id)
            }
            player_repo = PlayerRepository(session)
            lines: list[str] = []
            for part in joined:
                profile = player_repo.get_profile_by_player_id(part.player_id)
                name = profile.player.display_name if profile else f"#{part.player_id}"
                marks = []
                if getattr(part, "voted_to_start", False):
                    marks.append("🗳️ prêt")
                fought = metrics.get(part.player_id)
                if fought is not None and fought.fights_count > 0:
                    marks.append(f"⚔️ {format_int(fought.damage_dealt)} dégâts")
                suffix = f" — {' · '.join(marks)}" if marks else ""
                lines.append(f"• **{escape_markdown(name)}**{suffix}")

        count = len(lines)
        bonus = min(50, max(0, (count - 1) * 5))
        embed = discord.Embed(
            title=f"🛡️ Inscrits pour l'assaut de 21h — {count}",
            description=(
                "\n".join(lines) if lines
                else "Personne pour l'instant. Sois le premier à t'engager !"
            ),
            color=discord.Color.gold(),
        )
        embed.set_footer(
            text=(f"Bonus d'équipe actuel : +{bonus}% de stats "
                  f"(+5 % par combattant, max +50 %)")
        )
        return embed

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
        label="Combat auto à 21h",
        style=discord.ButtonStyle.primary,
        emoji="⏰",
        custom_id="world_boss:vote",
    )
    async def vote_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        # Le vote a été remplacé par un combat quotidien automatique à 21h.
        # Ce bouton est désormais purement informatif.
        await interaction.response.send_message(
            "⏰ **Combat automatique chaque jour à 21h** (heure de Paris).\n"
            "Inscris-toi via **🤝 Rejoindre** avant 20h50. À 21h, tous les "
            "inscrits combattent le boss, puis la liste est remise à zéro.",
            ephemeral=True,
        )


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
        self.daily_fight_loop.start()

    def cog_unload(self) -> None:
        self.auto_spawn_loop.cancel()
        self.daily_fight_loop.cancel()

    async def _resolve_active_boss_id(self) -> int | None:
        """Id du boss actuellement actif, ou None. (Le même helper existe sur
        WorldBossView ; ici pour la boucle quotidienne du cog.)"""
        with get_db_session() as session:
            boss = WorldBossRepository(session).get_active()
        return boss.id if boss else None

    @tasks.loop(time=_DAILY_FIGHT_TIME)
    async def daily_fight_loop(self) -> None:
        """Combat quotidien automatique à 21h (Paris) : tous les inscrits du
        jour combattent le boss actif, puis la liste est vidée (le use case
        désinscrit chaque combattant). Sans inscrit, on ne fait rien."""
        try:
            boss_id = await self._resolve_active_boss_id()
            if boss_id is None:
                return
            with get_db_session() as session:
                joined = WorldBossRepository(session).count_joined(boss_id)
            if joined <= 0:
                return
            logging.getLogger(__name__).info(
                "Combat quotidien world boss 21h : %s inscrit(s)", joined
            )
            await self.launch_party_fight(boss_id)
        except Exception:
            logging.getLogger(__name__).exception("daily_fight_loop failed")

    @daily_fight_loop.before_loop
    async def _before_daily_fight(self) -> None:
        await self.bot.wait_until_ready()

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

    @boss.command(
        name="moi",
        description="Votre contribution au raid : rang, dégâts, palier, progrès",
    )
    async def boss_me(self, interaction: discord.Interaction) -> None:
        """Vue JOUEUR : où j'en suis dans le raid de la semaine, et est-ce que
        je progresse par rapport à la semaine dernière."""
        await interaction.response.defer(ephemeral=True)
        from app.domain.services.contribution_tier_service import (
            next_tier, share_to_next, tier_for_share,
        )

        with get_db_session() as session:
            repo = WorldBossRepository(session)
            profile = PlayerRepository(session).get_by_discord_id(interaction.user.id)
            if profile is None:
                await interaction.followup.send(
                    "Crée d'abord ton profil avec `/profil`.", ephemeral=True)
                return
            pid = profile.player.id
            boss = repo.get_active()
            history = repo.list_history(limit=6)

            if boss is None:
                await interaction.followup.send(
                    "😴 Aucun raid en cours. Le prochain colosse se dresse "
                    "**lundi** — `/boss historique` pour revoir les précédents.",
                    ephemeral=True)
                return

            metrics = repo.list_participations_with_metrics(boss.id)
            mine = next((m for m in metrics if m.player_id == pid), None)

            # Part de contribution : même formule que la distribution des
            # récompenses (dégâts + encaissé + soins, normalisés).
            tot_d = sum(m.damage_dealt for m in metrics) or 1
            tot_t = sum(m.damage_tanked for m in metrics) or 1
            tot_h = sum(m.hp_healed for m in metrics) or 1

            def _score(m):
                return (m.damage_dealt / tot_d + m.damage_tanked / tot_t
                        + m.hp_healed / tot_h)

            scores = {m.player_id: _score(m) for m in metrics}
            total = sum(scores.values()) or 1.0
            ranking = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)

            # Dégâts du raid PRÉCÉDENT, pour mesurer le progrès d'une semaine
            # à l'autre (c'est la question que se pose le joueur : est-ce que
            # je tape plus fort qu'avant ?).
            previous_damage = 0
            previous_week = ""
            for row in history:
                if row["id"] == boss.id:
                    continue
                prev_part = repo.get_participation(row["id"], pid)
                if prev_part is not None and prev_part.fights_count > 0:
                    previous_damage = prev_part.damage_dealt
                    previous_week = f"semaine {row['week']}"
                break

        if mine is None or mine.fights_count == 0:
            await interaction.followup.send(
                f"⚔️ **{boss.name}** vous attend — vous n'avez pas encore frappé "
                "cette semaine.\nRejoignez le raid : chaque jour à **21h**, "
                "l'équipe lance l'assaut.",
                ephemeral=True)
            return

        share = scores[pid] / total
        rank = next(i for i, (p, _) in enumerate(ranking, 1) if p == pid)
        tier = tier_for_share(share)
        nxt = next_tier(share)

        embed = discord.Embed(
            title=f"⚔️ Votre raid — {boss.name}",
            description=f"Semaine en cours · **{len(metrics)}** combattants engagés",
            color=discord.Color.dark_red(),
        )
        embed.add_field(
            name="🏅 Votre rang",
            value=f"**#{rank}** sur {len(ranking)}\n{tier.format()}",
            inline=True,
        )
        embed.add_field(
            name="📊 Votre part",
            value=f"**{share * 100:.1f} %** de l'effort du raid",
            inline=True,
        )
        embed.add_field(
            name="⚔️ Vos assauts",
            value=f"**{mine.fights_count}** cette semaine",
            inline=True,
        )
        embed.add_field(
            name="💥 Dégâts infligés", value=f"**{format_int(mine.damage_dealt)}**",
            inline=True,
        )
        embed.add_field(
            name="🛡️ Dégâts encaissés", value=f"**{format_int(mine.damage_tanked)}**",
            inline=True,
        )
        embed.add_field(
            name="💚 Soins prodigués", value=f"**{format_int(mine.hp_healed)}**",
            inline=True,
        )
        if nxt is not None:
            manque = share_to_next(share) * 100
            embed.add_field(
                name="🎯 Palier suivant",
                value=(f"{nxt.icon} **{nxt.label}** — il vous manque "
                       f"**{manque:.1f} %** de contribution "
                       f"(×{nxt.gold_multiplier} sur l'or final)"),
                inline=False,
            )
        else:
            embed.add_field(
                name="🎯 Palier",
                value="Vous êtes au **sommet** — palier maximal atteint. 💎",
                inline=False,
            )
        if previous_damage > 0:
            delta = mine.damage_dealt - previous_damage
            pct = delta / previous_damage * 100
            arrow = "📈" if delta > 0 else ("📉" if delta < 0 else "➡️")
            embed.add_field(
                name=f"{arrow} Progrès vs {previous_week or 'la semaine passée'}",
                value=(f"**{format_int(previous_damage)}** → "
                       f"**{format_int(mine.damage_dealt)}** "
                       f"({'+' if delta >= 0 else ''}{pct:.0f} %)"),
                inline=False,
            )
        embed.set_footer(text="Les récompenses sont versées à la mort du boss.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @boss.command(
        name="historique",
        description="Les raids des semaines passées : progrès, MVP, dégâts",
    )
    async def boss_history(self, interaction: discord.Interaction) -> None:
        """Progression de semaine en semaine : c'est ici qu'on voit si la
        communauté frappe plus fort qu'avant."""
        await interaction.response.defer()
        with get_db_session() as session:
            repo = WorldBossRepository(session)
            history = repo.list_history(limit=8)
            player_repo = PlayerRepository(session)
            names: dict[int, str] = {}
            for row in history:
                pid = row["mvp_player_id"]
                if pid and pid not in names:
                    profile = player_repo.get_profile_by_player_id(pid)
                    names[pid] = profile.player.display_name if profile else f"#{pid}"

        if not history:
            await interaction.followup.send(
                "📜 Aucun raid dans les annales — le premier boss de la semaine "
                "vous attend."
            )
            return

        embed = discord.Embed(
            title="📜 Annales des raids",
            description=(
                "Les dernières semaines de guerre. Comparez les dégâts cumulés "
                "et le nombre de combattants : c'est la mesure de vos progrès."
            ),
            color=discord.Color.dark_gold(),
        )

        best_damage = max((r["total_damage"] for r in history), default=0)
        for row in history:
            issue = "🏆 terrassé" if row["killed"] else (
                "⏳ en cours" if row["defeated_at"] is None else "💨 survivant"
            )
            mvp = names.get(row["mvp_player_id"], "—")
            pct = (
                100 * (row["max_hp"] - max(0, row["current_hp"])) / row["max_hp"]
                if row["max_hp"] else 0
            )
            record = " 🔥 **record**" if (
                row["total_damage"] == best_damage and best_damage > 0
            ) else ""
            embed.add_field(
                name=f"Semaine {row['week']} — {row['name']} · {issue}{record}",
                value=(
                    f"💥 **{format_int(row['total_damage'])}** dégâts "
                    f"({pct:.0f} % de ses PV)\n"
                    f"👥 {row['warriors']} combattants · ⚔️ {row['assaults']} assauts\n"
                    f"🥇 MVP : **{escape_markdown(mvp)}** "
                    f"({format_int(row['mvp_damage'])})"
                ),
                inline=False,
            )
        await interaction.followup.send(embed=embed)

    # ---------- API publique pour le pont admin web ----------

    async def admin_spawn_boss(self, boss_code: str) -> tuple[bool, str]:
        """Spawn d'un boss demandé depuis l'admin WEB (via AdminBridgeCog).
        Même chemin que `/boss spawn`, sans interaction Discord."""
        if not boss_code:
            return False, "Code de boss manquant."
        with get_db_session() as session:
            result = SpawnWorldBossUseCase(
                world_boss_repository=WorldBossRepository(session),
            ).execute(boss_code=boss_code)
        if not result.success or result.boss is None:
            return False, result.message
        message = await self._post_boss_message(result.boss)
        if message is None:
            return False, "Channel boss introuvable (vérifier BOSS_CHANNEL_ID)."
        return True, f"{result.message} — posté dans le canal boss."

    async def admin_stop_boss(self) -> tuple[bool, str]:
        """Arrêt du boss actif depuis l'admin WEB : marque defeated et supprime
        le message, sans distribuer de récompenses (comme `/boss stop`)."""
        with get_db_session() as session:
            repo = WorldBossRepository(session)
            boss = repo.get_active()
            if boss is None or not boss.is_alive:
                return False, "Aucun world boss actif à arrêter."
            repo.mark_defeated(boss.id)
            boss_name, message_id = boss.name, boss.channel_message_id
        if message_id is not None:
            channel = _get_boss_channel(self.bot)
            if channel is not None:
                try:
                    msg = await channel.fetch_message(message_id)
                    await msg.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass
        return True, f"World boss {boss_name} arrêté (aucune récompense distribuée)."

    # ---------- helpers ----------

    async def _post_boss_message(self, boss) -> discord.Message | None:
        """Annonce du raid en DEUX messages, pour éviter la surcharge :

        1. un message de RASSEMBLEMENT : ping, lore court et règles du raid
           (comment ça marche, quand on frappe, ce qu'on gagne) ;
        2. le message-IMAGE : la bannière porte tout l'état du raid (PV, phase,
           stats du boss, élément et faiblesses, classement, semaine). C'est ce
           second message qui porte les boutons et qui est rafraîchi — il n'a
           donc AUCUN embed, pour ne rien dupliquer de l'image.
        """
        channel = _get_boss_channel(self.bot)
        if channel is None:
            return None

        # ---------- 1. message de rassemblement ----------
        rules = discord.Embed(
            title=f"⚔️ Le raid de la semaine commence — {boss.name}",
            description=(
                "Un colosse se dresse. Il restera là **toute la semaine** : "
                "chaque PV que vous lui arrachez est **définitif**, il ne "
                "régénère jamais."
            ),
            color=discord.Color.dark_red(),
        )
        rules.add_field(
            name="🤝 Comment participer",
            value=(
                "**Rejoindre** pour vous inscrire, puis **Voter pour lancer** "
                "quand vous êtes prêt. Le combat part dès que tous les inscrits "
                "ont voté — et de toute façon **automatiquement à 21h** chaque "
                "jour."
            ),
            inline=False,
        )
        rules.add_field(
            name="⏳ Rythme",
            value=(
                "**1 assaut par jour et par joueur.** Plus vous êtes nombreux, "
                "plus l'équipe est forte : **+5 % de stats par combattant "
                "supplémentaire** (jusqu'à +50 %)."
            ),
            inline=False,
        )
        rules.add_field(
            name="🎁 Récompenses",
            value=(
                "À sa mort, tout le monde est payé **selon sa contribution** "
                "(dégâts infligés, dégâts encaissés, soins prodigués). "
                "Le podium et les meilleurs rôles reçoivent bien plus.\n"
                "`/boss` pour votre contribution · `/boss historique` pour les "
                "semaines passées."
            ),
            inline=False,
        )
        try:
            await channel.send(content="@here", embed=rules)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("message de rassemblement échoué")

        # ---------- 2. message-image (porte les boutons + rafraîchi) ----------
        view = WorldBossView(self)
        attachment = None
        try:
            from app.bot.rendering.world_boss_banner import compose_raid_banner
            from app.bot.runtime.raid_banner_builder import build_raid_banner_data
            from app.shared.paths import GENERATED_ENCOUNTERS_DIR
            with get_db_session() as session:
                banner_data = build_raid_banner_data(session, boss)
            out = GENERATED_ENCOUNTERS_DIR / f"world_boss_{boss.id}.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(compose_raid_banner, str(out), banner_data)
            attachment = discord.File(str(out), filename=out.name)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("raid banner (spawn) failed")

        send_kwargs: dict = {"view": view}
        if attachment is not None:
            send_kwargs["file"] = attachment
        else:
            send_kwargs["content"] = f"**{boss.name}** — bannière indisponible."
        message = await channel.send(**send_kwargs)
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
                from app.bot.runtime.raid_banner_builder import (
                    build_raid_banner_data,
                )
                banner_data = build_raid_banner_data(session, boss)

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

            # Bannière de RAID : le visuel dédié à l'événement hebdomadaire
            # (barre de PV géante + phase + classement de contribution + jour
            # de la semaine). Remplace l'ancien rendu d'encounter générique,
            # qui donnait au boss l'allure d'un combat ordinaire.
            from app.bot.rendering.world_boss_banner import compose_raid_banner
            from app.shared.paths import GENERATED_ENCOUNTERS_DIR
            out = GENERATED_ENCOUNTERS_DIR / f"world_boss_{boss.id}.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            try:
                # Rendu Pillow → hors de l'event loop (cf. audit B5).
                await asyncio.to_thread(compose_raid_banner, str(out), banner_data)
                attachment = discord.File(str(out), filename=out.name)
            except Exception:
                attachment = None

            # Aucun embed : toute l'information vit dans la bannière (pas de
            # doublon). Les boutons disparaissent quand le boss est mort.
            view = WorldBossView(self) if boss.is_alive else None
            if attachment is not None:
                await message.edit(content=None, embed=None, view=view,
                                   attachments=[attachment])
            else:
                await message.edit(view=view)
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
                # PV avant l'assaut : sert à détecter le franchissement d'un
                # palier de phase (la dramaturgie de la semaine).
                boss_before = WorldBossRepository(session).get_by_id(boss_id)
                hp_before = boss_before.current_hp if boss_before else 0
                max_hp = boss_before.max_hp if boss_before else 0
                result = use_case.execute(boss_id)

            channel = _get_boss_channel(self.bot)
            if channel is not None:
                await channel.send(result.message)
                milestone = self._phase_milestone(hp_before, result.boss_remaining_hp, max_hp)
                if milestone and not result.boss_defeated:
                    await channel.send(milestone)
            await self.refresh_boss_message(boss_id)
            if result.boss_defeated:
                await self.complete_boss(boss_id)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("launch_party_fight failed")

    @staticmethod
    def _phase_milestone(hp_before: int, hp_after: int, max_hp: int) -> str | None:
        """Annonce quand le raid fait basculer le boss dans une nouvelle phase.

        Ces paliers sont le rythme dramatique de la semaine : ils récompensent
        l'effort collectif par un événement visible de tous, et rappellent au
        serveur que le combat progresse."""
        if max_hp <= 0 or hp_after >= hp_before:
            return None
        from app.bot.rendering.world_boss_banner import PHASES

        before = hp_before / max_hp
        after = hp_after / max_hp
        announces = {
            0.75: ("⚔️ **Première entaille sérieuse.** Le colosse saigne — "
                   "il entre en **COLÈRE**. Ses coups redoublent."),
            0.50: ("🔥 **La moitié est tombée.** Le monstre bascule en "
                   "**FUREUR** : plus rien ne le retient."),
            0.25: ("💀 **Dernier quart.** Le titan entre en **AGONIE** — "
                   "un ultime effort et il s'effondre. Tous à l'assaut !"),
        }
        for threshold, _, _ in PHASES[:-1]:
            if before > threshold >= after:
                return announces.get(threshold)
        return None

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

        # Bannière de VICTOIRE : le tableau d'honneur complet de la semaine
        # (paliers, dégâts, encaissé, soins, or) — l'aboutissement du raid.
        attachment = None
        try:
            from app.bot.rendering.world_boss_banner import (
                VictoryBannerData, VictoryRow, compose_victory_banner,
            )
            from app.bot.runtime.raid_banner_builder import raid_day_index, week_label
            from app.shared.paths import GENERATED_ENCOUNTERS_DIR

            with get_db_session() as session:
                repo = WorldBossRepository(session)
                metrics = {
                    m.player_id: m
                    for m in repo.list_participations_with_metrics(boss_id)
                }
                history = repo.list_history(limit=20)
            total_damage = sum(m.damage_dealt for m in metrics.values())
            past = [h["total_damage"] for h in history if h["id"] != boss_id]
            rows = [
                VictoryRow(
                    display_name=r.display_name,
                    damage=r.damage,
                    tanked=metrics[r.player_id].damage_tanked if r.player_id in metrics else 0,
                    healed=metrics[r.player_id].hp_healed if r.player_id in metrics else 0,
                    tier_label=r.tier_label,
                    share=r.share,
                    gold=r.gold,
                )
                for r in result.rewards
            ]
            data = VictoryBannerData(
                boss_name=boss.name,
                image_name=boss.image_name or "",
                max_hp=boss.max_hp,
                week_label=week_label(boss.spawned_at),
                days_taken=raid_day_index(boss.spawned_at),
                warriors=len(metrics),
                assaults=sum(m.fights_count for m in metrics.values()),
                rows=rows,
                is_record=bool(past) and total_damage > max(past),
            )
            out = GENERATED_ENCOUNTERS_DIR / f"world_boss_victory_{boss_id}.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(compose_victory_banner, str(out), data)
            attachment = discord.File(str(out), filename=out.name)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("victory banner failed")

        content = (
            f"🏆 **{boss.name} est tombé !** Le raid de la semaine est terminé — "
            "récompenses distribuées selon la contribution de chacun."
        )
        if attachment is not None:
            await channel.send(content=content, file=attachment)
        else:
            await channel.send(embed=build_boss_defeated_embed(boss, result.rewards))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WorldBossCog(bot))
