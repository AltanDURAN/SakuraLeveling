"""Cog des quêtes quotidiennes (/daily_quest).

3 quêtes assignées chaque jour à minuit UTC. Bouton 'Récupérer ma/mes
récompense(s)' affiché si au moins une quête est complétée non-claim.
"""

import discord
from discord import app_commands
from discord.ext import commands

from app.application.use_cases.daily_quests import (
    ClaimAllDailyUseCase,
    DailyQuestState,
    GetDailyQuestsUseCase,
)
from app.bot.views.quest_claim_view import QuestClaimView
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.daily_quest_repository import DailyQuestRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session


def _build_progress_bar(progress: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return "—"
    ratio = min(1.0, max(0.0, progress / total))
    filled = int(round(ratio * width))
    return "▰" * filled + "▱" * (width - filled)


def _tier_emoji(tier: str) -> str:
    return {"easy": "🟢", "medium": "🟡", "hard": "🔴"}.get(tier, "⚪")


def build_daily_embed(display_name: str, state: DailyQuestState) -> discord.Embed:
    embed = discord.Embed(
        title=f"📅 Quêtes quotidiennes de {display_name}",
        description=(
            f"Reset à minuit UTC. Dernière rotation : "
            f"<t:{int(state.day_start.timestamp())}:D>."
        ),
        color=discord.Color.teal(),
    )
    if not state.quests:
        embed.add_field(name="—", value="Aucune quête assignée.", inline=False)
        return embed

    for q in state.quests:
        if q.claimed:
            status_emoji = "🎁"
        elif q.completed:
            status_emoji = "✅"
        else:
            status_emoji = "⏳"
        bar = _build_progress_bar(q.progress, q.objective_quantity)
        items_label = (
            ", ".join(f"{qty}× `{c}`" for c, qty in q.reward_items)
            if q.reward_items
            else "—"
        )
        value = (
            f"{q.description}\n"
            f"{bar} **{q.progress}/{q.objective_quantity}**\n"
            f"💰 {q.reward_gold} or | ✨ {q.reward_xp} xp | 🎁 {items_label}"
        )
        embed.add_field(
            name=f"{status_emoji} {_tier_emoji(q.tier)} {q.name}",
            value=value, inline=False,
        )
    return embed


class DailyQuestCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.channel_id != settings.beta_channel_id:
            message = (
                "🚧 Le bot est actuellement en phase de test.\n"
                "Utilisez le channel beta dédié."
            )
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return False
        return True

    @app_commands.command(
        name="daily_quest",
        description="Voir et réclamer vos 3 quêtes quotidiennes",
    )
    async def daily_quest(self, interaction: discord.Interaction) -> None:
        state = self._fetch_state(interaction)
        embed = build_daily_embed(interaction.user.display_name, state)
        view = self._build_view(interaction, state)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    def _fetch_state(self, interaction: discord.Interaction) -> DailyQuestState:
        with get_db_session() as session:
            return GetDailyQuestsUseCase(
                player_repository=PlayerRepository(session),
                quest_repository=DailyQuestRepository(session),
            ).execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )

    def _build_view(
        self, interaction: discord.Interaction, state: DailyQuestState,
    ) -> QuestClaimView:
        async def on_claim(claim_interaction: discord.Interaction) -> None:
            await claim_interaction.response.defer(ephemeral=True)
            with get_db_session() as session:
                use_case = ClaimAllDailyUseCase(
                    player_repository=PlayerRepository(session),
                    quest_repository=DailyQuestRepository(session),
                    item_repository=ItemRepository(session),
                    inventory_repository=InventoryRepository(session),
                )
                result = use_case.execute(
                    discord_id=claim_interaction.user.id,
                    username=claim_interaction.user.name,
                    display_name=claim_interaction.user.display_name,
                )

            if not result.success:
                await claim_interaction.followup.send(result.message, ephemeral=True)
                return

            lines = [result.message]
            total_gold = sum(r.gold for r in result.rewards)
            total_xp = sum(r.xp for r in result.rewards)
            lines.append(f"💰 +{total_gold} or | ✨ +{total_xp} xp")
            for r in result.rewards:
                items_label = (
                    " — " + ", ".join(f"{q}× `{c}`" for c, q in r.items)
                    if r.items
                    else ""
                )
                lines.append(f"  • **{r.name}** : {r.gold} or, {r.xp} xp{items_label}")
            if result.leveled_up and result.new_level is not None:
                lines.append(f"🎉 Niveau **{result.new_level}** atteint !")

            # Re-fetch et mise à jour du message principal pour cacher le bouton
            new_state = self._fetch_state(claim_interaction)
            new_embed = build_daily_embed(
                claim_interaction.user.display_name, new_state,
            )
            new_view = self._build_view(claim_interaction, new_state)
            await claim_interaction.edit_original_response(
                embed=new_embed, view=new_view,
            )
            await claim_interaction.followup.send(
                "\n".join(lines), ephemeral=True,
            )

        return QuestClaimView(
            author_id=interaction.user.id,
            claimable_count=state.claimable_count,
            on_claim=on_claim,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DailyQuestCog(bot))
