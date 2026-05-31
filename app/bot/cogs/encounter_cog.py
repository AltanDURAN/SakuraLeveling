import asyncio
from datetime import datetime, timedelta, UTC

import discord
from discord.ext import commands, tasks

from app.application.services.encounter_service import EncounterService
from app.bot.embeds.battle_summary_embeds import build_rewards_page_embed
from app.bot.embeds.encounter_combat_log_embeds import (
    build_combat_log_embed,
    format_turn_action,
)
from app.bot.embeds.encounter_embeds import build_encounter_embed
from app.bot.rendering.fight_scene import compose_players_banner
from app.bot.runtime.active_encounter import ActiveEncounter
from app.bot.runtime.encounter_mob_state import EncounterMobState
from app.bot.views.battle_summary_view import BattleSummaryView
from app.bot.views.encounter_view import EncounterView
from app.domain.services.power_score_service import PowerScoreService
from app.domain.value_objects.battle_summary import BattleSummary
from app.domain.value_objects.stats import Stats
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.session import get_db_session
from app.shared.generated_cleanup import purge_old_files
from app.shared.paths import (
    GENERATED_ENCOUNTERS_DIR,
    GENERATED_EQUIPMENT_DIR,
    GENERATED_LISTS_DIR,
    GENERATED_PROFILES_DIR,
    LANDSCAPES_ASSETS_DIR,
)


# Durée de vie des PNG générés (encounters / profiles / équipement).
# Les images servent une seule fois (attachment Discord), Discord en garde
# sa propre copie sur son CDN. Au-delà de cet âge, on purge.
_GENERATED_FILES_TTL_SECONDS = 7 * 24 * 3600


class EncounterCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_encounter: ActiveEncounter | None = None
        self.encounter_service = EncounterService()
        self.next_spawn_at: datetime | None = None
        self._forced_mob_code: str | None = None
        # Event signalé par /admin start_encounter pour résoudre tout de suite
        # le combat actif sans attendre les 5 min. Re-créé à chaque spawn.
        self._early_resolve_event: asyncio.Event | None = None
        self.encounter_loop.start()
        self.generated_cleanup_loop.start()
        self.generated_dir = GENERATED_ENCOUNTERS_DIR
        self.generated_dir.mkdir(exist_ok=True)
        self.power_score_service = PowerScoreService()

    def cog_unload(self):
        self.encounter_loop.cancel()
        self.generated_cleanup_loop.cancel()

    @tasks.loop(hours=12)
    async def generated_cleanup_loop(self) -> None:
        """Purge périodique des PNG générés à la volée."""
        for directory in (
            GENERATED_ENCOUNTERS_DIR,
            GENERATED_PROFILES_DIR,
            GENERATED_EQUIPMENT_DIR,
            GENERATED_LISTS_DIR,
        ):
            purge_old_files(directory, _GENERATED_FILES_TTL_SECONDS)

    @generated_cleanup_loop.before_loop
    async def before_generated_cleanup_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def register_participant(
        self,
        user_id: int,
        display_name: str,
        avatar_url: str,
    ) -> tuple[bool, str]:
        success, message = self.encounter_service.register_participant(
            encounter=self.active_encounter,
            user_id=user_id,
            display_name=display_name,
            avatar_url=avatar_url,
        )
        return success, message

    async def unregister_participant(
        self,
        user_id: int,
    ) -> tuple[bool, str]:
        success, message = self.encounter_service.unregister_participant(
            encounter=self.active_encounter,
            user_id=user_id,
        )
        return success, message

    def trigger_immediate_spawn(self, mob_code: str | None = None) -> tuple[bool, str]:
        """Force la prochaine itération du loop à spawn un encounter.

        Si un combat est déjà actif, il est annulé pour faire place au nouveau
        (le timer de respawn naturel est correctement réinitialisé via
        `_early_resolve_event` qui débloque la boucle). Si `mob_code` est
        fourni, le prochain spawn ciblera ce mob précis (sinon random).
        """
        if mob_code is not None:
            with get_db_session() as session:
                mob = MobRepository(session).get_by_code(mob_code)
            if mob is None:
                return False, f"Mob `{mob_code}` introuvable."

        cancelled_existing = False
        if self.active_encounter is not None:
            # On signale au loop de finir tout de suite l'encounter actuel
            # (équivalent à un /admin end_encounter implicite). Le loop posera
            # automatiquement next_spawn_at = +1min puis on l'écrase juste
            # après pour spawner immédiatement.
            self.active_encounter = None
            if self._early_resolve_event is not None:
                self._early_resolve_event.set()
            cancelled_existing = True

        self._forced_mob_code = mob_code
        self.next_spawn_at = datetime.now(UTC) - timedelta(seconds=1)
        suffix = f" ({mob_code})" if mob_code else ""
        prefix = "Combat précédent annulé. " if cancelled_existing else ""
        return True, (
            f"{prefix}Spawn forcé{suffix} : un monstre apparaît dans quelques secondes."
        )

    def request_early_resolve(self) -> tuple[bool, str]:
        """Demande au loop de résoudre tout de suite l'encounter actif sans
        attendre les 5 min. Utilisé par /admin start_encounter. Pas de
        décalage temporel : la boucle continue ensuite normalement (next_spawn_at
        sera posé par la résolution comme d'habitude)."""
        if self.active_encounter is None:
            return False, "Aucun combat actif à résoudre."
        if self._early_resolve_event is None:
            return False, "Combat actif mais loop non prêt."
        self._early_resolve_event.set()
        return True, f"Combat lancé immédiatement contre **{self.active_encounter.mob_state.name}**."

    def force_end_encounter(self) -> tuple[bool, str]:
        """Annule un encounter actif (utilisé par /admin end_encounter).

        N'envoie pas de message dans le canal — l'admin se chargera de
        communiquer si besoin. Le timer de respawn est reset à +1min pour
        éviter qu'un autre n'apparaisse instantanément.
        """
        if self.active_encounter is None:
            return False, "Aucun combat actif à arrêter."
        mob_name = self.active_encounter.mob_state.name
        self.active_encounter = None
        self._forced_mob_code = None
        self.next_spawn_at = datetime.now(UTC) + timedelta(minutes=1)
        return True, f"Encounter actif (**{mob_name}**) annulé."

    @tasks.loop(seconds=10)
    async def encounter_loop(self):
        try:
            await self._encounter_loop_body()
        except Exception:
            # Filet de sécurité : ne laisse JAMAIS l'exception remonter,
            # sinon discord.ext.tasks arrête la boucle (= plus aucun
            # spawn naturel jusqu'au prochain restart du bot). On log et
            # on retente au prochain tick (10 s). Les erreurs transitoires
            # (503 Discord, timeout réseau) sont absorbées.
            import logging
            logging.getLogger(__name__).exception(
                "encounter_loop tick failed — sera retenté"
            )
            # Si la boucle a planté avant de poser next_spawn_at, on évite
            # de retry instantanément en posant un cooldown court.
            if self.active_encounter is None:
                self.next_spawn_at = datetime.now(UTC) + timedelta(seconds=30)

    @encounter_loop.error
    async def _encounter_loop_error(self, error: Exception) -> None:
        """Filet de dernière chance : si malgré tout la boucle s'arrête
        (le décorateur @tasks.loop la stoppe sur exception non rattrapée),
        on relogue et on la relance."""
        import logging
        logging.getLogger(__name__).exception(
            "encounter_loop crashed unexpectedly, restarting: %s", error,
        )
        if not self.encounter_loop.is_running():
            self.encounter_loop.restart()

    async def _encounter_loop_body(self):
        channel = self.bot.get_channel(settings.encounter_channel_id)
        if channel is None:
            return

        if self.active_encounter is not None:
            return

        now = datetime.now(UTC)
        if self.next_spawn_at is not None and now < self.next_spawn_at:
            return

        forced_code = self._forced_mob_code
        self._forced_mob_code = None  # consommé en une fois
        with get_db_session() as session:
            mob_repository = MobRepository(session)
            mob = (
                mob_repository.get_by_code(forced_code)
                if forced_code is not None
                else mob_repository.get_random()
            )

        if mob is None:
            return

        mob_state = EncounterMobState(
            code=mob.code,
            name=mob.name,
            image_name=mob.image_name,
            current_hp=mob.current_hp,
            max_hp=mob.max_hp,
            attack=mob.attack,
            defense=mob.defense,
            speed=mob.speed,
            crit_chance=mob.crit_chance,
            crit_damage=mob.crit_damage,
            dodge=mob.dodge,
            hp_regeneration=mob.hp_regeneration,
        )

        encounter = ActiveEncounter.create(
            mob_state=mob_state,
            victory_image_name="others/victory.png",
            defeat_image_name="others/defeat.png",
            flee_image_name="others/flee.jpg",
            duration_minutes=5,
        )

        view = EncounterView(self, timeout=300)

        spawn_filename = f"encounter_spawn_{encounter.mob_state.code}.png"
        spawn_output_full = self.generated_dir / spawn_filename
        spawn_output_relative = f"generated_encounters/{spawn_filename}"
        background_path = LANDSCAPES_ASSETS_DIR / "clairiere_sinistre.png"

        mob_score = self.power_score_service.calculate_and_format_from_mob(mob)

        spawn_mob_payload = {
            "name": encounter.mob_state.name,
            "image_name": encounter.mob_state.image_name,
            "current_hp": encounter.mob_state.current_hp,
            "max_hp": encounter.mob_state.max_hp,
            "attack": encounter.mob_state.attack,
            "defense": encounter.mob_state.defense,
            "speed": encounter.mob_state.speed,
            "crit_chance": encounter.mob_state.crit_chance,
            "crit_damage": encounter.mob_state.crit_damage,
            "dodge": encounter.mob_state.dodge,
            "hp_regeneration": encounter.mob_state.hp_regeneration,
            "power_score": mob_score,
        }

        # Rendu Pillow + téléchargement d'avatars : sync et CPU/IO-bound.
        # Sans to_thread, ça bloque tout l'event loop pendant le rendu (~1-2s
        # + jusqu'à 15s par avatar lent) → heartbeat Discord et autres
        # interactions gelés. Cf. audit Phase 1 finding B5.
        await asyncio.to_thread(
            compose_players_banner,
            players=[],
            mob=spawn_mob_payload,
            output_path=str(spawn_output_full),
            background_path=str(background_path),
            players_power_score="",
        )

        embed, file = build_encounter_embed(
            image_name=spawn_output_relative,
        )

        message = await channel.send(embed=embed, view=view, file=file)
        encounter.message_id = message.id
        self.active_encounter = encounter

        # Fenêtre de recrutement / combat : 5 min OU jusqu'à signal
        # d'/admin start_encounter (early resolve). Pas de décalage timer :
        # la suite de la boucle pose next_spawn_at comme d'habitude.
        self._early_resolve_event = asyncio.Event()
        try:
            await asyncio.wait_for(self._early_resolve_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            pass
        finally:
            self._early_resolve_event = None

        for child in view.children:
            child.disabled = True

        if self.active_encounter is None:
            self.next_spawn_at = datetime.now(UTC) + timedelta(minutes=1)
            return

        if not self.active_encounter.participants:
            flee_summary = BattleSummary(
                outcome="flee",
                mob_name=self.active_encounter.mob_state.name,
                mob_image_name=self.active_encounter.mob_state.image_name,
                mob_family="",
                turns=0,
            )
            flee_embed = build_rewards_page_embed(flee_summary)
            await message.edit(embed=flee_embed, attachments=[], view=None)
            self.active_encounter = None
            self.next_spawn_at = datetime.now(UTC) + timedelta(minutes=1)
            return

        result = self.resolve_active_encounter()
        if result is None:
            self.active_encounter = None
            self.next_spawn_at = datetime.now(UTC) + timedelta(minutes=1)
            return

        self.persist_final_players_hp(result)
        battle_summary = self.encounter_service.apply_rewards(self.active_encounter, result)

        background_path = LANDSCAPES_ASSETS_DIR / "clairiere_sinistre.png"
        current_filename = f"encounter_{self.active_encounter.message_id}_current.png"
        current_output_full = self.generated_dir / current_filename
        current_output_relative = f"generated_encounters/{current_filename}"

        # Message dédié au journal de combat tour par tour. Indépendant du
        # message de spawn (qui garde l'image et finira sur le BattleSummary).
        # On y accumule les actions et on poste un lien retour à la fin.
        mob_name = self.active_encounter.mob_state.name
        mob_max_hp = self.active_encounter.mob_state.max_hp
        action_lines: list[str] = []
        initial_log_embed = build_combat_log_embed(
            mob_name=mob_name,
            actions=action_lines,
            mob_current_hp=mob_max_hp,
            mob_max_hp=mob_max_hp,
            players_state=None,
            finished=False,
        )
        try:
            combat_log_message = await channel.send(embed=initial_log_embed)
        except discord.HTTPException:
            combat_log_message = None

        for turn_log in result.turn_logs:
            players_stats_for_score: list[Stats] = []

            for player_state in turn_log.players_state:
                players_stats_for_score.append(
                    Stats(
                        max_hp=player_state["max_hp"],
                        attack=player_state.get("attack", 1),
                        defense=player_state.get("defense", 0),
                        crit_chance=player_state.get("crit_chance", 0),
                        crit_damage=player_state.get("crit_damage", 100),
                        dodge=player_state.get("dodge", 0),
                        hp_regeneration=player_state.get("hp_regeneration", 0),
                        speed=player_state.get("speed", 1),
                    )
                )

            players_power_score = self.power_score_service.calculate_and_format_party_score(
                players_stats_for_score
            )

            mob_payload = dict(turn_log.mob_state)
            mob_payload["power_score"] = self.power_score_service.format_score(
                self.power_score_service.calculate_from_stats(
                    Stats(
                        max_hp=mob_payload["max_hp"],
                        attack=mob_payload["attack"],
                        defense=mob_payload["defense"],
                        crit_chance=mob_payload.get("crit_chance", 0),
                        crit_damage=mob_payload.get("crit_damage", 100),
                        dodge=mob_payload.get("dodge", 0),
                        hp_regeneration=mob_payload.get("hp_regeneration", 0),
                        speed=mob_payload.get("speed", 1),
                    )
                )
            )

            await asyncio.to_thread(
                compose_players_banner,
                players=turn_log.players_state,
                mob=mob_payload,
                output_path=str(current_output_full),
                background_path=str(background_path),
                players_power_score=players_power_score,
            )

            turn_embed, file = build_encounter_embed(
                image_name=current_output_relative,
            )

            await message.edit(embed=turn_embed, attachments=[file], view=view)

            # Met à jour le journal de combat séparé : on ajoute la ligne
            # narrant ce tour et on rafraîchit les PV affichés.
            if combat_log_message is not None:
                action_lines.append(format_turn_action(turn_log))
                log_embed = build_combat_log_embed(
                    mob_name=mob_name,
                    actions=action_lines,
                    mob_current_hp=int(turn_log.mob_state.get("current_hp", 0) or 0),
                    mob_max_hp=mob_max_hp,
                    players_state=turn_log.players_state,
                    finished=False,
                )
                try:
                    await combat_log_message.edit(embed=log_embed)
                except discord.HTTPException:
                    # On garde la suite du combat même si une édition échoue
                    # (rate limit, message supprimé). Le récap final reste
                    # disponible sur le message de spawn.
                    combat_log_message = None

            await asyncio.sleep(1.5)

        if battle_summary is None:
            self.active_encounter = None
            self.next_spawn_at = datetime.now(UTC) + timedelta(minutes=1)
            return

        summary_view = BattleSummaryView(battle_summary, timeout=600.0)
        await message.edit(
            embed=summary_view.current_embed,
            attachments=[],
            view=summary_view,
        )

        # Édition finale du journal de combat : on ajoute le lien vers
        # le message de spawn, où le BattleSummary affiche les récompenses.
        if combat_log_message is not None:
            redirect_url = getattr(message, "jump_url", None)
            final_log_embed = build_combat_log_embed(
                mob_name=mob_name,
                actions=action_lines,
                mob_current_hp=0
                if battle_summary.outcome == "victory"
                else max(0, result.mob_remaining_hp),
                mob_max_hp=mob_max_hp,
                players_state=None,
                finished=True,
                redirect_url=redirect_url,
            )
            try:
                await combat_log_message.edit(embed=final_log_embed)
            except discord.HTTPException:
                pass

        self.active_encounter = None
        self.next_spawn_at = datetime.now(UTC) + timedelta(minutes=1)

    @encounter_loop.before_loop
    async def before_encounter_loop(self):
        await self.bot.wait_until_ready()
        self.next_spawn_at = datetime.now(UTC) + timedelta(minutes=1)

    def resolve_active_encounter(self):
        return self.encounter_service.resolve_active_encounter(self.active_encounter)

    async def refresh_encounter_scene(self) -> None:
        if self.active_encounter is None or self.active_encounter.message_id is None:
            return

        channel = self.bot.get_channel(settings.encounter_channel_id)
        if channel is None:
            return

        try:
            message = await channel.fetch_message(self.active_encounter.message_id)
        except discord.NotFound:
            return

        players = [
            {
                "name": participant.display_name,
                "avatar_url": participant.avatar_url,
                "current_hp": participant.current_hp,
                "max_hp": participant.max_hp,
                "attack": participant.stats.attack,
                "defense": participant.stats.defense,
                "speed": participant.stats.speed,
                "crit_chance": participant.stats.crit_chance,
                "crit_damage": participant.stats.crit_damage,
                "dodge": participant.stats.dodge,
                "hp_regeneration": participant.stats.hp_regeneration,
            }
            for participant in self.active_encounter.participants.values()
        ]

        filename = f"encounter_{self.active_encounter.message_id}_current.png"
        output_full = self.generated_dir / filename
        output_relative = f"generated_encounters/{filename}"
        background_path = LANDSCAPES_ASSETS_DIR / "clairiere_sinistre.png"

        mob_score = self.power_score_service.format_score(
            self.power_score_service.calculate_from_stats(
                Stats(
                    max_hp=self.active_encounter.mob_state.max_hp,
                    attack=self.active_encounter.mob_state.attack,
                    defense=self.active_encounter.mob_state.defense,
                    crit_chance=self.active_encounter.mob_state.crit_chance,
                    crit_damage=self.active_encounter.mob_state.crit_damage,
                    dodge=self.active_encounter.mob_state.dodge,
                    hp_regeneration=self.active_encounter.mob_state.hp_regeneration,
                    speed=self.active_encounter.mob_state.speed,
                )
            )
        )

        mob_payload = {
            "name": self.active_encounter.mob_state.name,
            "image_name": self.active_encounter.mob_state.image_name,
            "current_hp": self.active_encounter.mob_state.current_hp,
            "max_hp": self.active_encounter.mob_state.max_hp,
            "attack": self.active_encounter.mob_state.attack,
            "defense": self.active_encounter.mob_state.defense,
            "speed": self.active_encounter.mob_state.speed,
            "crit_chance": self.active_encounter.mob_state.crit_chance,
            "crit_damage": self.active_encounter.mob_state.crit_damage,
            "dodge": self.active_encounter.mob_state.dodge,
            "hp_regeneration": self.active_encounter.mob_state.hp_regeneration,
            "power_score": mob_score,
        }

        players_stats_for_score = [
            Stats(
                max_hp=player["max_hp"],
                attack=player.get("attack", 1),
                defense=player.get("defense", 0),
                crit_chance=player.get("crit_chance", 0),
                crit_damage=player.get("crit_damage", 100),
                dodge=player.get("dodge", 0),
                hp_regeneration=player.get("hp_regeneration", 0),
                speed=player.get("speed", 1),
            )
            for player in players
        ]

        players_power_score = self.power_score_service.calculate_and_format_party_score(
            players_stats_for_score
        ) if players_stats_for_score else "0"

        await asyncio.to_thread(
            compose_players_banner,
            players=players,
            mob=mob_payload,
            output_path=str(output_full),
            background_path=str(background_path),
            players_power_score=players_power_score,
        )

        embed, file = build_encounter_embed(
            image_name=output_relative,
        )

        await message.edit(embed=embed, attachments=[file])

    def persist_final_players_hp(self, result) -> None:
        self.encounter_service.persist_final_players_hp(result)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EncounterCog(bot))