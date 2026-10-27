"""Or au quotidien : `/payer` (virement entre joueurs) et `/daily`
(récompense quotidienne, série, sablier de fidélité).

Découpé de `player_cog.py` le 26/10/2026 (roadmap N6).
"""

import discord
from discord import app_commands
from discord.ext import commands
from app.application.use_cases.transfer_gold import TransferGoldUseCase
from app.application.use_cases.claim_daily_reward import ClaimDailyRewardUseCase
from app.bot.embeds.daily_embeds import build_daily_cooldown_embed, build_daily_success_embed
from app.domain.services.cooldown_service import CooldownService
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.player_career_stats_repository import (
    PlayerCareerStatsRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session
from app.bot.cogs._mixins import BetaChannelOnlyMixin, PlayerLookupMixin


class EconomyCog(PlayerLookupMixin, BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="payer",
        description="Envoyer de l'or à un autre joueur",
    )
    @app_commands.describe(
        target="Joueur destinataire",
        amount="Montant à envoyer (>= 1)",
    )
    async def pay(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        amount: app_commands.Range[int, 1, 1_000_000_000],
    ) -> None:
        if target.bot:
            await interaction.response.send_message(
                "❌ Vous ne pouvez pas envoyer d'or à un bot.",
                ephemeral=True,
            )
            return

        with get_db_session() as session:
            use_case = TransferGoldUseCase(PlayerRepository(session))
            result = use_case.execute(
                sender_discord_id=interaction.user.id,
                sender_username=interaction.user.name,
                sender_display_name=interaction.user.display_name,
                receiver_discord_id=target.id,
                receiver_display_name=target.display_name,
                amount=amount,
            )

        if not result.success:
            await interaction.response.send_message(result.message, ephemeral=True)
            return

        await interaction.response.send_message(
            f"💸 {interaction.user.mention} a envoyé **{amount}** or à {target.mention}.\n"
            f"_Votre solde : {result.sender_balance_after} or._"
        )

    @app_commands.command(name="daily", description="Récupérer votre récompense quotidienne")
    async def daily(self, interaction: discord.Interaction) -> None:
        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            cooldown_repository = CooldownRepository(session)

            use_case = ClaimDailyRewardUseCase(
                player_repository=player_repository,
                cooldown_repository=cooldown_repository,
                cooldown_service=CooldownService(),
                career_stats_repository=PlayerCareerStatsRepository(session),
            )

            result = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )

        if result.success:
            embed = build_daily_success_embed(
                streak=result.streak,
                gold_gained=result.gold_gained,
                bonus_items=result.bonus_items,
                streak_bonus_pct=result.streak_bonus_pct,
                days_missed=result.days_missed,
                streak_before_absence=result.streak_before_absence,
                titles_unlocked=result.titles_unlocked,
                guard_used=result.guard_used,
            )
            await interaction.response.send_message(embed=embed)
        else:
            embed = build_daily_cooldown_embed(
                streak=result.streak,
                next_available_at=result.next_available_at,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EconomyCog(bot))
