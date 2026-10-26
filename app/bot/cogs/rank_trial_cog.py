"""Cog `/epreuve` : gagner son rang au combat plutôt qu'à la commande admin.

Le rang ouvre les zones de farm. Deux verrous, dans cet ordre :
  1. un SEUIL de power score ouvre l'épreuve (« tu as la puissance ») ;
  2. il faut réussir l'épreuve de SON RÔLE face au gardien (« tu sais t'en
     servir ») — les mêmes épreuves que /defi, au niveau du rang (26/10/2026,
     cf. `rank_trial_service`) : ⚔️ DPS, 🛡️ Tank ou 💚 Soutien, au choix.

Un échec pose un cooldown. Une promotion est annoncée dans le salon général
(`settings.rank_announce_channel_id`).
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, UTC

import discord
from discord import app_commands
from discord.ext import commands

from app.bot.cogs._mixins import BetaChannelOnlyMixin
from app.bot.rank_roles import RANK_ORDER, current_rank, set_rank_role
from app.application.services.player_stats_resolver import resolve_player_stats
from app.bot.embeds.role_trial_embeds import NO_POTIONS
from app.domain.services import role_trial_service as rts
from app.domain.services.rank_trial_service import ROLE_GOALS, RankTrialService, TrialEligibility
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.rank_trials import rank_trial_loader
from app.shared.formatters import format_int

_logger = logging.getLogger("sakura.rank_trials")

COOLDOWN_ACTION = "rank_trial"


def _service() -> RankTrialService:
    return RankTrialService(rank_trial_loader.list_trials(), RANK_ORDER)


def _goal(role: str, required: int) -> str:
    return ROLE_GOALS[role].format(n=format_int(required))


class RankTrialCog(BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------ lecture --
    def _load_state(self, interaction: discord.Interaction) -> tuple:
        """(éligibilité, player_id, stats) — lu en une seule session."""
        with get_db_session() as session:
            profile = PlayerRepository(session).get_or_create_by_discord_id(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )
            player_id = profile.player.id
            worn = EquipmentRepository(session).list_by_player_id(player_id)
            stats = resolve_player_stats(session, profile, worn)
            from app.application.services.combat_passives_resolver import resolve_player_power

            power = resolve_player_power(session, player_id, stats)

            cooldown = CooldownRepository(session).get_by_player_and_action(
                player_id, COOLDOWN_ACTION,
            )

        until = None
        if cooldown is not None:
            nxt = cooldown.next_available_at
            if nxt.tzinfo is None:
                nxt = nxt.replace(tzinfo=UTC)
            if nxt > datetime.now(UTC):
                until = f"<t:{int(nxt.timestamp())}:R>"

        rank = current_rank(interaction.user) if isinstance(
            interaction.user, discord.Member,
        ) else RANK_ORDER[0]
        eligibility = _service().evaluate(rank, power, on_cooldown_until=until)
        return eligibility, player_id, stats

    def _build_embed(self, elig: TrialEligibility) -> discord.Embed:
        if elig.at_max_rank:
            return discord.Embed(
                title="🏅 Rang maximal atteint",
                description=(
                    f"Tu portes déjà le rang **{elig.current_rank}**. "
                    f"Plus personne ne garde la porte au-dessus."
                ),
                color=discord.Color.gold(),
            )

        trial = elig.trial
        g = trial.guardian
        embed = discord.Embed(
            title=f"⚔️ Épreuve du rang {trial.rank}",
            description=(
                f"**{g.name}**\n*{g.lore}*\n\n"
                f"Choisis ton rôle et prouve ta maîtrise : réussis et le rang "
                f"**{trial.rank}** est à toi."
            ),
            color=discord.Color.dark_red() if not elig.can_attempt
            else discord.Color.green(),
        )
        embed.add_field(
            name="Les épreuves (au choix)",
            value="\n".join(f"{rts.ROLE_LABELS[r]} — {_goal(r, trial.thresholds[r])}"
                             for r in trial.roles()),
            inline=False,
        )
        embed.add_field(
            name="Ta puissance",
            value=(
                f"{format_int(elig.power)} / {format_int(trial.required_power)}\n"
                + ("✅ seuil atteint" if elig.power >= trial.required_power
                   else f"il t'en manque {format_int(elig.missing_power)}")
            ),
            inline=True,
        )
        embed.add_field(name="Règle", value=NO_POTIONS, inline=False)
        embed.set_footer(text=f"Rang actuel : {elig.current_rank}")
        if elig.blocked_reason:
            embed.add_field(
                name="Pas encore", value=elig.blocked_reason, inline=False,
            )
        return embed

    # --------------------------------------------------------- commandes --
    @app_commands.command(
        name="epreuve",
        description="Affronte le gardien du rang suivant pour être promu",
    )
    async def epreuve(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        elig, player_id, stats = await asyncio.to_thread(
            self._load_state, interaction,
        )
        embed = self._build_embed(elig)

        if not elig.can_attempt:
            await interaction.followup.send(embed=embed)
            return

        view = _TrialView(self, elig, player_id, stats, interaction.user)
        await interaction.followup.send(embed=embed, view=view)

    # ------------------------------------------------------------ épreuve --
    def _run(self, elig: TrialEligibility, role: str, player_id: int, stats, user):
        """Un essai de l'épreuve `role` face au gardien (tirage frais à
        chaque tentative : contrairement aux défis, l'épreuve se retente)."""
        from app.application.services.combat_passives_resolver import resolve_party_passives

        with get_db_session() as session:
            passives, tactics = resolve_party_passives(session, [player_id])
        trial = elig.trial
        return rts.run_trial(
            role, rts.VARIANTS[role][0], player_id=player_id, name=user.display_name,
            stats=stats, passives=passives.get(player_id), tactic=tactics.get(player_id),
            seed=random.SystemRandom().randrange(2 ** 63), level=trial.level,
            opponent_name=trial.guardian.name,
        )

    async def announce_promotion(self, member: discord.abc.User, trial, role: str) -> None:
        """Annonce publique d'une promotion dans le salon général."""
        channel = self.bot.get_channel(settings.rank_announce_channel_id) \
            if settings.rank_announce_channel_id else None
        if channel is None:
            return
        embed = discord.Embed(
            title=f"🏅 Nouveau rang {trial.rank} !",
            description=(f"{member.mention} accède au rang **{trial.rank}** : épreuve "
                         f"{rts.ROLE_LABELS[role]} réussie face à **{trial.guardian.name}**."),
            color=discord.Color.gold(),
        )
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=True))
        except discord.HTTPException:
            _logger.warning("annonce de promotion impossible", exc_info=True)

    def _apply_outcome(self, player_id: int, victory: bool) -> None:
        """Échec ⇒ cooldown. Les PV réels ne sont pas touchés : l'épreuve est
        un combat rituel, pas une sortie de farm."""
        if victory:
            return
        hours = rank_trial_loader.retry_cooldown_hours()
        now = datetime.now(UTC)
        with get_db_session() as session:
            CooldownRepository(session).upsert(
                player_id=player_id,
                action_key=COOLDOWN_ACTION,
                last_used_at=now,
                next_available_at=now + timedelta(hours=hours),
            )


