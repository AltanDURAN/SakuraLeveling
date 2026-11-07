import asyncio
import logging
import random
from datetime import datetime, timedelta, UTC

import discord
from discord.ext import commands, tasks

from app.application.services.encounter_service import EncounterService
from app.bot.embeds.battle_summary_embeds import build_rewards_page_embed
from app.bot.embeds.encounter_combat_log_embeds import (
    format_turn_action,
)
from app.bot.embeds.encounter_embeds import build_encounter_embed
from app.bot.rendering.fight_scene import compose_players_banner
from app.bot.rendering.render_queue import video_slot
from app.bot.runtime.active_encounter import ActiveEncounter
from app.bot.runtime.encounter_mob_state import EncounterMobState
from app.bot.views.battle_summary_view import BattleSummaryView
from app.bot.views.encounter_view import EncounterView
from app.domain.services import lunar_service, pack_service, pacing_service
from app.domain.services.mob_ability_service import is_group_elite
from app.domain.services.power_score_service import PowerScoreService
from app.domain.value_objects.stats import Stats
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.config.settings import settings
from app.infrastructure.pacing.pacing_loader import get_pacing
from app.infrastructure.encounters.farm_zone_loader import (
    default_channel_id,
    get_background_for_family,
    get_spawn_channel_for_family,
    list_zone_channels,
    unreleased_families,
)
from app.shared.formatters import discord_countdown
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

#: Premières apparitions décalées d'une zone à l'autre : sinon les zones
#: tournent ensemble, leurs combats finissent ensemble et leurs vidéos s'empilent.
_ZONE_STAGGER_SECONDS = 25
#: Message laissé quand un redémarrage annule un combat (retiré au retour du bot).
RESTART_NOTE = "🔧 Le bot redémarre : ce combat est annulé, rien n'est perdu."
#: Messages relus par zone au démarrage pour retirer ce que l'ancien processus a laissé.
RESTART_SCAN_LIMIT = 30
#: Un palier de niveau tous les N niveaux est annoncé à tout le serveur.
LEVEL_MILESTONE = 10
#: Sous ce niveau, un joueur seul ne bat presque que le monstre le plus faible
#: de la Clairière. Si la zone n'a vu que des débutants depuis `BEGINNER_MEMORY`,
#: ce monstre a `BEGINNER_WEIGHT` fois plus de chances d'apparaître, sans meute.
BEGINNER_LEVEL = 8
BEGINNER_WEIGHT = 10
BEGINNER_MEMORY = timedelta(minutes=15)

_logger = logging.getLogger(__name__)

