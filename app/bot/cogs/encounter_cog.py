import asyncio
import logging
import random
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
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.encounters.farm_zone_loader import (
    default_channel_id,
    get_background_for_family,
    get_spawn_channel_for_family,
    list_zone_channels,
)
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

_logger = logging.getLogger(__name__)


class EncounterCog(commands.Cog):
    """Boucle de spawn des encounters, MULTI-ZONE simultané.

    Chaque zone de farm (chaque salon de spawn distinct, cf. `farm_zones.json`)
    tourne son PROPRE encounter en parallèle via une tâche async dédiée
    (`_zone_loop`). L'état est indexé par `channel_id` : la clairière (slime +
    gobelin) et le cimetière (mort-vivant) peuvent avoir un combat actif chacun
    en même temps. Un seul encounter actif PAR zone à la fois.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.encounter_service = EncounterService()
        self.power_score_service = PowerScoreService()
        self.generated_dir = GENERATED_ENCOUNTERS_DIR
        self.generated_dir.mkdir(exist_ok=True)

        # --- État PAR ZONE (clé = channel_id du salon de spawn) ---
        # Encounter actif de la zone (absent = zone libre).
        self.active_encounters: dict[int, ActiveEncounter] = {}
        # Décor résolu au spawn, gardé pour tous les rendus de l'encounter.
        self._zone_bg: dict[int, str] = {}
        # Prochaine date de spawn autorisée pour la zone.
        self._zone_next_spawn: dict[int, datetime] = {}
        # Mob forcé au prochain spawn de la zone (/admin spawn_encounter).
        self._zone_forced_mob: dict[int, str] = {}
        # Élément forcé au prochain spawn de la zone (/admin spawn_encounter).
        self._zone_forced_element: dict[int, str] = {}
        # Event de résolution anticipée (/admin start_encounter) par zone.
        self._zone_early_resolve: dict[int, asyncio.Event] = {}
        # Tâche asyncio de chaque zone.
        self._zone_tasks: dict[int, asyncio.Task] = {}

        self._startup_task: asyncio.Task | None = None
        self.generated_cleanup_loop.start()
        self._startup_task = asyncio.ensure_future(self._start_zone_loops())

    def cog_unload(self):
        self.generated_cleanup_loop.cancel()
        if self._startup_task is not None:
            self._startup_task.cancel()
        for task in self._zone_tasks.values():
            task.cancel()

    async def _start_zone_loops(self) -> None:
        """Démarre une boucle async indépendante par zone de farm, une fois le
        bot prêt. Chaque zone spawn/combat en parallèle des autres."""
        await self.bot.wait_until_ready()
        now = datetime.now(UTC)
        for channel_id in list_zone_channels():
            self._zone_next_spawn.setdefault(channel_id, now + timedelta(minutes=1))
            self._zone_tasks[channel_id] = asyncio.ensure_future(
                self._zone_loop(channel_id)
            )
        _logger.info("Zones d'encounter démarrées : %s", list(self._zone_tasks.keys()))

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

    # ---------------------- Participants (zone-aware) ----------------------

    async def register_participant(
        self,
        channel_id: int,
        user_id: int,
        display_name: str,
        avatar_url: str,
    ) -> tuple[bool, str]:
        success, message = self.encounter_service.register_participant(
            encounter=self.active_encounters.get(channel_id),
            user_id=user_id,
            display_name=display_name,
            avatar_url=avatar_url,
        )
        return success, message

    async def unregister_participant(
        self,
        channel_id: int,
        user_id: int,
    ) -> tuple[bool, str]:
        success, message = self.encounter_service.unregister_participant(
            encounter=self.active_encounters.get(channel_id),
            user_id=user_id,
        )
        return success, message

    # ---------------------- Commandes admin (zone-aware) ----------------------

    def _pick_mob_for_zone(self, channel_id: int, forced_code: str | None):
        """Choisit un mob pour la zone : soit le mob forcé, soit un tirage
        pondéré parmi les mobs dont la FAMILLE spawn dans ce salon."""
        with get_db_session() as session:
            repo = MobRepository(session)
            if forced_code is not None:
                return repo.get_by_code(forced_code)
            mobs = repo.list_all()
        eligible = [
            m
            for m in mobs
            if get_spawn_channel_for_family(m.family) == channel_id and m.spawn_weight > 0
        ]
        if not eligible:
            return None
        return random.choices(
            eligible, weights=[m.spawn_weight for m in eligible], k=1
        )[0]

    def trigger_immediate_spawn(
        self,
        mob_code: str | None = None,
        element: str | None = None,
        channel_id: int | None = None,
    ) -> tuple[bool, str]:
        """Force le spawn immédiat d'un encounter.

        Zone ciblée, par priorité :
          1. `channel_id` (le salon d'où vient la commande) SI c'est un salon de
             zone spawnable → le mob apparaît là où l'admin a tapé la commande ;
          2. sinon la FAMILLE du mob (si `mob_code` fourni) ;
          3. sinon la zone de base.
        `element` (optionnel) force l'élément du spawn ; sinon aléatoire pondéré.
        Un combat déjà actif dans la zone est annulé pour faire place.
        """
        mob = None
        if mob_code is not None:
            with get_db_session() as session:
                mob = MobRepository(session).get_by_code(mob_code)
            if mob is None:
                return False, f"Mob `{mob_code}` introuvable."

        zone_channels = set(list_zone_channels())
        if channel_id is not None and channel_id in zone_channels:
            target = channel_id
        elif mob is not None:
            target = get_spawn_channel_for_family(mob.family)
        else:
            target = default_channel_id()

        cancelled_existing = False
        existing = self.active_encounters.pop(target, None)
        if existing is not None:
            # Réveille le combat en cours : sa boucle verra qu'il n'est plus
            # l'encounter courant de la zone et s'auto-annulera.
            event = self._zone_early_resolve.get(target)
            if event is not None:
                event.set()
            cancelled_existing = True

        if mob_code is not None:
            self._zone_forced_mob[target] = mob_code
        else:
            self._zone_forced_mob.pop(target, None)
        if element:
            self._zone_forced_element[target] = element
        else:
            self._zone_forced_element.pop(target, None)
        self._zone_next_spawn[target] = datetime.now(UTC) - timedelta(seconds=1)

        parts = []
        if mob_code:
            parts.append(mob_code)
        if element:
            parts.append(f"élément {element}")
        suffix = f" ({', '.join(parts)})" if parts else ""
        prefix = "Combat précédent annulé. " if cancelled_existing else ""
        return True, (
            f"{prefix}Spawn forcé{suffix} : un monstre apparaît dans quelques "
            f"secondes (salon `{target}`)."
        )

    def request_early_resolve(self) -> tuple[bool, str]:
        """Résout immédiatement TOUS les encounters actifs (toutes zones) sans
        attendre les 5 min. Utilisé par /admin start_encounter."""
        if not self.active_encounters:
            return False, "Aucun combat actif à résoudre."
        names: list[str] = []
        for channel_id, encounter in list(self.active_encounters.items()):
            event = self._zone_early_resolve.get(channel_id)
            if event is not None:
                event.set()
                names.append(encounter.mob_state.name)
        if not names:
            return False, "Combats actifs mais boucles non prêtes."
        joined = ", ".join(f"**{n}**" for n in names)
        return True, f"Combat(s) lancé(s) immédiatement : {joined}."

    def force_end_encounter(self) -> tuple[bool, str]:
        """Annule TOUS les encounters actifs (toutes zones). Utilisé par
        /admin end_encounter. N'envoie pas de message dans les canaux."""
        if not self.active_encounters:
            return False, "Aucun combat actif à arrêter."
        names: list[str] = []
        respawn_at = datetime.now(UTC) + timedelta(minutes=1)
        for channel_id in list(self.active_encounters.keys()):
            encounter = self.active_encounters.pop(channel_id)
            names.append(encounter.mob_state.name)
            self._zone_forced_mob.pop(channel_id, None)
            self._zone_next_spawn[channel_id] = respawn_at
            event = self._zone_early_resolve.get(channel_id)
            if event is not None:
                event.set()
        joined = ", ".join(f"**{n}**" for n in names)
        return True, f"Encounter(s) actif(s) annulé(s) : {joined}."

    # ---------------------- Boucle par zone ----------------------

    async def _zone_loop(self, channel_id: int) -> None:
        """Boucle indépendante d'une zone : attend le timer de spawn, fait
        apparaître un mob de la zone, joue le combat complet, puis reprogramme.
        Toute exception est absorbée pour ne jamais tuer la boucle de la zone."""
        while True:
            try:
                await asyncio.sleep(10)
                await self._zone_tick(channel_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                _logger.exception("zone_loop %s tick failed — retenté", channel_id)
                if channel_id not in self.active_encounters:
                    self._zone_next_spawn[channel_id] = datetime.now(UTC) + timedelta(
                        seconds=30
                    )

    async def _zone_tick(self, channel_id: int) -> None:
        if channel_id in self.active_encounters:
            return

        now = datetime.now(UTC)
        next_at = self._zone_next_spawn.get(channel_id)
        if next_at is not None and now < next_at:
            return

        forced_code = self._zone_forced_mob.pop(channel_id, None)
        forced_element = self._zone_forced_element.pop(channel_id, None)
        mob = self._pick_mob_for_zone(channel_id, forced_code)
        if mob is None:
            self._zone_next_spawn[channel_id] = now + timedelta(minutes=1)
            return

        await self._run_encounter(channel_id, mob, forced_element=forced_element)

    def _reschedule(self, channel_id: int, minutes: int = 1) -> None:
        """Libère la zone et pose le prochain spawn."""
        self.active_encounters.pop(channel_id, None)
        self._zone_next_spawn[channel_id] = datetime.now(UTC) + timedelta(minutes=minutes)

    async def _run_encounter(self, channel_id: int, mob, forced_element: str | None = None) -> None:
        """Cycle de vie complet d'un encounter dans une zone : spawn → fenêtre
        de recrutement (5 min ou résolution anticipée) → combat animé → récap.
        Opère sur un encounter LOCAL indexé par `channel_id` ; ne touche jamais
        l'état des autres zones."""
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            self._zone_next_spawn[channel_id] = datetime.now(UTC) + timedelta(minutes=1)
            return

        # Décor d'environnement de la zone (selon la famille du mob).
        background_path = LANDSCAPES_ASSETS_DIR / get_background_for_family(mob.family)
        self._zone_bg[channel_id] = str(background_path)

        # Élément spawné : priorité à l'élément FORCÉ (/admin spawn_encounter) ;
        # sinon l'élément stocké du mob (rare, forcé au contenu) ; sinon un tirage
        # aléatoire pondéré (chaque monstre peut spawner sous n'importe quel élément).
        from app.infrastructure.elements.element_spawn_weight_loader import (
            pick_random_element,
        )
        spawn_element = (
            (forced_element or "").strip()
            or (getattr(mob, "element", "") or "").strip()
            or pick_random_element()
        )

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
            element=spawn_element,
        )

        encounter = ActiveEncounter.create(
            mob_state=mob_state,
            victory_image_name="others/victory.png",
            defeat_image_name="others/defeat.png",
            flee_image_name="others/flee.jpg",
            duration_minutes=5,
        )

        view = EncounterView(self, channel_id, timeout=300)

        spawn_filename = f"encounter_spawn_{encounter.mob_state.code}.png"
        spawn_output_full = self.generated_dir / spawn_filename
        spawn_output_relative = f"generated_encounters/{spawn_filename}"

        mob_score = self.power_score_service.calculate_and_format_from_mob(mob)

        spawn_mob_payload = {
            "code": encounter.mob_state.code,
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
            "element": encounter.mob_state.element,
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
        self.active_encounters[channel_id] = encounter

        # Fenêtre de recrutement / combat : 5 min OU jusqu'à signal
        # d'/admin start_encounter (early resolve).
        event = asyncio.Event()
        self._zone_early_resolve[channel_id] = event
        try:
            await asyncio.wait_for(event.wait(), timeout=300)
        except asyncio.TimeoutError:
            pass
        finally:
            self._zone_early_resolve.pop(channel_id, None)

        for child in view.children:
            child.disabled = True

        # L'encounter a-t-il été annulé/remplacé pendant la fenêtre (admin
        # end/spawn) ? Si oui, on abandonne sans reprogrammer (celui qui a
        # annulé a déjà posé le prochain spawn).
        if self.active_encounters.get(channel_id) is not encounter:
            return

        if not encounter.participants:
            flee_summary = BattleSummary(
                outcome="flee",
                mob_name=encounter.mob_state.name,
                mob_image_name=encounter.mob_state.image_name,
                mob_family="",
                turns=0,
            )
            flee_embed = build_rewards_page_embed(flee_summary)
            await message.edit(embed=flee_embed, attachments=[], view=None)
            self._reschedule(channel_id)
            return

        result = self.encounter_service.resolve_active_encounter(encounter)
        if result is None:
            self._reschedule(channel_id)
            return

        self.encounter_service.persist_final_players_hp(result)
        battle_summary = self.encounter_service.apply_rewards(encounter, result)

        current_filename = f"encounter_{encounter.message_id}_current.png"
        current_output_full = self.generated_dir / current_filename
        current_output_relative = f"generated_encounters/{current_filename}"

        # Message dédié au journal de combat tour par tour. Indépendant du
        # message de spawn (qui garde l'image et finira sur le BattleSummary).
        mob_name = encounter.mob_state.name
        mob_max_hp = encounter.mob_state.max_hp
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
            # L'élément est fixe pour tout l'encounter → on l'injecte depuis la
            # source unique (mob_state), la teinte/badge persiste pendant le combat.
            mob_payload["code"] = encounter.mob_state.code
            mob_payload["element"] = encounter.mob_state.element
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

            # Met à jour le journal de combat séparé : ligne du tour + PV.
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
                    # (rate limit, message supprimé).
                    combat_log_message = None

            await asyncio.sleep(1.5)

        if battle_summary is None:
            self._reschedule(channel_id)
            return

        summary_view = BattleSummaryView(battle_summary, timeout=600.0)
        await message.edit(
            embed=summary_view.current_embed,
            attachments=[],
            view=summary_view,
        )

        # Édition finale du journal de combat : lien vers le message de spawn.
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

        self._reschedule(channel_id)

    async def refresh_encounter_scene(self, channel_id: int) -> None:
        encounter = self.active_encounters.get(channel_id)
        if encounter is None or encounter.message_id is None:
            return

        channel = self.bot.get_channel(channel_id)
        if channel is None:
            return

        try:
            message = await channel.fetch_message(encounter.message_id)
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
            for participant in encounter.participants.values()
        ]

        filename = f"encounter_{encounter.message_id}_current.png"
        output_full = self.generated_dir / filename
        output_relative = f"generated_encounters/{filename}"
        background_path = self._zone_bg.get(
            channel_id, str(LANDSCAPES_ASSETS_DIR / "clairiere_sinistre.png")
        )

        mob_score = self.power_score_service.format_score(
            self.power_score_service.calculate_from_stats(
                Stats(
                    max_hp=encounter.mob_state.max_hp,
                    attack=encounter.mob_state.attack,
                    defense=encounter.mob_state.defense,
                    crit_chance=encounter.mob_state.crit_chance,
                    crit_damage=encounter.mob_state.crit_damage,
                    dodge=encounter.mob_state.dodge,
                    hp_regeneration=encounter.mob_state.hp_regeneration,
                    speed=encounter.mob_state.speed,
                )
            )
        )

        mob_payload = {
            "code": encounter.mob_state.code,
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
            "element": encounter.mob_state.element,
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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EncounterCog(bot))
