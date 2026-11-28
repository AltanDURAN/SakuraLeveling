"""Commandes `/admin` sur les joueurs et le jeu (ressources, niveau, PV,
rang, accès, porte, victoires, défis, combats, reset, saison, apparition
forcée). Mixin d'`AdminCog`, sorti d'`admin_cog.py` le 28/11/2026 (audit) :
texte inchangé. ⚠️ Aucune commande ne reste dans `admin_cog.py` : discord.py
exécute le fichier d'une extension à CHAQUE chargement, et une commande
de ce fichier se réinscrirait dans le groupe partagé (CommandAlreadyRegistered)."""

import discord
from discord import app_commands
from app.application.services.player_stats_resolver import resolve_player_stats
from app.application.use_cases.reset_player import ResetPlayerUseCase
from app.bot.checks.admin_check import admin_only
from app.bot.rank_roles import RANK_ORDER, set_rank_role
from app.infrastructure.config.settings import settings
from app.shared.enums import ALL_ELEMENTS, ELEMENT_LABELS
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.repositories.player_health_repository import (
    PlayerHealthRepository,
)
from app.infrastructure.db.repositories.player_kill_repository import PlayerKillRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session
from app.bot.cogs.admin_group import _RESOURCE_CHOICES, admin


class AdminPlayersMixin:
    @admin.command(name="set", description="Définit une ressource d'un joueur à une valeur")
    @app_commands.describe(
        target="Joueur ciblé",
        resource="Type de ressource",
        amount="Nouvelle valeur (≥ 0)",
    )
    @app_commands.choices(resource=_RESOURCE_CHOICES)
    @admin_only
    async def set_resource(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        resource: app_commands.Choice[str],
        amount: app_commands.Range[int, 0, 1_000_000_000],
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        msg = await self._apply_resource("set", resource.value, target, amount)
        await interaction.followup.send(msg, ephemeral=True)

    @admin.command(name="give", description="Ajoute une quantité de ressource à un joueur")
    @app_commands.describe(
        target="Joueur ciblé",
        resource="Type de ressource",
        amount="Quantité à ajouter (≥ 1)",
    )
    @app_commands.choices(resource=_RESOURCE_CHOICES)
    @admin_only
    async def give_resource(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        resource: app_commands.Choice[str],
        amount: app_commands.Range[int, 1, 1_000_000_000],
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        msg = await self._apply_resource("give", resource.value, target, amount)
        await interaction.followup.send(msg, ephemeral=True)

    @admin.command(name="remove", description="Retire une quantité de ressource à un joueur (clamp à 0)")
    @app_commands.describe(
        target="Joueur ciblé",
        resource="Type de ressource",
        amount="Quantité à retirer (≥ 1)",
    )
    @app_commands.choices(resource=_RESOURCE_CHOICES)
    @admin_only
    async def remove_resource(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        resource: app_commands.Choice[str],
        amount: app_commands.Range[int, 1, 1_000_000_000],
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        msg = await self._apply_resource("remove", resource.value, target, amount)
        await interaction.followup.send(msg, ephemeral=True)

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
                new_skill_points=profile.progression.skill_points, source="admin",
            )

        await interaction.followup.send(
            f"✅ Niveau de {target.mention} défini à **{level}**.",
            ephemeral=True,
        )

    @admin.command(
        name="heal_full",
        description="Restaure tous les PV ET le mana d'un joueur à leur max courant",
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
            from app.infrastructure.db.repositories.player_mana_repository import (
                PlayerManaRepository,
            )
            player_repo = PlayerRepository(session)
            profile = player_repo.get_by_discord_id(target.id)
            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.", ephemeral=True
                )
                return
            equipped = EquipmentRepository(session).list_by_player_id(profile.player.id)
            # Chaîne complète (arbre + sets + titres) pour heal_full.
            stats = resolve_player_stats(session, profile, equipped)
            health_repo = PlayerHealthRepository(session)
            health_repo.get_or_create(profile.player.id, default_current_hp=stats.max_hp)
            health_repo.update_current_hp(profile.player.id, stats.max_hp)
            mana_repo = PlayerManaRepository(session)
            mana_repo.get_or_create(profile.player.id, default_current_mana=stats.mana_max)
            mana_repo.update_current_mana(profile.player.id, stats.mana_max)
        await interaction.followup.send(
            f"✅ {target.mention} restauré à pleins PV (**{stats.max_hp}**) "
            f"et plein mana (**{stats.mana_max}**).",
            ephemeral=True,
        )

    @admin.command(
        name="set_rank",
        description="Attribue un rôle de RANG (accès zones) à un joueur — retire les autres rangs",
    )
    @app_commands.describe(
        target="Joueur ciblé",
        rank="Rang à attribuer (F, E, D, C, B, A, S, SS, SSS)",
    )
    @app_commands.choices(
        rank=[app_commands.Choice(name=r, value=r) for r in RANK_ORDER]
    )
    @admin_only
    async def set_rank(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        rank: app_commands.Choice[str],
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not settings.rank_roles:
            await interaction.followup.send(
                "❌ Aucun rôle de rang configuré (`RANK_ROLE_IDS` vide dans `.env`).",
                ephemeral=True,
            )
            return
        ok = await set_rank_role(target, rank.value)
        if ok:
            await interaction.followup.send(
                f"✅ {target.mention} est désormais **Rang {rank.value}**.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"❌ Échec : rôle du Rang {rank.value} introuvable, ou le bot ne peut "
                "pas gérer ce rôle (permission « Gérer les rôles » + hiérarchie).",
                ephemeral=True,
            )

    @admin.command(
        name="acces",
        description="Accès aux salons (parcours d'arrivée) : aperçu de ce qui change, puis bouton pour appliquer",
    )
    @admin_only
    async def acces(self, interaction: discord.Interaction) -> None:
        """Règlement → Rang F → tutoriel → Aventurier → rangs : les
        permissions des salons suivent le parcours (cf. `app/bot/access.py`).
        Rien ne change avant le bouton « Appliquer »."""
        from app.bot import access
        from app.bot.views.access_view import AccessView, build_access_embed

        await interaction.response.defer(ephemeral=True)
        guild = self.bot.get_guild(settings.discord_guild_id) if settings.discord_guild_id else interaction.guild
        if guild is None:
            await interaction.followup.send("❌ Serveur du jeu introuvable (`DISCORD_GUILD_ID`).", ephemeral=True)
            return
        if not access.configured():
            await interaction.followup.send(
                "❌ Rôles du parcours non configurés : il faut `RANK_ROLE_IDS` et `ADVENTURER_ROLE_ID` "
                "dans `.env` (le rôle se crée avec `python -m scripts.channel_access --create-role`).",
                ephemeral=True)
            return
        plan = access.plan(guild.id, guild.channels)
        kwargs = {"view": AccessView(interaction.user.id, guild)} if plan.changes else {}
        await interaction.followup.send(embed=build_access_embed(plan), ephemeral=True, **kwargs)

    @admin.command(
        name="porte",
        description="Porte d'entrée avant le lancement : ouverte, testeurs seulement, ou fermée",
    )
    @app_commands.describe(
        etat="Nouvel état (vide : affiche l'état actuel)",
        ouverture="Ouverture annoncée aux joueurs, heure de Paris : JJ/MM/AAAA HH:MM",
    )
    @app_commands.choices(etat=[
        app_commands.Choice(name="Ouverte — tout le monde peut entrer", value="ouverte"),
        app_commands.Choice(name="Testeurs — les nouveaux ne peuvent plus entrer", value="testeurs"),
        app_commands.Choice(name="Fermée — tout le monde attend l'ouverture (rôles retirés)", value="fermee"),
    ])
    @admin_only
    async def porte(
        self,
        interaction: discord.Interaction,
        etat: app_commands.Choice[str] | None = None,
        ouverture: str | None = None,
    ) -> None:
        """Pas d'avant-première avant une saison (cf. `app/bot/entry_gate.py`).
        Le lancement de la saison rouvre la porte tout seul."""
        from datetime import datetime

        from app.bot import entry_gate
        from app.domain.services.pacing_service import PARIS

        await interaction.response.defer(ephemeral=True)
        gate = entry_gate.current()
        opens_at = gate.opens_at
        if ouverture:
            try:
                opens_at = datetime.strptime(ouverture.strip(), "%d/%m/%Y %H:%M").replace(tzinfo=PARIS)
            except ValueError:
                await interaction.followup.send(
                    "❌ Date d'ouverture illisible : écris-la `JJ/MM/AAAA HH:MM` (ex. `01/12/2026 20:00`).",
                    ephemeral=True)
                return
        if etat is None and not ouverture:
            await interaction.followup.send(
                f"Porte : {entry_gate.MODE_LABELS[gate.mode]}.\nCe que voit un joueur refusé :\n> "
                + entry_gate.waiting_text(gate), ephemeral=True)
            return
        guild = self.bot.get_guild(settings.discord_guild_id) if settings.discord_guild_id else interaction.guild
        report = await entry_gate.set_mode(guild, etat.value if etat else gate.mode, opens_at)
        await interaction.followup.send(
            f"✅ {report}\nCe que voit un joueur refusé :\n> {entry_gate.waiting_text()}", ephemeral=True)

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

    @admin.command(
        name="defi_cloture",
        description="Clôture TOUT DE SUITE la semaine des défis (or du podium, titres, annonce)",
    )
    @admin_only
    async def defi_cloture(self, interaction: discord.Interaction) -> None:
        """Pour tester sans attendre dimanche 20 h. La semaine clôturée ne se
        rejoue pas (idempotent) : les essais suivants de la même semaine ne
        seront plus récompensés."""
        import asyncio
        from datetime import UTC, datetime

        from app.application.use_cases import role_trials
        from app.bot.embeds.role_trial_embeds import build_results_embed
        from app.domain.services import role_trial_service as rts

        await interaction.response.defer(ephemeral=True)
        week = rts.week_start(rts.trial_day(datetime.now(UTC)))

        def _settle():
            with get_db_session() as session:
                return role_trials.settle_week(session, week)

        results = await asyncio.to_thread(_settle)
        if results is None:
            await interaction.followup.send("ℹ️ Cette semaine est déjà clôturée.", ephemeral=True)
            return
        cog = self.bot.get_cog("RoleTrialCog")
        channel = await cog._channel() if cog is not None else None
        if channel is not None and any(results.values()):
            await channel.send(embed=build_results_embed(week, results))
        await interaction.followup.send(
            "✅ Semaine des défis clôturée" + ("" if any(results.values())
                                              else " (personne n'avait joué)") + ".",
            ephemeral=True,
        )

    @admin.command(
        name="start_encounter",
        description="Lance tout de suite les combats en attente",
    )
    @admin_only
    async def start_encounter(self, interaction: discord.Interaction) -> None:
        encounter_cog = self.bot.get_cog("EncounterCog")
        if encounter_cog is None:
            await interaction.response.send_message(
                "❌ Le cog d'encounter n'est pas chargé.", ephemeral=True
            )
            return
        success, message = encounter_cog.request_early_resolve()
        await interaction.response.send_message(
            f"{'✅' if success else '⚠️'} {message}", ephemeral=True
        )

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
        name="lancer_saison",
        description="Lance officiellement une saison : TOUT le monde repart de zéro (aperçu puis confirmation)",
    )
    @app_commands.describe(
        numero="Numéro de la saison qui commence",
        annonce="Annonce dans le salon général (avec @everyone par défaut)",
    )
    @app_commands.choices(annonce=[
        app_commands.Choice(name="Annonce avec @everyone", value="everyone"),
        app_commands.Choice(name="Annonce avec @here", value="here"),
        app_commands.Choice(name="Annonce sans mention", value="none"),
        app_commands.Choice(name="Pas d'annonce", value="off"),
    ])
    @admin_only
    async def lancer_saison(
        self,
        interaction: discord.Interaction,
        numero: app_commands.Range[int, 1, 99] = 1,
        annonce: app_commands.Choice[str] | None = None,
    ) -> None:
        """Rien n'est effacé ici : l'aperçu propose un bouton, puis il faut
        taper « SAISON N » (cf. `season_launch`)."""
        import asyncio

        from app.bot import season_launch
        from app.bot.views.season_launch_view import SeasonLaunchView, build_preview_embed

        await interaction.response.defer(ephemeral=True)
        ping = annonce.value if annonce else "everyone"
        preview = await asyncio.to_thread(season_launch.preview, self.bot)
        await interaction.followup.send(
            embed=build_preview_embed(preview, numero, ping),
            view=SeasonLaunchView(interaction, numero, ping),
            ephemeral=True,
        )

    @admin.command(
        name="spawn_encounter",
        description="Force le spawn immédiat d'un encounter (mob, élément, meute optionnels)",
    )
    @app_commands.describe(
        mob_code="Code du mob à faire spawn (optionnel : random sinon)",
        element="Élément forcé (optionnel : aléatoire pondéré sinon)",
        meute="Fait apparaître une meute de 2 ou 3 monstres (le mob choisi en tête)",
    )
    @app_commands.choices(
        element=[
            app_commands.Choice(name=ELEMENT_LABELS[e.value], value=e.value)
            for e in ALL_ELEMENTS
        ],
        meute=[app_commands.Choice(name=f"Meute de {n}", value=n) for n in (2, 3)],
    )
    @admin_only
    async def spawn_encounter(
        self,
        interaction: discord.Interaction,
        mob_code: str | None = None,
        element: app_commands.Choice[str] | None = None,
        meute: app_commands.Choice[int] | None = None,
    ) -> None:
        encounter_cog = self.bot.get_cog("EncounterCog")
        if encounter_cog is None:
            await interaction.response.send_message(
                "❌ Le cog d'encounter n'est pas chargé.",
                ephemeral=True,
            )
            return

        # channel_id : le salon d'où vient la commande → le mob spawn ICI si
        # c'est une zone spawnable (sinon fallback famille / zone de base).
        success, message = encounter_cog.trigger_immediate_spawn(
            mob_code=mob_code,
            element=element.value if element else None,
            channel_id=interaction.channel_id,
            pack=meute.value if meute else 0,
        )
        await interaction.response.send_message(
            f"{'✅' if success else '⚠️'} {message}",
            ephemeral=True,
        )

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