from app.bot.rendering.fight_animation import MAX_UPLOAD_BYTES as _VIDEO_MAX_BYTES  # noqa: E402
from app.domain.services.monitoring import kinds
from app.infrastructure.monitoring.telemetry import record_now


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
        # Taille de meute forcée au prochain spawn (/admin spawn_encounter meute:).
        self._zone_forced_pack: dict[int, int] = {}
        # Event de résolution anticipée (/admin start_encounter) par zone.
        self._zone_early_resolve: dict[int, asyncio.Event] = {}
        # Tâche asyncio de chaque zone.
        self._zone_tasks: dict[int, asyncio.Task] = {}
        # Qui est passé dans chaque zone : {salon: {joueur: (niveau, date)}}.
        self._zone_visitors: dict[int, dict[int, tuple[int, datetime]]] = {}

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
        await self._clean_leftovers()
        now = datetime.now(UTC)
        for index, channel_id in enumerate(list_zone_channels()):
            self._zone_next_spawn.setdefault(
                channel_id, now + timedelta(minutes=1, seconds=index * _ZONE_STAGGER_SECONDS))
            self._zone_tasks[channel_id] = asyncio.ensure_future(
                self._zone_loop(channel_id)
            )
        _logger.info("Zones d'encounter démarrées : %s", list(self._zone_tasks.keys()))

    @staticmethod
    def _is_leftover(message, bot_id: int) -> bool:
        """Un monstre posé par l'ancien processus (ses boutons sont morts), ou
        la note d'un redémarrage."""
        if getattr(message.author, "id", None) != bot_id:
            return False
        if message.content.startswith(RESTART_NOTE):
            return True
        return any(getattr(child, "label", None) == "Combattre"
                   for row in message.components for child in getattr(row, "children", ()))

    async def _clean_leftovers(self) -> None:
        """Au démarrage, retire les monstres et notes laissés par le processus
        précédent : personne ne peut plus y répondre."""
        for channel_id in list_zone_channels():
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                continue
            try:
                async for message in channel.history(limit=RESTART_SCAN_LIMIT):
                    if self._is_leftover(message, self.bot.user.id):
                        await self._delete_quietly(message)
            except discord.HTTPException:
                _logger.warning("nettoyage de la zone %s impossible", channel_id, exc_info=True)

    async def prepare_shutdown(self) -> None:
        """Le bot s'arrête (déploiement) : aucun bouton mort ne reste derrière
        lui. Un combat pas encore joué est annulé ; un combat joué affiche son
        récapitulatif, sa vidéo ne sera pas finie."""
        for channel_id, encounter in list(self.active_encounters.items()):
            message = encounter.message
            if message is None:
                continue
            if encounter.resolved and encounter.summary is not None:
                try:
                    await message.edit(embed=build_rewards_page_embed(encounter.summary), attachments=[],
                                       view=None)
                except discord.HTTPException:
                    _logger.warning("récapitulatif d'arrêt impossible", exc_info=True)
                continue
            await self._delete_quietly(message)
            if encounter.participants:
                channel = self.bot.get_channel(channel_id)
                if channel is not None:
                    await self._send_quietly(channel, RESTART_NOTE)

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
        # Une seule zone à la fois : deux combats en parallèle écrivaient les
        # mêmes PV, le second effaçait la mort du premier.
        for other_id, other in self.active_encounters.items():
            if other_id != channel_id and user_id in other.participants and not other.resolved:
                return False, (f"⚔️ Tu es déjà inscrit à un combat dans <#{other_id}>. "
                               "Quitte-le ou termine-le avant d'en rejoindre un autre.")
        success, message = self.encounter_service.register_participant(
            encounter=self.active_encounters.get(channel_id),
            user_id=user_id,
            display_name=display_name,
            avatar_url=avatar_url,
        )
        if success:
            participant = self.active_encounters[channel_id].participants[user_id]
            self._zone_visitors.setdefault(channel_id, {})[user_id] = (participant.level, datetime.now(UTC))
        return success, message

    def _beginners_only(self, channel_id: int) -> bool:
        """La zone n'a vu que des débutants ces dernières minutes."""
        since = datetime.now(UTC) - BEGINNER_MEMORY
        levels = [level for level, at in self._zone_visitors.get(channel_id, {}).values() if at >= since]
        return bool(levels) and max(levels) < BEGINNER_LEVEL

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

    def request_launch(self, channel_id: int, user_id: int) -> tuple[bool, str]:
        """Bouton Lancer : un combattant inscrit démarre le combat sans attendre
        la fin du temps pour rejoindre (une fois passé le délai minimum)."""
        encounter = self.active_encounters.get(channel_id)
        if encounter is None or encounter.resolved:
            return False, "Ce combat a déjà commencé."
        if user_id not in encounter.participants:
            return False, "Rejoins d'abord le combat pour pouvoir le lancer."
        if encounter.launch_after is not None and datetime.now(UTC) < encounter.launch_after:
            return False, ("⏳ Laisse aux autres le temps de venir : tu pourras lancer "
                           f"<t:{int(encounter.launch_after.timestamp())}:R>.")
        event = self._zone_early_resolve.get(channel_id)
        if event is None:
            return False, "Ce combat a déjà commencé."
        event.set()
        return True, "🚀 C'est parti !"

    # ---------------------- Commandes admin (zone-aware) ----------------------

    def _pick_mob_for_zone(self, channel_id: int, forced_code: str | None):
        """Choisit un mob pour la zone : soit le mob forcé, soit un tirage
        pondéré parmi les mobs dont la FAMILLE spawn dans ce salon."""
        with get_db_session() as session:
            repo = MobRepository(session)
            if forced_code is not None:
                return repo.get_by_code(forced_code)
            mobs = repo.list_all()
        hidden = unreleased_families()
        eligible = [
            m
            for m in mobs
            if get_spawn_channel_for_family(m.family) == channel_id and m.spawn_weight > 0
            and m.family not in hidden
        ]
        if not eligible:
            return None
        weights = [m.spawn_weight for m in eligible]
        if self._beginners_only(channel_id):
            # Le premier combat d'un nouveau venu ne doit pas être une défaite.
            power = self.power_score_service.calculate_from_mob
            weakest = min(eligible, key=power)
            weights = [w * (BEGINNER_WEIGHT if m is weakest else 1) for m, w in zip(eligible, weights)]
        return random.choices(eligible, weights=weights, k=1)[0]

    @staticmethod
    def _pack_chance() -> float:
        """Part des apparitions qui sont des meutes (Morrigane, bénédiction
        de l'offrande commune, la relève)."""
        from app.application.use_cases.offering import active_blessing
        from app.domain.services.offering_service import effect_value

        try:
            with get_db_session() as session:
                blessed = effect_value(active_blessing(session), "pack_chance_pct") / 100
        except Exception:  # noqa: BLE001 — une bénédiction illisible ne bloque pas le spawn
            blessed = 0.0
        return max(get_pacing().zones.pack_chance_pct / 100, blessed)

    def _pick_companions(self, channel_id: int, leader, size: int) -> list:
        """Compagnons d'une meute de `size` autour de `leader` (cf.
        pack_service) : monstres de la zone, ni élite ni exclus, de puissance
        voisine. [] si le chef ne mène pas de meute."""
        if size < 2 or is_group_elite(leader.code) or leader.code in pack_service.EXCLUDED:
            return []
        with get_db_session() as session:
            mobs = MobRepository(session).list_all()
        hidden = unreleased_families()
        candidates = [
            m for m in mobs
            if get_spawn_channel_for_family(m.family) == channel_id and m.spawn_weight > 0
            and m.family not in hidden and not is_group_elite(m.code)
            and m.code not in pack_service.EXCLUDED
        ]
        return pack_service.pick_companions(
            leader, candidates, self.power_score_service.calculate_from_mob, size)

    def trigger_immediate_spawn(
        self,
        mob_code: str | None = None,
        element: str | None = None,
        channel_id: int | None = None,
        pack: int = 0,
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
        if pack >= 2:
            self._zone_forced_pack[target] = pack
        else:
            self._zone_forced_pack.pop(target, None)
        self._zone_next_spawn[target] = datetime.now(UTC) - timedelta(seconds=1)

        parts = []
        if mob_code:
            parts.append(mob_code)
        if element:
            parts.append(f"élément {element}")
        if pack >= 2:
            parts.append(f"meute de {pack}")
        suffix = f" ({', '.join(parts)})" if parts else ""
        prefix = "Combat précédent annulé. " if cancelled_existing else ""
        return True, (
            f"{prefix}Spawn forcé{suffix} : un monstre apparaît dans quelques "
            f"secondes (salon `{target}`)."
        )

    def queue_summoned_elite(self, mob_code: str, channel_id: int) -> tuple[bool, str]:
        """Cor de chasse : l'élite apparaîtra dans cette zone, APRÈS le combat
        en cours (on n'annule jamais le combat des autres). Une seule élite
        invoquée par zone à la fois."""
        if channel_id not in set(list_zone_channels()):
            return False, "Cette zone n'est pas ouverte."
        if self._zone_forced_mob.get(channel_id):
            return False, "Un cor a déjà sonné dans cette zone : son élite arrive, attends-la."
        if get_pacing().override(channel_id).paused:
            return False, "Cette zone est en pause : aucun monstre n'y apparaît pour l'instant."
        self._zone_forced_mob[channel_id] = mob_code
        if channel_id not in self.active_encounters:
            self._zone_next_spawn[channel_id] = datetime.now(UTC) - timedelta(seconds=1)
            return True, "arrive dans quelques secondes"
        return True, "arrivera juste après le combat en cours"

    def request_early_resolve(self) -> tuple[bool, str]:
        """Résout immédiatement TOUS les encounters actifs (toutes zones) sans
        attendre la fin de l'attente. Utilisé par /admin start_encounter."""
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

    @staticmethod
    def _current_lunar():
        """L'événement lunaire en cours (pleine lune, lune de sang…), ou None."""
        try:
            return lunar_service.active_event(datetime.now(UTC), get_pacing().lunar)
        except Exception:  # noqa: BLE001 — le ciel ne bloque jamais une apparition
            _logger.exception("calcul de l'événement lunaire impossible")
            return None

    @staticmethod
    def _spawn_description(encounter) -> str:
        """Texte sous le monstre : meute, événement lunaire, et l'heure du
        combat (ou de la fuite s'il n'a pas encore de combattant)."""
        lines = []
        if encounter.pack:
            lines.append(f"🐺 **Une meute !** {encounter.mob_names}")
        event = getattr(encounter, "lunar", None)
        if event is not None:
            lines.append(f"{event.label} — {lunar_service.effects_text(event.rule)}")
        when = discord_countdown(encounter.ends_at)
        if encounter.participants:
            count = len(encounter.participants)
            lines.append(f"⚔️ Le combat se lance {when} — {count} combattant{'s' if count > 1 else ''}. "
                         "Prêts ? Cliquez sur **Lancer**.")
        else:
            lines.append(f"⏳ Sans combattant, le monstre s'enfuit {when}.")
        return "\n".join(lines)

    def _forced_pending(self, channel_id: int) -> bool:
        """Un monstre est attendu (cor de chasse, spawn forcé par l'admin)."""
        return channel_id in self._zone_forced_mob or channel_id in self._zone_forced_pack

    async def _zone_tick(self, channel_id: int) -> None:
        if channel_id in self.active_encounters:
            return

        now = datetime.now(UTC)
        next_at = self._zone_next_spawn.get(channel_id)
        if next_at is not None and now < next_at:
            return

        # Rythme réglé depuis l'admin : zone en pause, heures calmes (un
        # monstre attendu — cor, admin — passe quand même).
        # Les heures calmes s'effacent devant un événement lunaire (ils ont
        # lieu la nuit : sinon on ne les verrait jamais).
        pacing = get_pacing()
        if not self._forced_pending(channel_id) and (
                pacing.override(channel_id).paused
                or (pacing_service.in_quiet_hours(pacing.zones, now) and self._current_lunar() is None)):
            return

        forced_code = self._zone_forced_mob.pop(channel_id, None)
        forced_element = self._zone_forced_element.pop(channel_id, None)
        forced_pack = self._zone_forced_pack.pop(channel_id, 0)
        mob = self._pick_mob_for_zone(channel_id, forced_code)
        if mob is None:
            self._zone_next_spawn[channel_id] = now + timedelta(minutes=1)
            return

        # Meute : de temps en temps (jamais sur un monstre forcé : cor de
        # chasse, test admin), ou forcée par l'admin.
        companions = []
        if forced_pack or (forced_code is None and not self._beginners_only(channel_id)
                           and random.random() < self._pack_chance()):
            size = forced_pack or pack_service.pick_pack_size(
                weights=pacing_service.pack_size_weights(pacing.zones))
            companions = self._pick_companions(channel_id, mob, size)

        await self._run_encounter(channel_id, mob, forced_element=forced_element,
                                  companions=companions)

    def _reschedule(self, channel_id: int, fled: bool = False) -> None:
        """Libère la zone et pose le prochain spawn selon le rythme réglé
        dans l'admin (délai, délai après une fuite, heures calmes)."""
        self.active_encounters.pop(channel_id, None)
        pacing = get_pacing()
        event = self._current_lunar()
        self._zone_next_spawn[channel_id] = pacing_service.next_spawn_at(
            pacing.zones, pacing.override(channel_id), datetime.now(UTC), fled=fled,
            rate=event.rule.spawn_rate if event is not None else 1.0)

    def _scene_inputs(self, channel_id: int, encounter) -> tuple[dict | None, dict | None]:
        """(spot, placement) pour le rendu : décor du couple (zone, élément
        spawné) + placement propre au monstre. None/None → rendu automatique."""
        from app.infrastructure.encounters import farm_zone_loader, mob_placement_loader
        element = getattr(encounter.mob_state, "element", "") or ""
        spot = farm_zone_loader.get_spot(channel_id, element) if element else None
        placement = mob_placement_loader.get_placement(encounter.mob_state.code, element)
        return spot, placement

    def _mob_payload(self, state: dict, element: str) -> dict:
        """Monstre à dessiner (état d'un tour ou du spawn) + élément + puissance."""
        payload = dict(state)
        payload["element"] = element
        payload["power_score"] = self.power_score_service.format_score(
            self.power_score_service.calculate_from_stats(Stats(
                max_hp=payload["max_hp"], attack=payload["attack"], defense=payload["defense"],
                crit_chance=payload.get("crit_chance", 0), crit_damage=payload.get("crit_damage", 100),
                dodge=payload.get("dodge", 0), hp_regeneration=payload.get("hp_regeneration", 0),
                speed=payload.get("speed", 1),
            )))
        return payload

    def _render_kwargs(self, channel_id: int, encounter, turn_log=None) -> dict:
        """Arguments de rendu de la scène : un monstre (`mob`, `placement`) ou
        une meute (`mobs`, `placements`, `formation` de la zone). `turn_log` :
        l'état d'un tour du combat, sinon celui du spawn."""
        from app.infrastructure.encounters import mob_formation_loader, mob_placement_loader

        element = encounter.mob_state.element
        spot, placement = self._scene_inputs(channel_id, encounter)
        if turn_log is not None:
            states = turn_log.enemies_state or [turn_log.mob_state]
        else:
            states = [{
                "code": m.code, "name": m.name, "image_name": m.image_name,
                "current_hp": m.current_hp, "max_hp": m.max_hp, "attack": m.attack,
                "defense": m.defense, "speed": m.speed, "crit_chance": m.crit_chance,
                "crit_damage": m.crit_damage, "dodge": m.dodge, "hp_regeneration": m.hp_regeneration,
            } for m in encounter.mobs]
        payloads = [self._mob_payload(s, element) for s in states]
        # Chiffres de dégâts et effets de l'action (cf. combat_fx).
        fx = {"events": turn_log.events, "fx_seed": turn_log.turn_number} if turn_log is not None else {}
        if len(payloads) == 1:
            payloads[0]["code"] = encounter.mob_state.code
            return {"mob": payloads[0], "spot": spot, "placement": placement, **fx}
        return {
            "mob": None, "spot": spot, "mobs": payloads, **fx,
            "placements": [mob_placement_loader.get_placement(p.get("code"), element) for p in payloads],
            "formation": mob_formation_loader.get_formation(str(channel_id), len(payloads)),
        }

    async def _run_encounter(self, channel_id: int, mob, forced_element: str | None = None,
                             companions: list | None = None) -> None:
        """Cycle de vie complet d'un encounter dans une zone : spawn → fenêtre
        de recrutement (réglable, ou résolution anticipée) → combat animé → récap.
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
        # sinon l'élément stocké du mob (rare, forcé au contenu) ; sinon on le
        # résout via les SPOTS de la zone (élément dispo à cette heure ∩ poids du
        # monstre) ; ultime repli (zone sans spot) = tirage uniforme.
        import random as _random

        from app.infrastructure.encounters.element_spot_resolver import resolve_spawn
        from app.shared.enums import ALL_ELEMENTS
        # Événement lunaire : il peut favoriser un élément (nouvelle lune : ténèbre).
        lunar = self._current_lunar()
        boost = lunar_service.element_boost(lunar.rule) if lunar is not None else {}
        spawn_element = (forced_element or "").strip() or (getattr(mob, "element", "") or "").strip()
        if not spawn_element:
            resolved, _ = resolve_spawn(channel_id, mob.code, element_boost=boost)
            elements = [e.value for e in ALL_ELEMENTS]
            spawn_element = resolved or _random.choices(
                elements, weights=[boost.get(e, 1.0) for e in elements], k=1)[0]

        # Meute : PV et ATK de chacun × le facteur de sa taille (pack_service) ;
        # événement lunaire : × sa force, et sa DÉFENSE × son propre réglage.
        members = [mob, *(companions or [])]
        factor = pack_service.scale(len(members)) * (lunar.rule.strength if lunar is not None else 1.0)
        defense_factor = lunar.rule.defense if lunar is not None else 1.0

        def _state(m) -> EncounterMobState:
            hp = max(1, round(m.max_hp * factor))
            return EncounterMobState(
                code=m.code,
                name=m.name,
                image_name=m.image_name,
                current_hp=hp if factor != 1 else m.current_hp,
                max_hp=hp,
                attack=max(1, round(m.attack * factor)),
                defense=round(m.defense * defense_factor),
                speed=m.speed,
                crit_chance=m.crit_chance,
                crit_damage=m.crit_damage,
                dodge=m.dodge,
                hp_regeneration=m.hp_regeneration,
                element=spawn_element,
            )

        mob_state = _state(mob)
        # Temps pour rejoindre (réglable depuis l'admin, Monde › Rythme) : plus
        # long pour une élite, qu'on ne bat qu'en groupe.
        zones = get_pacing().zones
        window_s = pacing_service.join_window_seconds(zones, elite=is_group_elite(mob.code))

        encounter = ActiveEncounter.create(
            mob_state=mob_state,
            victory_image_name="others/victory.png",
            defeat_image_name="others/defeat.png",
            flee_image_name="others/flee.jpg",
            duration_minutes=window_s / 60,
        )
        encounter.pack = [_state(m) for m in members[1:]]
        encounter.lunar = lunar
        encounter.channel_id = channel_id
        encounter.launch_after = encounter.started_at + timedelta(seconds=zones.launch_min_seconds)

        view = EncounterView(self, channel_id, timeout=window_s)

        spawn_filename = f"encounter_spawn_{encounter.mob_state.code}.jpg"
        spawn_output_full = self.generated_dir / spawn_filename
        spawn_output_relative = f"generated_encounters/{spawn_filename}"

        # Rendu Pillow + téléchargement d'avatars : sync et CPU/IO-bound.
        # Sans to_thread, ça bloque tout l'event loop pendant le rendu (~1-2s
        # + jusqu'à 15s par avatar lent) → heartbeat Discord et autres
        # interactions gelés. Cf. audit Phase 1 finding B5.
        await asyncio.to_thread(
            compose_players_banner,
            players=[],
            output_path=str(spawn_output_full),
            background_path=str(background_path),
            players_power_score="",
            **self._render_kwargs(channel_id, encounter),
        )

        embed, file = build_encounter_embed(
            image_name=spawn_output_relative,
        )
        embed.description = self._spawn_description(encounter)

        message = await channel.send(embed=embed, view=view, file=file)
        encounter.message_id = message.id
        encounter.message = message
        self.active_encounters[channel_id] = encounter
        try:
            await self._play_encounter(channel, channel_id, encounter, view, message,
                                       background_path, window_s)
        finally:
            # Quoi qu'il arrive (Discord en panne, récapitulatif refusé…), la
            # zone repart : sinon elle restait figée jusqu'au redémarrage.
            if self.active_encounters.get(channel_id) is encounter:
                self._reschedule(channel_id)

    async def _play_encounter(self, channel, channel_id: int, encounter, view, message,
                              background_path, window_s: int) -> None:
        """Du monstre posé au récapitulatif : attente, fuite ou combat, vidéo.
        La zone est libérée par l'appelant, quoi qu'il arrive ici."""
        # Fenêtre de recrutement : le temps pour rejoindre, ou jusqu'au bouton
        # Lancer et au signal d'/admin start_encounter (early resolve).
        event = asyncio.Event()
        self._zone_early_resolve[channel_id] = event
        try:
            await asyncio.wait_for(event.wait(), timeout=window_s)
        except asyncio.TimeoutError:
            pass
        finally:
            self._zone_early_resolve.pop(channel_id, None)

        for child in view.children:
            child.disabled = True

        # L'encounter a-t-il été annulé/remplacé pendant la fenêtre (admin
        # end/spawn) ? Si oui, on retire son message et on abandonne sans
        # reprogrammer (celui qui a annulé a déjà posé le prochain spawn).
        if self.active_encounters.get(channel_id) is not encounter:
            await self._delete_quietly(message)
            return

        if not encounter.participants:
            # Personne n'est venu : le message part avec le monstre. Il en
            # restait ~240 par jour et par zone, qui noyaient les vrais combats.
            await self._delete_quietly(message)
            self._reschedule(channel_id, fled=True)
            await asyncio.to_thread(record_now, get_db_session, kinds.FLEE, zone=channel_id,
                                    ref=encounter.mob_state.code, qty=len(encounter.mobs))
            return

        result = self.encounter_service.resolve_active_encounter(encounter)
        if result is None or not encounter.participants:
            # Tous les inscrits sont tombés ailleurs entre-temps : pas de combat.
            await self._delete_quietly(message)
            return

        self.encounter_service.persist_final_players_hp(result, encounter)
        battle_summary = self.encounter_service.apply_rewards(encounter, result)
        encounter.resolved = True
        encounter.summary = battle_summary

        if battle_summary is not None:
            battle_summary.journal = [format_turn_action(log) for log in result.turn_logs]

        # Les combattants sont prévenus : le combat se joue en direct ici. (Le
        # message part une fois la vidéo finie : le récapitulatif reste seul.)
        mentions = " ".join(f"<@{p.user_id}>" for p in encounter.participants.values())
        announce = None
        try:
            announce = await channel.send(
                f"⚔️ **Le combat contre {encounter.mob_names} commence !** {mentions}\n"
                f"Il se joue en direct : {message.jump_url}",
                allowed_mentions=discord.AllowedMentions(users=True, everyone=False, roles=False))
        except discord.HTTPException:
            _logger.warning("annonce du début du combat impossible", exc_info=True)

        # Le combat en VIDÉO (27/10/2026) : un GIF qui se lance tout seul et ne
        # boucle pas, puis le message passe au récapitulatif. Il remplace les
        # images toutes les 1,5 s et le message « combat en cours » (le
        # déroulé est la 3e page du récapitulatif).
        await self._play_fight_video(channel_id, encounter, message, result, background_path)

        if announce is not None:
            await self._delete_quietly(announce)
        if battle_summary is None:
            return

        summary_view = BattleSummaryView(battle_summary, timeout=600.0)
        summary_view.message = message
        try:
            await message.edit(embed=summary_view.current_embed, attachments=[], view=summary_view)
        except discord.HTTPException:
            # Les récompenses sont déjà données : le joueur doit au moins le savoir.
            _logger.exception("récapitulatif du combat refusé par Discord")
            await self._send_quietly(channel, f"⚔️ Combat terminé contre {battle_summary.mob_name} : "
                                              "les récompenses sont distribuées (/profil, /inventaire).")

        await self._announce_mythics(channel, battle_summary, getattr(message, "jump_url", None))
        await self._announce_milestones(battle_summary)

    @staticmethod
    async def _delete_quietly(message) -> None:
        try:
            await message.delete()
        except discord.HTTPException:
            _logger.warning("message du combat non supprimé", exc_info=True)

    @staticmethod
    async def _send_quietly(channel, text: str) -> None:
        try:
            await channel.send(text)
        except discord.HTTPException:
            _logger.warning("message non envoyé", exc_info=True)

    def _render_fight_video(self, channel_id: int, encounter, result, background_path):
        """Le GIF du combat (cf. `fight_animation`), ou None si le rendu
        échoue ou dépasse la taille d'un envoi Discord même réduit."""
        from app.application.services.encounter_service import EncounterService
        from app.bot.rendering.fight_animation import WIDTH, animate_fight
        from app.bot.rendering.fight_scene import build_scene

        if not result.turn_logs:
            return None
        first = result.turn_logs[0]
        players = [dict(p) for p in first.players_state]
        by_user = {p.user_id: p for p in encounter.participants.values()}
        start_players = {}
        for p in players:
            part = by_user.get(p.get("user_id"))
            start = (EncounterService._scaled_hp(part.current_hp, part.max_hp, p["max_hp"])
                     if part is not None else p["current_hp"])
            start_players[f"p{p['player_id']}"] = (start, p["max_hp"])
        kwargs = self._render_kwargs(channel_id, encounter)
        scene = build_scene(players=players, background_path=str(background_path),
                            **{k: v for k, v in kwargs.items() if k in (
                                "mob", "spot", "placement", "mobs", "placements", "formation")})
        first_enemies = first.enemies_state or [first.mob_state]
        start_enemies = {
            f"e{i}": (m.current_hp, m.max_hp, int((first_enemies[i] if i < len(first_enemies) else {})
                                                   .get("shield", 0) or 0))
            for i, m in enumerate(encounter.mobs)
        }
        out = self.generated_dir / f"encounter_{encounter.message_id}_combat.gif"
        for width in (WIDTH, 440):
            anim = animate_fight(scene, start_enemies, start_players, result.turn_logs, out, width=width)
            if anim.size_bytes <= _VIDEO_MAX_BYTES:
                return anim
        out.unlink(missing_ok=True)
        return None

    async def _play_fight_video(self, channel_id: int, encounter, message, result, background_path) -> None:
        """Joue la vidéo du combat dans le message du monstre, le temps qu'elle
        dure (best effort : sans vidéo, on passe directement au récapitulatif)."""
        try:
            await message.edit(embed=discord.Embed(
                title=f"⚔️ Le combat s'engage — {encounter.mob_names}",
                description="_Les coups pleuvent…_", color=discord.Color.orange()), view=None)
        except discord.HTTPException:
            pass
        try:
            # Une vidéo à la fois (mémoire) ; file trop longue ⇒ récapitulatif direct.
            async with video_slot() as granted:
                if not granted:
                    _logger.warning("file des vidéos trop longue : combat sans vidéo")
                    return
                anim = await asyncio.to_thread(self._render_fight_video, channel_id, encounter, result,
                                               background_path)
        except Exception:
            _logger.exception("vidéo du combat échouée")
            return
        if anim is None:
            return
        embed = discord.Embed(title=f"⚔️ {encounter.mob_names}", color=discord.Color.orange())
        embed.set_image(url=f"attachment://{anim.path.name}")
        try:
            await message.edit(embed=embed, attachments=[discord.File(anim.path, filename=anim.path.name)],
                               view=None)
            await asyncio.sleep(anim.duration_s + 1.0)
        except discord.HTTPException:
            _logger.warning("envoi de la vidéo du combat échoué", exc_info=True)
        finally:
            anim.path.unlink(missing_ok=True)   # Discord garde sa copie

    @staticmethod
    async def _announce_mythics(channel, summary, jump_url: str | None) -> None:
        """Un mythique tombe environ 1 fois sur 25 000 morts : c'est un
        événement pour tout le serveur, on l'annonce dans le salon."""
        for reward in getattr(summary, "rewards", None) or []:
            for gear_name, rarity in getattr(reward, "gear", None) or []:
                if rarity != "mythic":
                    continue
                embed = discord.Embed(
                    title="🔴 UNE PIÈCE MYTHIQUE EST TOMBÉE",
                    description=(
                        f"<@{reward.user_id}> vient d'arracher **{gear_name}** "
                        f"(mythique) à {summary.mob_name} !"
                        + (f"\n[Voir le combat]({jump_url})" if jump_url else "")
                    ),
                    color=discord.Color.from_rgb(235, 70, 90),
                )
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    pass

    async def _announce_milestones(self, summary) -> None:
        """Les paliers de niveau (tous les 10) sont annoncés à tout le serveur,
        sans mentionner personne (le joueur l'a déjà vu dans son récapitulatif)."""
        lines = []
        for reward in getattr(summary, "rewards", None) or []:
            before, after = reward.level_before, reward.level_after
            if before and after // LEVEL_MILESTONE > before // LEVEL_MILESTONE:
                lines.append(f"🌸 **{discord.utils.escape_markdown(reward.name)}** atteint le "
                             f"**niveau {after // LEVEL_MILESTONE * LEVEL_MILESTONE}** !")
        if not lines:
            return
        channel = self.bot.get_channel(settings.rank_announce_channel_id)
        if channel is None:
            return
        try:
            await channel.send("\n".join(lines), allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            _logger.warning("annonce de palier impossible", exc_info=True)

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

        filename = f"encounter_{encounter.message_id}_current.jpg"
        output_full = self.generated_dir / filename
        output_relative = f"generated_encounters/{filename}"
        background_path = self._zone_bg.get(
            channel_id, str(LANDSCAPES_ASSETS_DIR / "clairiere_sinistre.png")
        )

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
            output_path=str(output_full),
            background_path=str(background_path),
            players_power_score=players_power_score,
            **self._render_kwargs(channel_id, encounter),
        )

        embed, file = build_encounter_embed(
            image_name=output_relative,
        )
        embed.description = self._spawn_description(encounter)

        await message.edit(embed=embed, attachments=[file])


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EncounterCog(bot))