class _TrialView(discord.ui.View):
    """Un bouton par rôle proposé à ce rang."""

    def __init__(self, cog: RankTrialCog, elig, player_id, stats, user) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.elig = elig
        self.player_id = player_id
        self.stats = stats
        self.user = user
        for role in elig.trial.roles():
            self.add_item(_RoleButton(self, role))


class _RoleButton(discord.ui.Button):
    def __init__(self, view: _TrialView, role: str) -> None:
        super().__init__(label=rts.ROLE_LABELS[role], style=discord.ButtonStyle.danger)
        self._owner = view
        self._role = role

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self._owner
        if interaction.user.id != view.user.id:
            await interaction.response.send_message(
                "❌ Cette épreuve n'est pas la tienne.", ephemeral=True,
            )
            return
        for child in view.children:
            child.disabled = True
        await interaction.response.edit_message(view=view)

        trial = view.elig.trial
        run = await asyncio.to_thread(
            view.cog._run, view.elig, self._role, view.player_id, view.stats, view.user,
        )
        victory = trial.passed(self._role, run.score)
        await asyncio.to_thread(view.cog._apply_outcome, view.player_id, victory)

        required = trial.thresholds[self._role]
        unit = {"dps": "dégâts infligés", "tank": "dégâts encaissés", "soutien": "PV soignés"}[self._role]
        score_line = f"{rts.ROLE_LABELS[self._role]} : **{format_int(run.score)}** {unit} / {format_int(required)} requis."
        if victory:
            promoted = False
            if isinstance(interaction.user, discord.Member):
                promoted = await set_rank_role(interaction.user, trial.rank)
            embed = discord.Embed(
                title=f"🏅 Rang {trial.rank} obtenu",
                description=(
                    f"{score_line}\n**{trial.guardian.name}** s'incline.\n\n"
                    + (
                        f"Tu portes désormais le rang **{trial.rank}** — "
                        f"de nouvelles zones s'ouvrent à toi."
                        if promoted
                        else "⚠️ Le rôle Discord n'a pas pu être attribué : "
                             "préviens un admin."
                    )
                ),
                color=discord.Color.gold(),
            )
            if promoted:
                await view.cog.announce_promotion(interaction.user, trial, self._role)
        else:
            hours = rank_trial_loader.retry_cooldown_hours()
            embed = discord.Embed(
                title="💀 Épreuve échouée",
                description=(
                    f"{score_line}\n**{trial.guardian.name}** n'est pas convaincu.\n\n"
                    f"Reviens plus fort — tu pourras retenter dans **{hours} h** "
                    f"(ou tout de suite avec un sceau du second souffle, chez Sorn)."
                ),
                color=discord.Color.dark_red(),
            )
        view.stop()
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RankTrialCog(bot))
