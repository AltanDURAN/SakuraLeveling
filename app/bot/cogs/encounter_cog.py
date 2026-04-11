import asyncio

import discord
from discord.ext import commands, tasks
from pathlib import Path

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
from tests.sandbox.fight_scene import compose_players_banner

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
print("=======================")
print(BASE_DIR)
print("=======================")
class EncounterCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_encounter: ActiveEncounter | None = None
        self.encounter_loop.start()
        self.generated_dir = Path("generated_encounters")
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

        participant = EncounterParticipant(
            user_id=user_id,
            display_name=display_name,
            avatar_url=avatar_url,
            current_hp=stats.max_hp,  # temporairement full HP
            max_hp=stats.max_hp,
        )

        self.active_encounter.participants[user_id] = participant

        print(f"[ENCOUNTER] {display_name} a rejoint le combat.")
        print(f"[AVATAR] {avatar_url}")

        await self.refresh_encounter_scene()

        return True, "Vous avez rejoint le combat."

    @tasks.loop(minutes=5)
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

        encounter = ActiveEncounter.create(
            mob_code=mob.code,
            mob_name=mob.name,
            spawn_image_url=mob.image_url,
            turn_image_urls=[
                "https://maisons-alfort.fr/wp-content/uploads/2019/01/TRAVAUX.jpg",
                "https://www.guichenpontrean.fr/medias/sites/7/2015/10/Travaux-2.jpg",
                "https://www.arpajon91.fr/Files/9/d/csm_Info_travaux_page-0001_97d7fe931e.jpg",
            ],
            victory_image_url="https://static1.millenium.org/article_old/images/contenu/actus/LOL/Rominnoux/Victory.png",
            defeat_image_url="https://static1.millenium.org/article_old/images/contenu/actus/LOL/Rominnoux/Defeat.png",
            flee_image_url="https://media.istockphoto.com/id/1225549108/fr/vectoriel/ex%C3%A9cuter-sport-illustration-dic%C3%B4ne-vectorielle-dexercice.jpg?s=612x612&w=0&k=20&c=GRCiH7FF_i-YicXcn1XbQwtEucJOwNd2zTgZQS_aY6U=",
            duration_minutes=5,
        )

        view = EncounterView(self)
        embed = build_encounter_embed(
            mob_name=encounter.mob_name,
            image_url=encounter.spawn_image_url,
            state_text="Un monstre apparaît. Cliquez sur **Combattre** pour rejoindre l'expédition.",
        )

        message = await channel.send(embed=embed, view=view)
        encounter.message_id = message.id
        self.active_encounter = encounter

        await asyncio.sleep(300)

        for child in view.children:
            child.disabled = True

        if self.active_encounter is None:
            return

        if not self.active_encounter.participant_user_ids:
            flee_embed = build_encounter_embed(
                mob_name=self.active_encounter.mob_name,
                image_url=self.active_encounter.flee_image_url,
                state_text="Le monstre s'est enfui...",
            )
            await message.edit(embed=flee_embed, view=view)
            self.active_encounter = None
            return

        result = self.resolve_active_encounter()
        if result is None:
            self.active_encounter = None
            return

        for index, _turn_log in enumerate(result.turn_logs):
            image_url = None
            if index < len(self.active_encounter.turn_image_urls):
                image_url = self.active_encounter.turn_image_urls[index]

            turn_embed = build_encounter_embed(
                mob_name=self.active_encounter.mob_name,
                image_url=image_url,
                state_text=f"⚔️ Combat en cours... Tour {index + 1}",
            )

            await message.edit(embed=turn_embed, view=view)
            await asyncio.sleep(1.5)

        final_image = (
            self.active_encounter.victory_image_url
            if result.victory
            else self.active_encounter.defeat_image_url
        )

        final_text = (
            f"🏆 Victoire en {result.turns} tour(s) !"
            if result.victory
            else f"💀 Défaite après {result.turns} tour(s)."
        )

        final_embed = build_encounter_embed(
            mob_name=self.active_encounter.mob_name,
            image_url=final_image,
            state_text=final_text,
        )

        await message.edit(embed=final_embed, view=view)
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

            mob = mob_repository.get_by_code(self.active_encounter.mob_code)
            if mob is None:
                return None

            party = []

            for user_id in self.active_encounter.participant_user_ids:
                profile = player_repository.get_by_discord_id(user_id)
                if profile is None:
                    continue

                equipped_items = equipment_repository.list_by_player_id(profile.player.id)
                active_class = class_repository.get_current_class_for_player(profile.player.id)

                stats = StatsService().calculate_player_stats(
                    profile=profile,
                    equipped_items=equipped_items,
                    active_class=active_class,
                )

                party.append((profile.player.display_name, stats))

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
                "avatar_url": participant.avatar_url,
                "current_hp": participant.current_hp,
                "max_hp": participant.max_hp,
            }
            for participant in self.active_encounter.participants.values()
        ]

        if not players:
            return

        output_path = self.generated_dir / f"encounter_{self.active_encounter.message_id}.png"
        background_path = BASE_DIR / "assets" / "landscapes" / "clairiere_sinistre.png"

        compose_players_banner(
            players=players,
            output_path=str(output_path),
            background_path=str(background_path),
        )

        filename = output_path.name
        file = discord.File(output_path, filename=filename)

        embed = build_encounter_embed(
            mob_name=self.active_encounter.mob_name,
            image_url=None,
            state_text="Des aventuriers se rassemblent pour le combat...",
            generated_image_name=filename,
        )

        view = EncounterView(self, timeout=300)

        await message.edit(embed=embed, attachments=[file], view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EncounterCog(bot))