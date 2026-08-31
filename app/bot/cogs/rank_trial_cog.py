"""Cog `/epreuve` : gagner son rang au combat plutôt qu'à la commande admin.

Le rang ouvre les zones de farm. Jusqu'ici il ne montait que par
`/admin set_rank` — la progression n'était donc pas un système de jeu.

Deux verrous, dans cet ordre :
  1. un SEUIL de power score ouvre l'épreuve (« tu as la puissance ») ;
  2. il faut battre le GARDIEN en combat solo (« tu sais t'en servir »).

Un échec pose un cooldown : on ne relance pas l'épreuve en boucle jusqu'à
tomber sur un bon tirage.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, UTC

import discord
from discord import app_commands
from discord.ext import commands

from app.bot.cogs._mixins import BetaChannelOnlyMixin
from app.bot.rank_roles import RANK_ORDER, current_rank, set_rank_role
from app.application.services.player_stats_resolver import resolve_player_stats
from app.domain.entities.mob_definition import MobDefinition
from app.domain.services.party_combat_service import PartyCombatService
from app.domain.services.power_score_service import PowerScoreService
from app.domain.services.rank_trial_service import RankTrialService, TrialEligibility
from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.rank_trials import rank_trial_loader
from app.shared.formatters import format_int

_logger = logging.getLogger("sakura.rank_trials")

COOLDOWN_ACTION = "rank_trial"
MAX_TURNS = 60


def _service() -> RankTrialService:
    return RankTrialService(rank_trial_loader.list_trials(), RANK_ORDER)


def _guardian_mob(guardian) -> MobDefinition:
    now = datetime.now(UTC)
    return MobDefinition(
        id=0, code="gardien_epreuve", name=guardian.name, description=guardian.lore,
        image_name="", family="gardien",
        max_hp=guardian.max_hp, current_hp=guardian.max_hp,
        attack=guardian.attack, defense=guardian.defense,
        xp_reward=0, gold_reward=0, spawn_weight=0,
        speed=guardian.speed, crit_chance=guardian.crit_chance,
        crit_damage=guardian.crit_damage, dodge=guardian.dodge,
        hp_regeneration=0, loot_table=None,
        created_at=now, updated_at=now, element="",
    )


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
            active_class = ClassRepository(session).get_current_class_for_player(
                player_id,
            )
            stats = resolve_player_stats(session, profile, worn, active_class)
            power = PowerScoreService().calculate_from_stats(stats)

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
                f"Bats-le en combat singulier et le rang **{trial.rank}** est à toi."
            ),
            color=discord.Color.dark_red() if not elig.can_attempt
            else discord.Color.green(),
        )
        embed.add_field(
            name="Le gardien",
            value=(
                f"❤️ {format_int(g.max_hp)} PV\n"
                f"⚔️ {g.attack} attaque\n"
                f"🛡️ {g.defense} défense"
            ),
            inline=True,
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

    # ------------------------------------------------------------ combat --
    def _fight(self, elig: TrialEligibility, player_id: int, stats, user) -> tuple:
        """Combat solo contre le gardien. Renvoie (victoire, tours, pv restants)."""
        party = [{
            "player_id": player_id, "user_id": user.id,
            "name": user.display_name, "avatar_url": "",
            "stats": stats, "current_hp": stats.max_hp, "max_hp": stats.max_hp,
            "current_mana": stats.mana_max, "mana_max": stats.mana_max,
        }]
        result = PartyCombatService().fight_party_vs_mob(
            party, _guardian_mob(elig.trial.guardian), max_turns=MAX_TURNS,
        )
        contribution = next(
            (c for c in result.contributions if c.player_id == player_id), None,
        )
        remaining = int(contribution.final_hp) if contribution else 0
        return result.victory, result.turns, remaining

    def _apply_outcome(self, player_id: int, victory: bool) -> None:
        """Échec ⇒ cooldown. Les PV réels ne sont pas touchés : l'épreuve est
        un duel rituel, pas une sortie de farm."""
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
    def __init__(self, cog: RankTrialCog, elig, player_id, stats, user) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.elig = elig
        self.player_id = player_id
        self.stats = stats
        self.user = user

    @discord.ui.button(
        label="Affronter le gardien", style=discord.ButtonStyle.danger, emoji="⚔️",
    )
    async def fight(
        self, interaction: discord.Interaction, button: discord.ui.Button,
    ) -> None:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                "❌ Cette épreuve n'est pas la tienne.", ephemeral=True,
            )
            return

        button.disabled = True
        await interaction.response.edit_message(view=self)

        victory, turns, remaining = await asyncio.to_thread(
            self.cog._fight, self.elig, self.player_id, self.stats, self.user,
        )
        await asyncio.to_thread(
            self.cog._apply_outcome, self.player_id, victory,
        )

        trial = self.elig.trial
        if victory:
            promoted = False
            if isinstance(interaction.user, discord.Member):
                promoted = await set_rank_role(interaction.user, trial.rank)
            embed = discord.Embed(
                title=f"🏅 Rang {trial.rank} obtenu",
                description=(
                    f"**{trial.guardian.name}** tombe au bout de {turns} tours. "
                    f"Il te restait {format_int(remaining)} PV.\n\n"
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
        else:
            hours = rank_trial_loader.retry_cooldown_hours()
            embed = discord.Embed(
                title="💀 Épreuve échouée",
                description=(
                    f"**{trial.guardian.name}** te met à terre après {turns} tours.\n\n"
                    f"Reviens plus fort — tu pourras retenter dans **{hours} h**."
                ),
                color=discord.Color.dark_red(),
            )
        self.stop()
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RankTrialCog(bot))
