"""Cog des quêtes hebdomadaires (/weekly et /weekly_claim).

3 quêtes random tirées chaque lundi 00:00 UTC pour chaque joueur. Mix
easy/medium/hard si possible. Les progrès sont mis à jour automatiquement
au fil des évènements de jeu (kill, duel, craft, gather, daily, boss).
"""

import discord
from discord import app_commands
from discord.ext import commands

from app.application.use_cases.weekly_quests import (
    ClaimWeeklyQuestUseCase,
    GetWeeklyQuestsUseCase,
    QuestStatus,
    WeeklyQuestState,
)
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.weekly_quest_repository import (
    WeeklyQuestRepository,
)
from app.infrastructure.db.session import get_db_session


def _build_progress_bar(progress: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return "—"
    ratio = min(1.0, max(0.0, progress / total))
    filled = int(round(ratio * width))
    return "▰" * filled + "▱" * (width - filled)


def _tier_emoji(tier: str) -> str:
    return {"easy": "🟢", "medium": "🟡", "hard": "🔴"}.get(tier, "⚪")


def build_weekly_embed(
    display_name: str, state: WeeklyQuestState
) -> discord.Embed:
    embed = discord.Embed(
        title=f"📅 Quêtes hebdo de {display_name}",
        description=(
            f"Semaine du <t:{int(state.week_start.timestamp())}:D>. "
            "Récompenses récupérables avec `/weekly_claim`."
        ),
        color=discord.Color.purple(),
    )

    if not state.quests:
        embed.add_field(name="—", value="Aucune quête assignée.", inline=False)
        return embed

    for q in state.quests:
        status_emoji = "✅" if q.completed else "⏳"
        if q.claimed:
            status_emoji = "🎁"
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
            name=f"{status_emoji} {_tier_emoji(q.tier)} {q.name} (`{q.code}`)",
            value=value,
            inline=False,
        )
    return embed


class WeeklyQuestCog(commands.Cog):
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
        name="weekly",
        description="Afficher les 3 quêtes hebdomadaires + progression",
    )
    async def weekly(self, interaction: discord.Interaction) -> None:
        with get_db_session() as session:
            use_case = GetWeeklyQuestsUseCase(
                player_repository=PlayerRepository(session),
                quest_repository=WeeklyQuestRepository(session),
            )
            state = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )

        embed = build_weekly_embed(interaction.user.display_name, state)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="weekly_claim",
        description="Réclamer la récompense d'une quête hebdomadaire complétée",
    )
    @app_commands.describe(quest_code="Code de la quête à réclamer (autocomplete)")
    async def weekly_claim(
        self,
        interaction: discord.Interaction,
        quest_code: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            use_case = ClaimWeeklyQuestUseCase(
                player_repository=PlayerRepository(session),
                quest_repository=WeeklyQuestRepository(session),
                item_repository=ItemRepository(session),
                inventory_repository=InventoryRepository(session),
            )
            result = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
                quest_code=quest_code,
            )

        if not result.success:
            await interaction.followup.send(result.message, ephemeral=True)
            return

        items_label = (
            ", ".join(f"{qty}× `{c}`" for c, qty in result.items) if result.items else "—"
        )
        msg = (
            f"{result.message}\n"
            f"💰 +{result.gold} or | ✨ +{result.xp} xp | 🎁 {items_label}"
        )
        if result.leveled_up and result.new_level is not None:
            msg += f"\n🎉 Niveau **{result.new_level}** atteint !"
        await interaction.followup.send(msg, ephemeral=True)

    @weekly_claim.autocomplete("quest_code")
    async def quest_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        with get_db_session() as session:
            use_case = GetWeeklyQuestsUseCase(
                player_repository=PlayerRepository(session),
                quest_repository=WeeklyQuestRepository(session),
            )
            state = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )

        # On ne propose que les quêtes complétées non-claim
        current_lower = current.lower()
        out: list[app_commands.Choice[str]] = []
        for q in state.quests:
            if not q.completed or q.claimed:
                continue
            if current_lower in q.code.lower() or current_lower in q.name.lower():
                out.append(
                    app_commands.Choice(
                        name=f"✅ {q.name} ({q.code})", value=q.code,
                    )
                )
            if len(out) >= 25:
                break
        return out


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WeeklyQuestCog(bot))
