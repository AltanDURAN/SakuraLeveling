import asyncio

import discord
from discord.ext import commands, tasks

from app.application.services.encounter_service import EncounterService
from app.bot.embeds.encounter_embeds import build_encounter_embed
from app.bot.rendering.fight_scene import compose_players_banner
from app.bot.runtime.active_encounter import ActiveEncounter
from app.bot.runtime.encounter_mob_state import EncounterMobState
from app.bot.views.encounter_view import EncounterView
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.session import get_db_session
from app.shared.paths import GENERATED_ENCOUNTERS_DIR, LANDSCAPES_ASSETS_DIR


class EncounterCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_encounter: ActiveEncounter | None = None
        self.encounter_service = EncounterService()
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
        success, message = self.encounter_service.register_participant(
            encounter=self.active_encounter,
            user_id=user_id,
            display_name=display_name,
            avatar_url=avatar_url,
        )

        return success, message

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
            image_name=f"mobs/{encounter.mob_state.image_name}",
            state_text="Un monstre apparaît. Cliquez sur **Combattre** pour rejoindre l'expédition.",
        )

        message = await channel.send(embed=embed, view=view, file=file)
        encounter.message_id = message.id
        self.active_encounter = encounter

        await asyncio.sleep(60)  # spawn_time

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

        self.persist_final_players_hp(result)
        self.encounter_service.apply_rewards(self.active_encounter, result)

        background_path = LANDSCAPES_ASSETS_DIR / "clairiere_sinistre.png"

        for index, turn_log in enumerate(result.turn_logs):
            filename = f"encounter_{self.active_encounter.message_id}_turn_{index + 1}.png"
            output_full = self.generated_dir / filename
            output_relative = f"generated_encounters/{filename}"

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
            }
            for participant in self.active_encounter.participants.values()
        ]

        if not players:
            return

        filename = f"encounter_{self.active_encounter.message_id}.png"
        output_full = self.generated_dir / filename
        output_relative = f"generated_encounters/{filename}"
        background_path = LANDSCAPES_ASSETS_DIR / "clairiere_sinistre.png"

        with get_db_session() as session:
            mob_repository = MobRepository(session)
            mob = mob_repository.get_by_code(self.active_encounter.mob_state.code)

        if mob is None:
            return

        mob_payload = {
            "name": mob.name,
            "image_name": mob.image_name,
            "current_hp": mob.current_hp,
            "max_hp": mob.max_hp,
            "attack": mob.attack,
            "defense": mob.defense,
        }

        compose_players_banner(
            players=players,
            mob=mob_payload,
            output_path=str(output_full),
            background_path=str(background_path),
        )

        embed, file = build_encounter_embed(
            mob_name=self.active_encounter.mob_state.name,
            image_name=output_relative,
            state_text="Des aventuriers se rassemblent pour le combat...",
        )

        view = EncounterView(self, timeout=60)  # spawn_time

        await message.edit(embed=embed, attachments=[file], view=view)

    def persist_final_players_hp(self, result) -> None:
        self.encounter_service.persist_final_players_hp(result)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EncounterCog(bot))