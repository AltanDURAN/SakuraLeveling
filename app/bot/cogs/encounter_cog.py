import asyncio
import random
from datetime import datetime

import discord
from discord.ext import commands, tasks

from app.bot.embeds.battle_embeds import build_battle_result_embed
from app.bot.embeds.encounter_embeds import (
    build_encounter_no_participants_embed,
    build_encounter_spawn_embed,
)
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


class EncounterCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_encounter: ActiveEncounter | None = None
        self.encounter_loop.start()

    def cog_unload(self):
        self.encounter_loop.cancel()

    def register_participant(self, user_id: int) -> tuple[bool, str]:
        if self.active_encounter is None:
            return False, "Aucun combat à rejoindre."
        if datetime.utcnow() >= self.active_encounter.ends_at:
            return False, "Le recrutement est terminé."
        if user_id in self.active_encounter.participant_user_ids:
            return False, "Vous avez déjà rejoint le combat."

        self.active_encounter.participant_user_ids.add(user_id)
        return True, "Vous avez rejoint le groupe d'aventuriers."

    @tasks.loop(minutes=5)
    async def encounter_loop(self):
        channel = self.bot.get_channel(settings.encounter_channel_id)
        if channel is None:
            return

        if self.active_encounter is not None:
            return

        with get_db_session() as session:
            mob_repository = MobRepository(session)
            mob = mob_repository.get_by_code("slime")

        if mob is None:
            return

        encounter = ActiveEncounter.create(
            mob_code=mob.code,
            mob_name=mob.name,
            mob_image_url=mob.image_url,
            duration_minutes=5,
        )

        embed = build_encounter_spawn_embed(encounter)
        view = EncounterView(self)

        message = await channel.send(embed=embed, view=view)
        encounter.message_id = message.id
        self.active_encounter = encounter

        await asyncio.sleep(300)

        view.children[0].disabled = True
        await message.edit(view=view)

        if self.active_encounter is None:
            return

        if not self.active_encounter.participant_user_ids:
            embed = build_encounter_no_participants_embed(self.active_encounter)
            await message.edit(embed=embed, view=view)
            self.active_encounter = None
            return

        result = self.resolve_active_encounter()

        if result is None:
            self.active_encounter = None
            return

        final_embed = build_battle_result_embed_from_party(result)
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


def build_battle_result_embed_from_party(result):
    color = discord.Color.green() if result.victory else discord.Color.red()

    embed = discord.Embed(
        title=f"⚔️ Résultat — {result.mob_name}",
        description=result.summary,
        color=color,
    )

    if result.mob_image_url:
        embed.set_thumbnail(url=result.mob_image_url)

    embed.add_field(name="🕒 Tours", value=str(result.turns), inline=True)
    embed.add_field(name="👾 PV restants monstre", value=str(result.mob_remaining_hp), inline=True)
    embed.add_field(name="🏆 Victoire", value="Oui" if result.victory else "Non", inline=True)

    if result.surviving_players:
        embed.add_field(
            name="🧍 Survivants",
            value="\n".join(result.surviving_players),
            inline=False,
        )

    if result.defeated_players:
        embed.add_field(
            name="💀 Vaincus",
            value="\n".join(result.defeated_players),
            inline=False,
        )

    if result.victory:
        embed.add_field(name="✨ XP gagnée", value=str(result.xp_gained), inline=True)
        embed.add_field(name="💰 Gold gagné", value=str(result.gold_gained), inline=True)

    if result.turn_logs:
        last_turn = result.turn_logs[-1]
        embed.add_field(
            name="📜 Dernier tour",
            value=(
                f"Actions des joueurs :\n" + "\n".join(last_turn.player_actions) + "\n\n"
                f"Action du monstre :\n{last_turn.mob_action}\n\n"
                f"État du groupe :\n{last_turn.party_hp_summary}"
            ),
            inline=False,
        )

    return embed


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EncounterCog(bot))