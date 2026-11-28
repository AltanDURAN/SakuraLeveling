"""Boutons du message du world boss (Rejoindre, Quitter, Horaires) — vue
persistante. Sortie de `world_boss_cog.py` le 28/11/2026 (audit) : texte
inchangé ; toujours importable depuis `world_boss_cog`."""

from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import discord

from app.application.use_cases.world_boss import (
    JoinWorldBossUseCase,
    LeaveWorldBossUseCase,
)
from app.bot.embeds.limits import fit_lines
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.world_boss_repository import WorldBossRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.pacing.pacing_loader import get_pacing
from app.domain.services import pacing_service
from app.shared.formatters import format_int
from discord.utils import escape_markdown
from app.bot.rules_gate import GatedView


if TYPE_CHECKING:
    from app.bot.cogs.world_boss_cog import WorldBossCog


# Combat quotidien : inscription de minuit à la fermeture, lancement auto à
# l'heure de l'assaut (Paris) — réglables depuis l'admin (Monde › Rythme).
_PARIS = ZoneInfo("Europe/Paris")


class WorldBossView(GatedView):
    """View persistante attachée au message du boss (3 boutons).

    Persistante = `timeout=None` + chaque bouton a un `custom_id` stable.
    Au démarrage du bot, le cog ré-enregistre une instance via
    `bot.add_view(...)` pour que Discord reconnecte les clics aux callbacks
    sans avoir besoin du message original. Indispensable pour un boss qui
    peut survivre à un reboot.
    """

    def __init__(self, cog: "WorldBossCog | None" = None) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.vote_button.label = f"Horaires (assaut à {pacing_service.fight_label(get_pacing().raid)})"

    def _resolve_cog(self, interaction: discord.Interaction) -> "WorldBossCog | None":
        """Si la view a été restaurée sans cog (pas de référence au reboot),
        on récupère le cog vivant depuis le bot."""
        if self.cog is not None:
            return self.cog
        return interaction.client.get_cog("WorldBossCog")

    async def _resolve_active_boss_id(self) -> int | None:
        """Trouve l'id du boss actuellement actif (peu importe quel message
        a déclenché l'interaction). Renvoie None si aucun boss actif."""
        with get_db_session() as session:
            boss = WorldBossRepository(session).get_active()
        return boss.id if boss else None

    @discord.ui.button(
        label="Rejoindre",
        style=discord.ButtonStyle.success,
        emoji="🤝",
        custom_id="world_boss:join",
    )
    async def join_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        # Fenêtre d'inscription : de minuit à la fermeture (Paris). Fermée
        # ensuite, jusqu'à l'assaut puis réouverte le lendemain à minuit.
        raid = get_pacing().raid
        if pacing_service.registration_closed(raid, datetime.now(_PARIS)):
            fight, close = pacing_service.fight_label(raid), pacing_service.close_label(raid)
            await interaction.followup.send(
                f"🚪 Inscriptions **fermées** depuis {close}. L'assaut du jour part à "
                f"**{fight}**. Reviens t'inscrire après minuit pour celui de demain.",
                ephemeral=True,
            )
            return
        with get_db_session() as session:
            use_case = JoinWorldBossUseCase(
                world_boss_repository=WorldBossRepository(session),
                player_repository=PlayerRepository(session),
            )
            result = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )
        # Détail des inscrits : savoir QUI est déjà là (et donc si ça vaut le
        # coup d'attendre du monde) est le premier réflexe après s'être inscrit.
        roster = await self._build_roster_embed()
        await interaction.followup.send(
            result.message, embed=roster, ephemeral=True,
        )
        if result.success:
            cog = self._resolve_cog(interaction)
            boss_id = await self._resolve_active_boss_id()
            if cog and boss_id:
                await cog.refresh_boss_message(boss_id)

    async def _build_roster_embed(self) -> discord.Embed | None:
        """Liste des inscrits au prochain assaut, avec leur état (a voté / a
        déjà frappé cette semaine) et le bonus d'équipe atteint."""
        with get_db_session() as session:
            repo = WorldBossRepository(session)
            boss = repo.get_active()
            if boss is None:
                return None
            joined = repo.list_joined_participants(boss.id)
            metrics = {
                m.player_id: m
                for m in repo.list_participations_with_metrics(boss.id)
            }
            player_repo = PlayerRepository(session)
            lines: list[str] = []
            for part in joined:
                profile = player_repo.get_profile_by_player_id(part.player_id)
                name = profile.player.display_name if profile else f"#{part.player_id}"
                marks = []
                fought = metrics.get(part.player_id)
                if fought is not None and fought.fights_count > 0:
                    marks.append(f"⚔️ {format_int(fought.damage_dealt)} dégâts")
                suffix = f" — {' · '.join(marks)}" if marks else ""
                lines.append(f"• **{escape_markdown(name)}**{suffix}")

        count = len(lines)
        bonus = min(50, max(0, (count - 1) * 5))
        embed = discord.Embed(
            title=f"🛡️ Inscrits pour l'assaut de {pacing_service.fight_label(get_pacing().raid)} — {count}",
            description=(
                fit_lines(lines, budget=3900, more="… et {n} autre(s) inscrit(s)") if lines
                else "Personne pour l'instant. Sois le premier à t'engager !"
            ),
            color=discord.Color.gold(),
        )
        embed.set_footer(
            text=(f"Bonus d'équipe actuel : +{bonus}% de stats "
                  f"(+5 % par combattant, max +50 %)")
        )
        return embed

    @discord.ui.button(
        label="Quitter",
        style=discord.ButtonStyle.secondary,
        emoji="🚪",
        custom_id="world_boss:leave",
    )
    async def leave_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            use_case = LeaveWorldBossUseCase(
                world_boss_repository=WorldBossRepository(session),
                player_repository=PlayerRepository(session),
            )
            result = use_case.execute(discord_id=interaction.user.id)
        await interaction.followup.send(result.message, ephemeral=True)
        if result.success:
            cog = self._resolve_cog(interaction)
            boss_id = await self._resolve_active_boss_id()
            if cog and boss_id:
                await cog.refresh_boss_message(boss_id)

    @discord.ui.button(
        label="Horaires",             # il informe : gris, pas un bouton d'action (décision de l'auteur, 14/11/2026)
        style=discord.ButtonStyle.secondary,
        emoji="⏰",
        custom_id="world_boss:vote",
    )
    async def vote_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        # Le vote a été remplacé par un combat quotidien automatique.
        # Ce bouton est désormais purement informatif.
        raid = get_pacing().raid
        fight, close = pacing_service.fight_label(raid), pacing_service.close_label(raid)
        await interaction.response.send_message(
            f"⏰ **Combat automatique chaque jour à {fight}** (heure de Paris).\n"
            f"Inscris-toi via **🤝 Rejoindre** avant {close}. À {fight}, tous les "
            "inscrits combattent le boss, puis la liste est remise à zéro.",
            ephemeral=True,
        )
