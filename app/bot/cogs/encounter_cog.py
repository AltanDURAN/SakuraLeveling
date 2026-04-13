import asyncio

import discord
from discord.ext import commands, tasks
from pathlib import Path
from datetime import datetime, timezone

from app.bot.embeds.encounter_embeds import build_encounter_embed
from app.bot.runtime.active_encounter import ActiveEncounter
from app.bot.views.encounter_view import EncounterView
from app.domain.services.party_combat_service import PartyCombatService
from app.domain.services.stats_service import StatsService
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session
from app.bot.runtime.encounter_participant import EncounterParticipant
from app.bot.rendering.fight_scene import compose_players_banner
from app.shared.paths import GENERATED_ENCOUNTERS_DIR, LANDSCAPES_ASSETS_DIR
from app.bot.runtime.encounter_mob_state import EncounterMobState
from app.infrastructure.db.repositories.player_health_repository import PlayerHealthRepository
from app.domain.services.health_regeneration_service import HealthRegenerationService
from app.shared.paths import GENERATED_ENCOUNTERS_DIR, LANDSCAPES_ASSETS_DIR
from app.bot.rendering.fight_scene import compose_players_banner

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
print("=======================")
print(BASE_DIR)
print("=======================")
class EncounterCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_encounter: ActiveEncounter | None = None
        self.encounter_loop.start()
        self.generated_dir = GENERATED_ENCOUNTERS_DIR
        self.generated_dir.mkdir(exist_ok=True)

    def cog_unload(self):
        self.encounter_loop.cancel()

    async def register_participant(
        self,
        user_id: int,
        display_name: str,
        avatar_url: str,
    ) -> tuple[bool, str]:
        if self.active_encounter is None:
            return False, "Aucun combat à rejoindre."

        if user_id in self.active_encounter.participants:
            return False, "Vous avez déjà rejoint le combat."

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            equipment_repository = EquipmentRepository(session)
            class_repository = ClassRepository(session)
            player_health_repository = PlayerHealthRepository(session)

            profile = player_repository.get_by_discord_id(user_id)
            if profile is None:
                return False, "Votre profil joueur n'existe pas encore. Utilisez /profile d'abord."

            equipped_items = equipment_repository.list_by_player_id(profile.player.id)
            active_class = class_repository.get_current_class_for_player(profile.player.id)

            stats = StatsService().calculate_player_stats(
                profile=profile,
                equipped_items=equipped_items,
                active_class=active_class,
            )

            health_state = player_health_repository.get_or_create(
                player_id=profile.player.id,
                default_current_hp=stats.max_hp,
            )

            now = datetime.now(timezone.utc)

            regenerated_current_hp = HealthRegenerationService().apply_out_of_combat_regeneration(
                current_hp=health_state.current_hp,
                max_hp=stats.max_hp,
                hp_regeneration=stats.hp_regeneration,
                last_updated_at=health_state.updated_at,
                now=now,
            )

            print(f"[REGEN] old={health_state.current_hp} new={regenerated_current_hp} max={stats.max_hp} regen={stats.hp_regeneration}")
            player_health_repository.update_current_hp(
                player_id=profile.player.id,
                current_hp=regenerated_current_hp,
            )

        participant = EncounterParticipant(
            user_id=user_id,
            player_id=profile.player.id,
            display_name=display_name,
            avatar_url=avatar_url,
            current_hp=regenerated_current_hp,
            max_hp=stats.max_hp,
        )

        self.active_encounter.participants[user_id] = participant

        print(f"[ENCOUNTER] {display_name} a rejoint le combat.")
        print(f"[AVATAR] {avatar_url}")

        return True, "Vous avez rejoint le combat."

    @tasks.loop(minutes=1)
    async def encounter_loop(self):
        channel = self.bot.get_channel(settings.encounter_channel_id)
        if channel is None:
            return

        if self.active_encounter is not None:
            return

        with get_db_session() as session:
            mob_repository = MobRepository(session)
            mob = mob_repository.get_random()

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
        )

        encounter = ActiveEncounter.create(
            mob_state=mob_state,
            victory_image_name="others/victory.png",
            defeat_image_name="others/defeat.png",
            flee_image_name="others/flee.jpg",
            duration_minutes=1,
        )

        view = EncounterView(self)
        embed, file = build_encounter_embed(
            mob_name=encounter.mob_state.name,
            image_name="mobs/" + encounter.mob_state.image_name,
            state_text="Un monstre apparaît. Cliquez sur **Combattre** pour rejoindre l'expédition.",
        )

        message = await channel.send(embed=embed, view=view, file=file)
        encounter.message_id = message.id
        self.active_encounter = encounter

        await asyncio.sleep(60) #spawn_time

        for child in view.children:
            child.disabled = True

        if self.active_encounter is None:
            return

        if not self.active_encounter.participants:
            flee_embed, file = build_encounter_embed(
                mob_name=self.active_encounter.mob_state.name,
                image_name=self.active_encounter.flee_image_name,
                state_text="Le monstre s'est enfui...",
            )
            await message.edit(embed=flee_embed, attachments=[file], view=view)
            self.active_encounter = None
            return

        result = self.resolve_active_encounter()
        if result is None:
            self.active_encounter = None
            return

        background_path = LANDSCAPES_ASSETS_DIR / "clairiere_sinistre.png"

        for index, turn_log in enumerate(result.turn_logs):
            output_relative = f"generated_encounters/encounter_{self.active_encounter.message_id}_turn_{index + 1}.png"
            output_full = GENERATED_ENCOUNTERS_DIR / f"encounter_{self.active_encounter.message_id}_turn_{index + 1}.png"

            compose_players_banner(
                players=turn_log.players_state,
                mob=turn_log.mob_state,
                output_path=str(output_full),
                background_path=str(background_path),
            )

            turn_embed, file = build_encounter_embed(
                mob_name=self.active_encounter.mob_state.name,
                image_name=output_relative,
                state_text=f"⚔️ Combat en cours... Tour {index + 1}",
            )

            await message.edit(embed=turn_embed, attachments=[file], view=view)
            await asyncio.sleep(1.5)

        final_image = (
            self.active_encounter.victory_image_name
            if result.victory
            else self.active_encounter.defeat_image_name
        )

        final_text = (
            f"🏆 Victoire en {result.turns} tour(s) !"
            if result.victory
            else f"💀 Défaite après {result.turns} tour(s)."
        )

        final_embed, file = build_encounter_embed(
            mob_name=self.active_encounter.mob_state.name,
            image_name=final_image,
            state_text=final_text,
        )

        await message.edit(embed=final_embed, attachments=[file], view=view)
        self.active_encounter = None

    @encounter_loop.before_loop
    async def before_encounter_loop(self):
        await self.bot.wait_until_ready()

    def resolve_active_encounter(self):
        if self.active_encounter is None:
            return None

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            equipment_repository = EquipmentRepository(session)
            class_repository = ClassRepository(session)
            mob_repository = MobRepository(session)

            mob = mob_repository.get_by_code(self.active_encounter.mob_state.code)
            if mob is None:
                return None

            party = []

            for participant in self.active_encounter.participants.values():
                profile = player_repository.get_by_discord_id(participant.user_id)
                if profile is None:
                    continue

                equipped_items = equipment_repository.list_by_player_id(participant.player_id)
                active_class = class_repository.get_current_class_for_player(participant.player_id)

                stats = StatsService().calculate_player_stats(
                    profile=profile,
                    equipped_items=equipped_items,
                    active_class=active_class,
                )

                party.append(
                    {
                        "name": participant.display_name,
                        "avatar_url": participant.avatar_url,
                        "current_hp": participant.current_hp,
                        "max_hp": participant.max_hp,
                        "stats": stats,
                    }
                )

        if not party:
            return None

        return PartyCombatService().fight_party_vs_mob(
            party=party,
            mob=mob,
        )
    
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
            }
            for participant in self.active_encounter.participants.values()
        ]

        if not players:
            return

        output = self.generated_dir / f"encounter_{self.active_encounter.message_id}.png"
        output_path = "generated_encounters/" + f"encounter_{self.active_encounter.message_id}.png"
        background_path = LANDSCAPES_ASSETS_DIR / "clairiere_sinistre.png"

        with get_db_session() as session:
            mob_repository = MobRepository(session)
            mob = mob_repository.get_by_code(self.active_encounter.mob_state.code)
        
        print("###################")
        print(mob)
        print(mob.name)
        print("###################")
        
        mob = {
            "name": mob.name,
            "image_name": mob.image_name,
            "current_hp": mob.current_hp,
            "max_hp": mob.max_hp,
            "attack": mob.attack,
            "defense": mob.defense,
        }
        
        print(mob)

        compose_players_banner(
            players=players,
            mob=mob,
            output_path="assets/" + output_path,
            background_path=str(background_path),
        )

        embed, file = build_encounter_embed(
            mob_name=self.active_encounter.mob_state.name,
            image_name=output_path,
            state_text="Des aventuriers se rassemblent pour le combat...",
        )

        view = EncounterView(self, timeout=60) #spawn_time

        await message.edit(embed=embed, attachments=[file], view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EncounterCog(bot))